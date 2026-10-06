"""Settings from the environment (``FAKE_AGENT_*``), read once at start-up; agent keys
are re-read from ``FAKE_AGENT_KEYS_DIR`` on every request, so a Secret mounted there
(or a file a test writes) takes effect without a restart."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

LABEL = re.compile(r"[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?")
"""A Kubernetes namespace or name (DNS-1123 label), as kagent and Soundings use them."""

KEY = re.compile(r"sdg_[A-Za-z0-9_]{8,200}")
"""A Soundings API key (``sdg_`` + lookup id + secret)."""

BEHAVIOURS = (
    "normal",
    "slow",
    "lingers",
    "fails",
    "silent",
    "asks",
    "rejects",
    "blind-probe",
    "strays",
    "late",
    "no-cancel",
    "unavailable",
    "drops",
)
"""What an agent does (README.md): by the suffix of its name (``idea-evaluator-slow``)
or set per agent in ``FAKE_AGENT_BEHAVIOURS``; ``normal`` otherwise."""


def _seconds(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    value = float(raw)
    if not 0 <= value <= 3600:
        raise ValueError(f"{name} must be between 0 and 3600 seconds")
    return value


def agent_id(namespace: str, name: str) -> str:
    return f"{namespace}/{name}"


def _pairs(name: str) -> dict[str, str]:
    """``ns/name=value`` pairs separated by commas or newlines."""
    pairs: dict[str, str] = {}
    for item in re.split(r"[,\n]", os.environ.get(name, "")):
        item = item.strip()
        if not item:
            continue
        agent, sep, value = item.partition("=")
        namespace, slash, agent_name = agent.strip().partition("/")
        if (
            not sep
            or not slash
            or not LABEL.fullmatch(namespace)
            or not LABEL.fullmatch(agent_name)
        ):
            raise ValueError(f"{name}: entries are <namespace>/<name>=<value>")
        pairs[agent_id(namespace, agent_name)] = value.strip()
    return pairs


def bare_key(value: str) -> str | None:
    """The key in a Secret value: ``Bearer sdg_...`` (what kagent sends as is) or the key."""
    value = value.strip()
    if value.lower().startswith("bearer "):
        value = value[7:].strip()
    return value if KEY.fullmatch(value) else None


@dataclass(frozen=True)
class Settings:
    mcp_url: str | None
    """Soundings' MCP endpoint (like kagent's ``RemoteMCPServer.spec.url``). Never taken
    from a message: Soundings' messages carry no URL."""
    keys: dict[str, str] = field(default_factory=dict)
    keys_dir: Path | None = None
    behaviours: dict[str, str] = field(default_factory=dict)
    required_token: str | None = None
    """When set, every A2A request needs ``Authorization: Bearer <token>`` (kagent's
    ``trusted-proxy`` auth mode, which Soundings' ``SOUNDINGS_KAGENT_TOKEN`` answers)."""
    byo: tuple[str, str] | None = None
    """``FAKE_AGENT_BYO=<namespace>/<name>``: also serve that agent at ``/`` (A2A 0.3
    JSON-RPC and ``/.well-known/agent-card.json``), as kagent's controller expects of a
    ``type: BYO`` Agent's pod (port 8080 there: ``FAKE_AGENT_PORT=8080``)."""
    step_delay: float = 0.3
    slow_interval: float = 2.0
    late_delay: float = 3.0
    mcp_timeout: float = 30.0
    max_observations: int = 500

    @classmethod
    def from_env(cls) -> Settings:
        keys = {}
        for agent, value in _pairs("FAKE_AGENT_KEYS").items():
            key = bare_key(value)
            if key is None:
                raise ValueError(f"FAKE_AGENT_KEYS: the value for {agent} is not a Soundings key")
            keys[agent] = key
        behaviours = _pairs("FAKE_AGENT_BEHAVIOURS")
        for agent, behaviour in behaviours.items():
            if behaviour not in BEHAVIOURS:
                raise ValueError(f"FAKE_AGENT_BEHAVIOURS: unknown behaviour for {agent}")
        keys_dir = os.environ.get("FAKE_AGENT_KEYS_DIR", "").strip()
        mcp_url = os.environ.get("FAKE_AGENT_MCP_URL", "").strip() or None
        if mcp_url and not re.fullmatch(r"https?://[^\s/?#@]+(/[^\s?#]*)?", mcp_url):
            raise ValueError("FAKE_AGENT_MCP_URL must be an http(s) URL without credentials")
        byo = None
        byo_agent = os.environ.get("FAKE_AGENT_BYO", "").strip()
        if byo_agent:
            namespace, _, name = byo_agent.partition("/")
            if not LABEL.fullmatch(namespace) or not LABEL.fullmatch(name):
                raise ValueError("FAKE_AGENT_BYO must be <namespace>/<name>")
            byo = (namespace, name)
        return cls(
            mcp_url=mcp_url,
            byo=byo,
            keys=keys,
            keys_dir=Path(keys_dir) if keys_dir else None,
            behaviours=behaviours,
            required_token=os.environ.get("FAKE_AGENT_REQUIRE_TOKEN", "").strip() or None,
            step_delay=_seconds("FAKE_AGENT_STEP_DELAY", 0.3),
            slow_interval=_seconds("FAKE_AGENT_SLOW_INTERVAL", 2.0),
            late_delay=_seconds("FAKE_AGENT_LATE_DELAY", 3.0),
            mcp_timeout=_seconds("FAKE_AGENT_MCP_TIMEOUT", 30.0),
        )

    def key_for(self, namespace: str, name: str) -> str | None:
        """The agent's key: ``FAKE_AGENT_KEYS``, else the file ``<namespace>.<name>`` in
        ``FAKE_AGENT_KEYS_DIR`` (a Kubernetes Secret key may hold dots, labels may not).
        An agent without a key isn't served (404), like an Agent that doesn't exist."""
        agent = agent_id(namespace, name)
        if agent in self.keys:
            return self.keys[agent]
        if self.keys_dir is None:
            return None
        path = self.keys_dir / f"{namespace}.{name}"
        try:
            return bare_key(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, NotADirectoryError, IsADirectoryError, PermissionError):
            return None

    def behaviour_for(self, namespace: str, name: str) -> str:
        explicit = self.behaviours.get(agent_id(namespace, name))
        if explicit:
            return explicit
        for behaviour in sorted(BEHAVIOURS, key=len, reverse=True):
            if behaviour != "normal" and name.endswith("-" + behaviour):
                return behaviour
        return "normal"
