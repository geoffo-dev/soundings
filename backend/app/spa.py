"""Serve the built single-page app (``frontend/dist``) from the API process.

* ``/assets/*`` (Vite's content-hashed files): long-lived immutable caching.
* Any other GET/HEAD that matches no route and is not a backend path serves a
  file from the build root if one exists (favicon, fonts, ...) or ``index.html``,
  both with ``Cache-Control: no-cache`` so new deploys are picked up.
* Backend paths (``/api``, ``/mcp``, ``/.well-known``, ...) keep returning problem+json
  404s (an MCP client probing for OAuth metadata after a 401 gets a clean 404).
* Precompressed files (performance review B4): the image build writes ``<file>.br`` and
  ``<file>.gz`` next to every compressible file (``scripts/precompress-assets.mjs``);
  a client that accepts Brotli or gzip gets one (``Content-Encoding``, ``Vary:
  Accept-Encoding``), everyone else the file itself. A build without them (``npm run
  build``, the e2e stack) is served as it is.
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import mimetypes
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import FileResponse, Response

from app.errors import NotFoundProblem
from app.middleware import accepted_encodings

BACKEND_PATH_PREFIXES = ("/api", "/mcp", "/metrics", "/healthz", "/readyz", "/.well-known")
"""Paths the SPA fallback never answers. Add new non-SPA top-level paths here."""

IMMUTABLE = "public, max-age=31536000, immutable"
REVALIDATE = "no-cache"

PRECOMPRESSED: Final = (("br", ".br"), ("gzip", ".gz"))
"""Codings the build may have written next to a file, in order of preference."""

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


def file_response(request: Request, file: Path, *, cache_control: str) -> FileResponse:
    """``file``, or its precompressed ``.br`` / ``.gz`` twin when the client takes it."""
    accepted = accepted_encodings(request.scope)
    media_type = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
    headers = {"Cache-Control": cache_control}
    for coding, suffix in PRECOMPRESSED:
        twin = file.with_name(file.name + suffix)
        if twin.is_file():
            headers["Vary"] = "Accept-Encoding"
            if coding in accepted:
                headers["Content-Encoding"] = coding
                return FileResponse(twin, media_type=media_type, headers=headers)
    return FileResponse(file, media_type=media_type, headers=headers)


@dataclass(frozen=True, slots=True)
class SpaBundle:
    """A built SPA; ``index.html`` is read once so its CSP hashes always match (and
    gzipped once, for clients that take it)."""

    root: Path
    index_html: bytes
    script_hashes: tuple[str, ...]
    index_gzip: bytes = field(default=b"", repr=False)

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
            index_gzip=gzip.compress(html, compresslevel=9, mtime=0),
        )

    def index_response(self, request: Request | None = None) -> Response:
        headers = {"Cache-Control": REVALIDATE, "Vary": "Accept-Encoding"}
        body = self.index_html
        if request is not None and "gzip" in accepted_encodings(request.scope):
            body = self.index_gzip
            headers["Content-Encoding"] = "gzip"
        return Response(body, media_type="text/html; charset=utf-8", headers=headers)

    async def fallback(self, request: Request) -> Response | None:
        """Answer an unmatched request, or ``None`` to let it 404."""
        if request.method not in {"GET", "HEAD"}:
            return None
        path: str = request.scope["path"]
        if is_backend_path(path):
            return None
        file = _safe_file(self.root, path.lstrip("/"))
        if file is not None and file.name != "index.html":
            return file_response(request, file, cache_control=REVALIDATE)
        return self.index_response(request)


def install_spa(app: FastAPI, bundle: SpaBundle) -> None:
    """Add the ``/assets`` route. The fallback is wired via the 404 handler."""
    assets_root = bundle.root / "assets"
    router = APIRouter(include_in_schema=False)

    @router.api_route("/assets/{asset_path:path}", methods=["GET", "HEAD"])
    async def spa_asset(request: Request, asset_path: str) -> FileResponse:
        file = _safe_file(assets_root, asset_path) if assets_root.is_dir() else None
        if file is None:
            raise NotFoundProblem
        return file_response(request, file, cache_control=IMMUTABLE)

    app.include_router(router)
