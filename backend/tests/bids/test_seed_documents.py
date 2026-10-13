"""The demo seed's bid documents are the ones :mod:`tests.bids.seed_documents` builds, each
a few KB, of a type the upload accepts, with text the extraction child finds; the price is
only in the pricing schedules (pricing documents)."""

from __future__ import annotations

import re

from app.bids.extract_child import Limits, extract
from app.bids.extraction import CHILD_LIMITS
from app.bids.sniff import sniff
from tests.bids.seed_documents import DOCUMENTS, SEED_DIR


def test_the_committed_documents_are_current() -> None:
    committed = {path.name: path.read_bytes() for path in SEED_DIR.iterdir() if path.is_file()}
    assert committed == dict(DOCUMENTS), "run: uv run python -m tests.bids.seed_documents"


def test_they_are_small_pdf_and_word_files() -> None:
    kinds = {sniff(data, name).value for name, data in DOCUMENTS.items()}
    assert kinds == {"pdf", "docx"}
    assert all(len(data) < 4096 for data in DOCUMENTS.values())


def test_only_the_pricing_schedules_carry_prices() -> None:
    """Role matrix 3a: prices only for call managers and the price section's assessors, so a
    supplier's amounts appear in its pricing schedule (a pricing document) and nowhere the
    other assessors or the AI read (a form of tender once said "96,000 GBP")."""
    limits = Limits(**CHILD_LIMITS)
    texts = {
        name: extract(sniff(data, name).value, data, limits).text
        for name, data in DOCUMENTS.items()
    }
    for name, text in texts.items():
        if not name.endswith("-pricing-schedule.pdf"):
            continue
        supplier = name.removesuffix("-pricing-schedule.pdf")
        amounts = set(re.findall(r"[\d,]+ GBP", text))
        assert amounts, name
        for other, other_text in texts.items():
            if other.startswith(f"{supplier}-") and other != name:
                assert not amounts & set(re.findall(r"[\d,]+ GBP", other_text)), other
