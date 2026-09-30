"""Soundings backend: a FastAPI app for submitting, owning and evaluating ideas."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("soundings")
except PackageNotFoundError:  # pragma: no cover - only when running from a bare checkout
    __version__ = "0.0.0"
