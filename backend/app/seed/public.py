"""Phase 4 demo content: branding, Customer Innovation's public form and a few ideas
sent through it (contract-phase4 sections 3.5-3.11).

* The **global** branding keeps the Soundings name, colours and font and adds an email
  footer, so the shell looks as before and every email shows the footer.
* **Customer Innovation** overrides the colours and font and has its own logo and
  favicon (SVGs that pass the upload allow-list): its public form, tracking pages,
  emails to public submitters and exported proposals show them.
* Its **public form** is on and moderated, with an intro. Three ideas came in through
  it in the last few hours (after every other demo idea, so the demo keys stay the
  same): one approved by the project admin (its submitter gave a confirmed address and
  asked for updates), two waiting in the moderation queue (one anonymous). They have no
  tracking link (nobody could know its token); send the form to get a real one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

__all__ = [
    "CUST_BRANDING",
    "CUST_FAVICON",
    "CUST_LOGO",
    "GLOBAL_FOOTER",
    "PUBLIC_FORM_INTRO",
    "PUBLIC_IDEAS",
    "PUBLIC_PROJECT",
    "PublicIdeaSeed",
]

PUBLIC_PROJECT: Final = "CUST"

GLOBAL_FOOTER: Final = "Soundings demo · Example Retail Ltd\n1 Example Street, London EC1A 1AA"

CUST_BRANDING: Final = {
    "primary_color": "#0b6e4f",
    "accent_color": "#c2410c",
    "font": "ibm_plex_sans",
    "email_footer": "Customer Innovation · Example Retail Ltd\n1 Example Street, London EC1A 1AA",
}
"""The project's override; the app name stays the global one."""

CUST_LOGO: Final = b"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="220" height="40" viewBox="0 0 220 40">
<title>Customer Innovation</title>
<defs>
<linearGradient id="tile" x1="0" y1="0" x2="1" y2="1">
<stop offset="0" stop-color="#0b6e4f"/>
<stop offset="1" stop-color="#14a37f"/>
</linearGradient>
</defs>
<rect width="40" height="40" rx="9" fill="url(#tile)"/>
<path d="M8 25c4-6 8-6 12 0s8 6 12 0" fill="none" stroke="#ffffff" stroke-width="3"
      stroke-linecap="round"/>
<circle cx="20" cy="13" r="3.5" fill="#fbbf24"/>
<text x="50" y="26" font-family="'IBM Plex Sans', Arial, sans-serif" font-size="15"
      font-weight="600" fill="#0b2e24">Customer Innovation</text>
</svg>
"""
"""A wordmark logo: a green tile with a wave and a sun, and the project's name."""

CUST_FAVICON: Final = b"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 40 40">
<rect width="40" height="40" rx="9" fill="#0b6e4f"/>
<path d="M8 25c4-6 8-6 12 0s8 6 12 0" fill="none" stroke="#ffffff" stroke-width="3.5"
      stroke-linecap="round"/>
<circle cx="20" cy="13" r="4" fill="#fbbf24"/>
</svg>
"""

PUBLIC_FORM_INTRO: Final = (
    # The form itself says you get a private link (UX review P7 p3: not twice).
    "Got an idea that would make shopping with us better? Tell the Customer Innovation "
    "team: we read every idea."
)


@dataclass(frozen=True, slots=True)
class PublicIdeaSeed:
    title: str
    summary: str
    description: str
    hours_ago: float
    name: str | None = None
    email: str | None = None
    confirmed: bool = False
    wants_updates: bool = False
    approved_after: float | None = None
    """Hours after it came in that the project admin approved it; ``None``: waiting."""


PUBLIC_IDEAS: Final = (
    PublicIdeaSeed(
        title="Reusable delivery boxes with a deposit",
        summary=(
            "Deliver in sturdy boxes customers hand back to the next driver, with a small "
            "deposit refunded to their account."
        ),
        description=(
            "Every order arrives in a new cardboard box, and most of them are bigger than "
            "they need to be.\n\nA deposit of £2 per box, refunded when the driver collects "
            "it on the next delivery, would cut packaging and look good on the van."
        ),
        hours_ago=6,
        name="Sam Okafor",
        email="sam.okafor@example.org",
        confirmed=True,
        wants_updates=True,
        approved_after=1.0,
    ),
    PublicIdeaSeed(
        title="Repair café in the flagship store",
        summary=(
            "Once a month, volunteers help customers fix small appliances and clothes they "
            "bought from us."
        ),
        description="Other shops do this and it brings people in on quiet Saturdays.",
        hours_ago=3,
    ),
    PublicIdeaSeed(
        title="Braille labels on own-brand products",
        summary="Add Braille to the labels of our own-brand groceries, starting with tins.",
        description=(
            "My dad is blind and can't tell our tins apart. Some supermarkets already do "
            "this for their own brands."
        ),
        hours_ago=1.5,
        name="Robin",
    ),
)
