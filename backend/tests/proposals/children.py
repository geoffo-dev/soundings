"""Stand-in PDF child processes for the renderer tests (imported by ``spawn`` in the
child, so they live in a module, not in a test function)."""

from __future__ import annotations

import os
import time
from multiprocessing.connection import Connection


def sleep_forever(connection: Connection) -> None:
    """A render that never finishes (the parent must kill it)."""
    while True:
        connection.recv()
        time.sleep(3600)


def crash(connection: Connection) -> None:
    """A render that takes the process down."""
    connection.recv()
    os._exit(3)


def answer_error(connection: Connection) -> None:
    while True:
        connection.recv()
        connection.send(("error", "ValueError"))


def never_read(connection: Connection) -> None:
    """A child that stops reading: sending it a large document blocks."""
    time.sleep(3600)
