"""PDF rendering in a separate process with a hard time limit (contract-phase4 3.4,
ADR 0011).

WeasyPrint is CPU-bound and holds the GIL (a render in a thread pauses the event loop
for hundreds of milliseconds), and some inputs are slow. So a render never runs in the
API process: an :class:`ExportDocument` goes to a child process (``multiprocessing``
**spawn** context, never ``fork`` from the threaded API process), which builds the
HTML (Markdown included) and returns the PDF bytes.

* **One render at a time per API process:** an asyncio semaphore on the app (waiting
  costs no thread) and the renderer's own lock. Waiting more than
  :data:`SLOT_TIMEOUT` seconds -> :class:`ExportBusy` (503 ``export_busy``).
* **A hard limit:** a render gets :data:`RENDER_TIMEOUT` seconds of wall-clock time,
  child start-up included; then the child is killed (``SIGKILL``) -> ``ExportBusy``.
  The next export starts a fresh child.
* **A warm child:** the child serves renders one after another and exits by itself
  after :data:`IDLE_EXIT` seconds without work (or when the API process goes away),
  so most exports skip the second of interpreter and WeasyPrint start-up and an idle
  API process holds no renderer memory.
* **Its own temporary folder:** each child writes temporary files (WeasyPrint's font
  folder, about 700 KB) in a folder the parent made for it and deletes once the child
  is gone, so a killed render leaves nothing behind in ``/tmp``.

The parent imports nothing heavy: ``weasyprint`` is imported only in the child
(:mod:`app.proposals.pdf_child`), so the API starts where Pango is missing.
"""

from __future__ import annotations

import asyncio
import atexit
import logging
import multiprocessing
import os
import shutil
import tempfile
import threading
import time
from collections.abc import Callable
from multiprocessing.connection import Connection
from multiprocessing.process import BaseProcess
from typing import Any, Final

from app.proposals.document import ExportDocument

__all__ = [
    "IDLE_EXIT",
    "RENDER_TIMEOUT",
    "RETRY_AFTER",
    "SLOT_TIMEOUT",
    "ExportBusy",
    "RenderFailed",
    "Renderer",
    "render_pdf",
    "renderer",
]

logger = logging.getLogger(__name__)

RENDER_TIMEOUT: Final = 20.0
"""Seconds a render may take before its process is killed."""
SLOT_TIMEOUT: Final = 30.0
"""Seconds a request may wait for the renderer."""
RETRY_AFTER: Final = 10
"""``Retry-After`` of a 503 ``export_busy``."""
IDLE_EXIT: Final = 300.0
"""Seconds the child waits for another render before it exits."""


class ExportBusy(Exception):
    """The renderer stayed busy (``reason="busy"``) or a render ran out of time and was
    killed (``reason="timeout"``)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class RenderFailed(Exception):
    """The render raised or its process died (never carries document content)."""


def _serve(connection: Connection) -> None:
    """The child's entry point; imports the renderer (and WeasyPrint) in the child."""
    from app.proposals.pdf_child import serve

    serve(connection)


def _child_main(target: Callable[[Connection], None], connection: Connection, scratch: str) -> None:
    """Runs in the child: its temporary files go to ``scratch`` (deleted by the parent)."""
    tempfile.tempdir = scratch
    os.environ["TMPDIR"] = scratch
    target(connection)


class Renderer:
    """A child process that renders one document at a time. Blocking: call
    :meth:`render` from a worker thread (:func:`render_pdf` does)."""

    def __init__(self, target: Callable[[Connection], None] = _serve) -> None:
        self._target = target
        self._lock = threading.Lock()
        self._process: BaseProcess | None = None
        self._connection: Connection | None = None
        self._scratch: str | None = None

    @property
    def pid(self) -> int | None:
        return self._process.pid if self._process is not None else None

    def _start(self) -> Connection:
        context = multiprocessing.get_context("spawn")
        scratch = tempfile.mkdtemp(prefix="soundings-pdf-")
        ours, theirs = context.Pipe(duplex=True)
        process = context.Process(
            target=_child_main,
            args=(self._target, theirs, scratch),
            name="soundings-pdf",
            daemon=True,
        )
        self._scratch = scratch
        try:
            process.start()
        except BaseException:
            ours.close()
            shutil.rmtree(scratch, ignore_errors=True)
            self._scratch = None
            raise
        finally:
            theirs.close()
        self._process, self._connection = process, ours
        return ours

    @property
    def scratch(self) -> str | None:
        """The current child's temporary folder (None without a child)."""
        return self._scratch

    def _ensure(self) -> tuple[Connection, bool]:
        """The child's pipe, and whether the child is new."""
        if self._process is not None and self._connection is not None and self._process.is_alive():
            return self._connection, False
        self.stop()
        return self._start(), True

    def stop(self) -> None:
        """Kill the child (if any), delete its temporary folder and forget it."""
        process, connection, scratch = self._process, self._connection, self._scratch
        self._process = self._connection = self._scratch = None
        if connection is not None:
            connection.close()
        if process is not None:
            if process.is_alive():
                process.kill()
            process.join(timeout=5)
            if process.exitcode is not None:
                process.close()
        if scratch is not None:
            shutil.rmtree(scratch, ignore_errors=True)

    def render(self, document: Any, *, timeout: float, wait: float) -> bytes:
        """The child's PDF for ``document``, within ``timeout`` seconds in all (sending
        the document and a fresh child's start-up included), after waiting at most
        ``wait`` seconds for a render in progress."""
        if not self._lock.acquire(timeout=wait):
            raise ExportBusy("busy")
        try:
            deadline = time.monotonic() + timeout
            for attempt in (1, 2):
                connection, fresh = self._ensure()
                process = self._process
                # Bounds every blocking step below: a send to a child that stopped
                # reading, the wait for the reply, a reply cut off half-way.
                watchdog = threading.Timer(max(deadline - time.monotonic(), 0.0), _kill, (process,))
                watchdog.daemon = True
                watchdog.start()
                try:
                    connection.send(document)
                    remaining = deadline - time.monotonic()
                    if remaining <= 0 or not connection.poll(remaining):
                        self.stop()
                        raise ExportBusy("timeout")
                    status, payload = connection.recv()
                except (EOFError, OSError):
                    self.stop()
                    if time.monotonic() >= deadline:
                        raise ExportBusy("timeout") from None
                    # The child died. A reused one may just have exited while idle: try
                    # once more with a fresh one; a fresh one that dies has crashed.
                    if fresh or attempt == 2:
                        raise RenderFailed("the PDF renderer exited") from None
                    continue
                finally:
                    watchdog.cancel()
                if status == "ok" and isinstance(payload, bytes):
                    return payload
                raise RenderFailed(str(payload))
            raise RenderFailed("the PDF renderer exited")  # pragma: no cover
        finally:
            self._lock.release()


def _kill(process: BaseProcess | None) -> None:
    """The watchdog: SIGKILL the child (if it is still running)."""
    try:
        if process is not None and process.is_alive():
            process.kill()
    except ValueError:  # already closed by stop()
        pass


_renderer: Renderer | None = None
_renderer_lock = threading.Lock()


def renderer() -> Renderer:
    """This process's renderer (created on first use)."""
    global _renderer  # noqa: PLW0603 - one renderer per process
    with _renderer_lock:
        if _renderer is None:
            _renderer = Renderer()
            atexit.register(_renderer.stop)  # its temporary folder goes with the process
        return _renderer


def _slot(state: Any) -> asyncio.Semaphore:
    slot: asyncio.Semaphore | None = getattr(state, "pdf_render_slot", None)
    if slot is None:
        slot = asyncio.Semaphore(1)
        state.pdf_render_slot = slot
    return slot


async def render_pdf(state: Any, document: ExportDocument) -> bytes:
    """The PDF for ``document``; ``state`` is the app's state (holds the wait slot).

    Raises :class:`ExportBusy` (waited :data:`SLOT_TIMEOUT` s, or the render took more
    than :data:`RENDER_TIMEOUT` s and was killed) or :class:`RenderFailed`."""
    slot = _slot(state)
    try:
        await asyncio.wait_for(slot.acquire(), SLOT_TIMEOUT)
    except TimeoutError:
        raise ExportBusy("busy") from None
    try:
        return await asyncio.to_thread(
            renderer().render, document, timeout=RENDER_TIMEOUT, wait=SLOT_TIMEOUT
        )
    finally:
        slot.release()
