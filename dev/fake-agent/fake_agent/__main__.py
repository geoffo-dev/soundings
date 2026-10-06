"""``fake-agent`` / ``python -m fake_agent``: serve on ``FAKE_AGENT_HOST``:``FAKE_AGENT_PORT``
(default 0.0.0.0:8083, kagent's controller port)."""

from __future__ import annotations

import logging
import os

import uvicorn

from fake_agent.app import create_app
from fake_agent.config import Settings


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("FAKE_AGENT_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    # The SDK logs request bodies at DEBUG (message text, tool history): keep it quiet.
    logging.getLogger("a2a").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    settings = Settings.from_env()
    if not settings.mcp_url:
        logging.getLogger("fake_agent").warning(
            "FAKE_AGENT_MCP_URL is not set: runs fail when they call Soundings"
        )
    uvicorn.run(
        create_app(settings),
        host=os.environ.get("FAKE_AGENT_HOST", "0.0.0.0"),  # noqa: S104 (a container's port)
        port=int(os.environ.get("FAKE_AGENT_PORT", "8083")),
        log_level="warning",
        access_log=False,
    )


if __name__ == "__main__":
    main()
