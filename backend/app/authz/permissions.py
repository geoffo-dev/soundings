"""``permissions`` objects in responses, computed by the same policy the API enforces.

The UI uses them to show or hide controls (contract section 1, "Permissions"); they
are never security. Every idea-write flag is false in an archived project, because
those rules carry the archived-project condition.
"""

from __future__ import annotations

from uuid import UUID

from app.authz.policy import Resource, can
from app.authz.rules import Rule
from app.domain.principal import Principal
from app.schemas.ideas import IdeaPermissions, IdeaSummaryPermissions
from app.schemas.projects import ProjectPermissions

__all__ = ["idea_permissions", "idea_summary_permissions", "project_permissions"]

_SOMEONE_ELSE = UUID(int=0)
"""A user id nobody has: evaluates the remove variant of ``evaluator.manage`` for
"another evaluator" (c16 passes) when building flags."""


def project_permissions(principal: Principal | None, resource: Resource) -> ProjectPermissions:
    return ProjectPermissions(
        can_manage=can(principal, Rule.PROJECT_EDIT_SETTINGS, resource),
        can_create_ideas=can(principal, Rule.IDEA_CREATE, resource),
    )


def idea_summary_permissions(
    principal: Principal | None, resource: Resource
) -> IdeaSummaryPermissions:
    return IdeaSummaryPermissions(
        can_change_status=can(principal, Rule.IDEA_CHANGE_STATUS, resource),
    )


def idea_permissions(principal: Principal | None, resource: Resource) -> IdeaPermissions:
    """The idea page's flags. ``resource`` must have the idea's facts."""
    idea = resource.idea
    if idea is None:
        raise ValueError("idea permissions need the idea's facts")
    is_owner = principal is not None and idea.owner_id == principal.user_id
    removing_someone_else = resource.replace(evaluator_to_remove=_SOMEONE_ELSE)
    return IdeaPermissions(
        can_change_status=can(principal, Rule.IDEA_CHANGE_STATUS, resource),
        can_edit=can(principal, Rule.IDEA_EDIT_OWN, resource)
        or can(principal, Rule.IDEA_EDIT_ANY, resource),
        can_assign_owner=can(principal, Rule.IDEA_ASSIGN_OWNER, resource),
        # "Step down" is for the owner; admins clear the owner with assign.
        can_release_owner=is_owner and can(principal, Rule.IDEA_RELEASE_OWNER, resource),
        can_volunteer=can(principal, Rule.IDEA_VOLUNTEER_OWNER, resource),
        can_invite_evaluators=can(principal, Rule.EVALUATOR_MANAGE, resource),
        can_remove_evaluators=can(principal, Rule.EVALUATOR_MANAGE, removing_someone_else),
        can_evaluate=can(principal, Rule.EVALUATION_SUBMIT_OWN, resource),
        can_close_evaluation=can(principal, Rule.EVALUATION_CLOSE, resource),
        can_comment=can(principal, Rule.COMMENT_CREATE, resource),
        can_vote=can(principal, Rule.IDEA_VOTE, resource),
        can_delete=can(principal, Rule.IDEA_DELETE, resource),
    )
