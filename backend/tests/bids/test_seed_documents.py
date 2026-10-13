"""The demo seed's bid documents are the ones :mod:`tests.bids.seed_documents` builds, each
a few KB, of a type the upload accepts, with text the extraction child finds."""

from __future__ import annotations

from app.bids.sniff import sniff
from tests.bids.seed_documents import DOCUMENTS, SEED_DIR


def test_the_committed_documents_are_current() -> None:
    committed = {path.name: path.read_bytes() for path in SEED_DIR.iterdir() if path.is_file()}
    assert committed == dict(DOCUMENTS), "run: uv run python -m tests.bids.seed_documents"


def test_they_are_small_pdf_and_word_files() -> None:
    kinds = {sniff(data, name).value for name, data in DOCUMENTS.items()}
    assert kinds == {"pdf", "docx"}
    assert all(len(data) < 4096 for data in DOCUMENTS.values())
