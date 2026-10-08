"""The proposal template every new project starts with (SPEC section 2; Phase 8: a
starting point that project admins edit, contract-phase8 section 2).

The sections are :data:`app.schemas.proposals.DEFAULT_PROPOSAL_TEMPLATE` (the built-in
eight, keys ``summary`` ... ``next_steps``); migration 0012 gave the same rows to every
project that existed before Phase 8.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from app.models.proposal import ProposalTemplateSection
from app.schemas.proposals import DEFAULT_PROPOSAL_TEMPLATE

__all__ = ["default_template_sections"]


def default_template_sections(project_id: UUID) -> list[ProposalTemplateSection]:
    """New rows for a project's default template (positions 0-7)."""
    return [
        ProposalTemplateSection(
            id=uuid4(),
            project_id=project_id,
            key=str(section.key),
            title=section.title,
            hint=section.prompt,
            position=position,
        )
        for position, section in enumerate(DEFAULT_PROPOSAL_TEMPLATE)
    ]
