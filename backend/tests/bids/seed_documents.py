"""The demo seed's bid documents (``app/seed/bids/``, contract-phase10 section 17): small
PDF and Word files from three fictional suppliers, built with the test builders
(:mod:`tests.bids.files`) so they are deterministic. ``test_seed_documents.py`` checks
the committed files equal what this builds; to change one, edit it here and run::

    uv run python -m tests.bids.seed_documents

Every supplier, person and number in them is invented.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Final

from tests.bids.files import docx, pdf

__all__ = ["DOCUMENTS", "SEED_DIR", "build", "write"]

SEED_DIR: Final = Path(__file__).resolve().parents[2] / "app" / "seed" / "bids"


def _tender(supplier: str, signatory: str, total: str, start: str) -> bytes:
    return pdf(
        "FORM OF TENDER",
        "Call for bids: Data platform build (Internal Tools, TOOLS-3)",
        "",
        f"Bidder: {supplier}",
        "",
        "We offer to design, build and hand over the self-service test data generator",
        "described in the invitation to tender, for the total price set out in our",
        f"pricing schedule ({total}, fixed for the contract term).",
        "",
        "We accept the buyer's standard terms and conditions without amendment.",
        f"We can start on {start} and will hold this offer open for 90 days.",
        "",
        f"Signed: {signatory}, for and on behalf of {supplier}",
        "Date: 1 October 2026",
    )


def _pricing(supplier: str, rows: tuple[tuple[str, str], ...], total: str) -> bytes:
    return pdf(
        "PRICING SCHEDULE",
        f"Bidder: {supplier}",
        "Call for bids: Data platform build",
        "",
        *(f"{item}: {price}" for item, price in rows),
        "",
        f"Total for the contract term: {total} (excluding VAT)",
        "Prices are fixed for 36 months. No other charges apply.",
    )


def _insurance(supplier: str, insurer: str, cover: str) -> bytes:
    return pdf(
        "CERTIFICATE OF INSURANCE",
        f"Insured: {supplier}",
        f"Insurer: {insurer}",
        "",
        f"Professional indemnity: {cover} any one claim",
        "Public liability: 5,000,000 GBP any one event",
        "Employer's liability: 10,000,000 GBP",
        "",
        "Period of insurance: 1 April 2026 to 31 March 2027",
        "This certificate confirms that the policies above are in force.",
    )


DOCUMENTS: Final[Mapping[str, bytes]] = {
    # --- Northwind Data Ltd: complete and strong ----------------------------------------
    "northwind-form-of-tender.pdf": _tender(
        "Northwind Data Ltd", "Hannah Wright, Managing Director", "120,000 GBP", "2 November 2026"
    ),
    "northwind-pricing-schedule.pdf": _pricing(
        "Northwind Data Ltd",
        (
            ("Discovery and design (3 weeks)", "18,000 GBP"),
            ("Build and integration (10 weeks)", "72,000 GBP"),
            ("Hand-over, training and 3 months' support", "30,000 GBP"),
        ),
        "120,000 GBP",
    ),
    "northwind-insurance-certificate.pdf": _insurance(
        "Northwind Data Ltd", "Harbourside Mutual Insurance", "5,000,000 GBP"
    ),
    "northwind-technical-proposal.docx": docx(
        "Technical proposal: Northwind Data Ltd",
        "Our approach builds the generator as a small service in your developer portal. "
        "Every scenario is a version-controlled recipe that produces realistic, anonymised "
        "customers, orders and payment methods in staging within a minute.",
        "Data never leaves your environment: the generator runs in your cluster, holds no "
        "production data and is covered by our ISO 27001 certification.",
        "Requirements coverage: we meet all 14 requirements in the specification and attach "
        "a traceability matrix. A working prototype is available for a demo.",
        "Delivery plan: discovery and design in weeks 1-3, build in weeks 4-13, hand-over "
        "and training in week 14. We need a named product owner for two hours a week.",
        "Team: a lead engineer and two developers who built a similar generator for a "
        "national retailer in 2025; references available on request.",
    ),
    # --- Tessellate Software: complete, cheaper, weaker technically ---------------------
    "tessellate-form-of-tender.pdf": _tender(
        "Tessellate Software", "Ravi Mehta, Director", "96,000 GBP", "16 November 2026"
    ),
    "tessellate-pricing-schedule.pdf": _pricing(
        "Tessellate Software",
        (
            ("Configuration of our TestForge product", "36,000 GBP"),
            ("Licences for 36 months", "45,000 GBP"),
            ("Training and support", "15,000 GBP"),
        ),
        "96,000 GBP",
    ),
    "tessellate-insurance-certificate.pdf": _insurance(
        "Tessellate Software", "Calder Bay Insurance", "2,000,000 GBP"
    ),
    "tessellate-technical-proposal.docx": docx(
        "Technical proposal: Tessellate Software",
        "We propose our TestForge product, configured for your systems. TestForge generates "
        "synthetic customer and order records from templates that your teams can edit.",
        "TestForge is a hosted service: generated data is stored in our cloud region in "
        "Ireland. Single sign-on is on our roadmap for next year.",
        "Requirements coverage: TestForge meets 11 of the 14 requirements out of the box; "
        "payment methods and invoices would need custom templates, priced separately.",
        "Delivery plan: configuration in weeks 1-4 and a pilot with one team in week 5.",
        "Team: a solution consultant and our standard support desk.",
    ),
    # --- Quillfield Systems: no insurance certificate ----------------------------------
    "quillfield-form-of-tender.pdf": _tender(
        "Quillfield Systems", "Owen Price, Partner", "84,000 GBP", "9 November 2026"
    ),
    "quillfield-pricing-schedule.pdf": _pricing(
        "Quillfield Systems",
        (
            ("Build (8 weeks)", "64,000 GBP"),
            ("Support for 12 months", "20,000 GBP"),
        ),
        "84,000 GBP",
    ),
    "quillfield-technical-proposal.docx": docx(
        "Technical proposal: Quillfield Systems",
        "We will build a command-line tool that copies a sample of production data and "
        "masks names and email addresses before loading it into staging.",
        "Delivery plan: eight weeks from the start date, with weekly demos.",
    ),
}
"""File name -> bytes. Each supplier's pricing schedule is a pricing document (only call
managers and the Commercial assessors open it); Quillfield has no insurance certificate."""


def build() -> dict[str, bytes]:
    return dict(DOCUMENTS)


def write(directory: Path = SEED_DIR) -> list[Path]:
    """Write every document to ``directory`` (the committed copies)."""
    directory.mkdir(parents=True, exist_ok=True)
    written = []
    for name, data in DOCUMENTS.items():
        path = directory / name
        path.write_bytes(data)
        written.append(path)
    return written


if __name__ == "__main__":  # pragma: no cover - a maintenance command
    for path in write():
        print(path.name, path.stat().st_size)  # noqa: T201 - a maintenance command
