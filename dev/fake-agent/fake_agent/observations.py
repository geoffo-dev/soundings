"""What the fake agent saw and did, per run, for tests (``GET /_fake/observations``):
the A2A requests (methods, headers that matter, ``historyLength``, cancels), the MCP
tools it called with their error codes, and what rule 9 and c22 showed it. Never keys,
tokens, message text or tool results beyond codes and flags."""

from __future__ import annotations

import re
import threading
from collections import OrderedDict
from datetime import UTC, datetime
from typing import Any

_URL = re.compile(r"https?://", re.IGNORECASE)
_KEY = re.compile(r"sdg_[A-Za-z0-9_]{8,}")


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def message_checks(text: str, metadata: dict[str, Any]) -> dict[str, bool]:
    """What Soundings' run message must never carry (contract-phase6 section 1)."""
    flat = text + " " + repr(metadata)
    return {"has_url": bool(_URL.search(flat)), "has_api_key": bool(_KEY.search(flat))}


class Observations:
    """Thread-safe, bounded (oldest runs dropped first)."""

    def __init__(self, limit: int = 500) -> None:
        self._limit = limit
        self._runs: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._tasks: dict[str, str] = {}
        self._lock = threading.Lock()

    def _run(self, run_id: str) -> dict[str, Any]:
        run = self._runs.get(run_id)
        if run is None:
            run = {
                "run_id": run_id,
                "first_seen_at": now(),
                "a2a_requests": [],
                "tool_calls": [],
                "blind": [],
                "strays": {},
                "late": None,
                "cancel_requests": 0,
                "final_state": None,
            }
            self._runs[run_id] = run
            while len(self._runs) > self._limit:
                old_id, _ = self._runs.popitem(last=False)
                for task, owner in list(self._tasks.items()):
                    if owner == old_id:
                        del self._tasks[task]
        return run

    def start(self, run_id: str, **fields: Any) -> None:
        with self._lock:
            self._run(run_id).update(fields)

    def link_task(self, run_id: str, task_id: str, context_id: str | None) -> None:
        with self._lock:
            self._tasks[task_id] = run_id
            self._run(run_id).update(task_id=task_id, context_id=context_id)

    def run_for_task(self, task_id: str) -> str | None:
        with self._lock:
            return self._tasks.get(task_id)

    def a2a_request(self, run_id: str | None, entry: dict[str, Any]) -> None:
        with self._lock:
            target = self._run(run_id) if run_id else self._run("_unmatched")
            target["a2a_requests"].append({"at": now(), **entry})
            if entry.get("method") in ("tasks/cancel", "CancelTask"):
                target["cancel_requests"] += 1

    def tool_call(self, run_id: str, tool: str, error_code: str | None, phase: str) -> None:
        with self._lock:
            self._run(run_id)["tool_calls"].append(
                {"at": now(), "tool": tool, "error_code": error_code, "phase": phase}
            )

    def blind(self, run_id: str, entry: dict[str, Any]) -> None:
        with self._lock:
            self._run(run_id)["blind"].append({"at": now(), **entry})

    def stray(self, run_id: str, attempt: str, error_code: str | None) -> None:
        with self._lock:
            self._run(run_id)["strays"][attempt] = error_code

    def late(self, run_id: str, tool: str, error_code: str | None) -> None:
        with self._lock:
            self._run(run_id)["late"] = {"at": now(), "tool": tool, "error_code": error_code}

    def finish(self, run_id: str, state: str) -> None:
        with self._lock:
            run = self._run(run_id)
            run["final_state"] = state
            run["finished_at"] = now()

    def get(self, run_id: str) -> dict[str, Any] | None:
        with self._lock:
            run = self._runs.get(run_id)
            return _copy(run) if run is not None else None

    def all(self) -> list[dict[str, Any]]:
        with self._lock:
            return [_copy(run) for run in self._runs.values()]

    def clear(self) -> None:
        with self._lock:
            self._runs.clear()
            self._tasks.clear()


def _copy(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _copy(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_copy(item) for item in value]
    return value
