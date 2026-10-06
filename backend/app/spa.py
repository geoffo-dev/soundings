"""Serve the built single-page app (``frontend/dist``) from the API process.

* ``/assets/*`` (Vite's content-hashed files): long-lived immutable caching.
* Any other GET/HEAD that matches no route and is not a backend path serves a
  file from the build root if one exists (favicon, fonts, ...) or ``index.html``,
  both with ``Cache-Control: no-cache`` so new deploys are picked up.
* Backend paths (``/api``, ``/mcp``, ``/.well-known``, ...) keep returning problem+json
  404s (an MCP client probing for OAuth metadata after a 401 gets a clean 404).
"""

from __future__ import annotations

import base64
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import FileResponse, Response

from app.errors import NotFoundProblem

BACKEND_PATH_PREFIXES = ("/api", "/mcp", "/metrics", "/healthz", "/readyz", "/.well-known")
"""Paths the SPA fallback never answers. Add new non-SPA top-level paths here."""

IMMUTABLE = "public, max-age=31536000, immutable"
REVALIDATE = "no-cache"

_INLINE_SCRIPT = re.compile(r"<script\b([^>]*)>(.*?)</script\s*>", re.IGNORECASE | re.DOTALL)
_SRC_ATTRIBUTE = re.compile(r"\bsrc\s*=", re.IGNORECASE)


def inline_script_hashes(html: str) -> tuple[str, ...]:
    """CSP ``sha256-...`` sources for each inline ``<script>`` in ``html``."""
    hashes: list[str] = []
    for attributes, body in _INLINE_SCRIPT.findall(html):
        if _SRC_ATTRIBUTE.search(attributes) or not body.strip():
            continue
        digest = base64.b64encode(hashlib.sha256(body.encode()).digest()).decode("ascii")
        hashes.append(f"sha256-{digest}")
    return tuple(dict.fromkeys(hashes))


def is_backend_path(path: str) -> bool:
    return any(path == prefix or path.startswith(prefix + "/") for prefix in BACKEND_PATH_PREFIXES)


def _safe_file(root: Path, relative: str) -> Path | None:
    """Resolve ``relative`` inside ``root``; ``None`` for traversal, dotfiles or non-files."""
    if not relative or "\x00" in relative:
        return None
    try:
        candidate = (root / relative).resolve()
    except (OSError, ValueError):
        return None
    if not candidate.is_relative_to(root):
        return None
    if any(part.startswith(".") for part in candidate.relative_to(root).parts):
        return None
    return candidate if candidate.is_file() else None


@dataclass(frozen=True, slots=True)
class SpaBundle:
    """A built SPA; ``index.html`` is read once so its CSP hashes always match."""

    root: Path
    index_html: bytes
    script_hashes: tuple[str, ...]

    @classmethod
    def load(cls, static_dir: Path) -> SpaBundle | None:
        """Load ``static_dir`` if it holds a build (``index.html``), else ``None``."""
        index = static_dir / "index.html"
        if not index.is_file():
            return None
        html = index.read_bytes()
        return cls(
            root=static_dir.resolve(),
            index_html=html,
            script_hashes=inline_script_hashes(html.decode("utf-8")),
        )

    def index_response(self) -> Response:
        return Response(
            self.index_html,
            media_type="text/html; charset=utf-8",
            headers={"Cache-Control": REVALIDATE},
        )

    async def fallback(self, request: Request) -> Response | None:
        """Answer an unmatched request, or ``None`` to let it 404."""
        if request.method not in {"GET", "HEAD"}:
            return None
        path: str = request.scope["path"]
        if is_backend_path(path):
            return None
        file = _safe_file(self.root, path.lstrip("/"))
        if file is not None and file.name != "index.html":
            return FileResponse(file, headers={"Cache-Control": REVALIDATE})
        return self.index_response()


def install_spa(app: FastAPI, bundle: SpaBundle) -> None:
    """Add the ``/assets`` route. The fallback is wired via the 404 handler."""
    assets_root = bundle.root / "assets"
    router = APIRouter(include_in_schema=False)

    @router.api_route("/assets/{asset_path:path}", methods=["GET", "HEAD"])
    async def spa_asset(asset_path: str) -> FileResponse:
        file = _safe_file(assets_root, asset_path) if assets_root.is_dir() else None
        if file is None:
            raise NotFoundProblem
        return FileResponse(file, headers={"Cache-Control": IMMUTABLE})

    app.include_router(router)
