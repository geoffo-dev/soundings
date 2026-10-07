"""What an API key may reach, route by route (role matrix section 5; contract-phase5
sections 2 and 3.3).

Rules carry their scope (:data:`app.authz.rules.RULE_SCOPES`) and the policy narrows
every decision by it. Some routes have no rule of their own, and some only ever run
session-only rules; :data:`ROUTE_KEY_ACCESS` classifies **every** API operation so a key
is refused before such a route runs:

* ``policy``: the route's rules decide (the policy checks the key's scopes and
  projects, after the 404s).
* ``read``: no rule of its own (``get_me``, My work, owned ideas, global search): the
  key needs the ``read`` scope.
* ``session``: never through a key (every rule it runs is session only, or it is a
  person's reading state, like the inbox): 403 ``insufficient_scope``.
* ``public``: no principal at all (sign-in, unsubscribe links, the public form,
  branding reads): keys are never read there.

:func:`check_route_for_key` runs in :func:`app.api.deps.get_current_user` for every
key-authenticated request. **Deny by default:** an operation missing from the table is
refused to keys (``tests/authz/test_key_routes.py`` keeps the table complete). A refusal
here comes before the route's own checks (the 404s and the body's 422), which reveals
nothing: it doesn't depend on the resource.

:func:`require_session` and :func:`require_key_scope` are the same checks for code that
isn't a route (and for routes that want to say it explicitly).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

from app.domain.principal import ApiKeyScope, Principal
from app.errors import ProblemError

__all__ = [
    "ROUTE_KEY_ACCESS",
    "InsufficientScopeProblem",
    "KeyAccess",
    "check_route_for_key",
    "require_key_scope",
    "require_session",
]


class KeyAccess(StrEnum):
    POLICY = "policy"
    READ = "read"
    SESSION = "session"
    PUBLIC = "public"


class InsufficientScopeProblem(ProblemError):
    """403 ``insufficient_scope``: the key's scopes don't allow it, or it needs a session."""

    def __init__(self) -> None:
        super().__init__(
            403, "insufficient_scope", detail="This API key's scopes don't allow that."
        )


_P, _R, _S, _U = KeyAccess.POLICY, KeyAccess.READ, KeyAccess.SESSION, KeyAccess.PUBLIC

# fmt: off
ROUTE_KEY_ACCESS: Final[dict[str, KeyAccess]] = {
    # Phase 1: signed in, projects, ideas, evaluations, collaboration, My work, search
    "get_me": _R,
    "list_dev_users": _U, "dev_login": _U, "logout": _U,
    "search_users": _P,
    "list_projects": _P, "get_project": _P, "list_project_members": _P,
    "list_project_tags": _P,
    "create_project": _S,                                   # project.create
    "update_project": _S,                                   # project.edit_settings, rename labels
    "add_project_member": _S, "update_project_member": _S,  # project.manage_members
    "remove_project_member": _S,
    "replace_rubric": _S,                                   # project.edit_rubric
    "list_ideas": _P, "get_board": _P, "create_idea": _P,
    "get_idea": _P, "update_idea": _P,
    "delete_idea": _S,                                      # idea.delete: a hard cascade
    "change_idea_status": _P, "set_idea_owner": _P, "volunteer_as_owner": _P,
    "add_evaluators": _P, "remove_evaluator": _P, "set_evaluation_due_date": _P,
    "close_evaluation": _P, "reopen_evaluation": _P,
    "list_evaluations": _P, "get_my_evaluation": _P, "save_my_evaluation": _P,
    "vote_idea": _P, "unvote_idea": _P, "watch_idea": _P, "unwatch_idea": _P,
    "list_idea_activity": _P,
    "create_comment": _P, "update_comment": _P, "delete_comment": _P,
    "get_my_work": _R, "list_my_owned_ideas": _R, "global_search": _R,
    # Phase 2: sign-in, administration, groups and project access
    "get_auth_config": _U, "sso_login": _U, "sso_callback": _U,
    "break_glass_login": _U, "logout_redirect": _U,
    "list_admin_users": _S, "create_admin_user": _S, "get_admin_user": _S,
    "update_admin_user": _S, "replace_user_external_ids": _S,
    "unlink_user_identity": _S, "end_user_sessions": _S,
    "list_admin_groups": _S, "create_group": _S, "test_group_mapping": _S,
    "get_group": _S, "update_group": _S, "delete_group": _S,
    "replace_group_mapping": _S, "list_group_members": _S,
    "add_group_member": _S, "remove_group_member": _S,
    "search_groups": _P,                                    # user.search
    "list_project_group_grants": _P, "list_project_access": _P,
    "add_project_group_grant": _S, "update_project_group_grant": _S,
    "remove_project_group_grant": _S,
    "list_audit_entries": _S, "get_sso_config": _S,
    # Phase 3: the inbox and the bell are a person's reading state; preferences
    "list_notifications": _S, "get_notification_summary": _S,
    "mark_notification_read": _S, "mark_all_notifications_read": _S,
    "get_notification_preferences": _S, "update_notification_preferences": _S,
    "get_unsubscribe": _U, "confirm_unsubscribe": _U,
    "get_email_config": _S, "send_test_email": _S, "list_outbox_emails": _S,
    "retry_failed_outbox_emails": _S, "get_outbox_email": _S, "retry_outbox_email": _S,
    # Phase 4: proposals, public submission, moderation, branding
    "get_proposal": _P, "create_proposal": _P, "update_proposal_section": _P,
    "export_proposal_markdown": _P, "export_proposal_pdf": _P,
    "list_proposal_threads": _P, "create_proposal_thread": _P,
    "reply_to_proposal_thread": _P, "resolve_proposal_thread": _P,
    "reopen_proposal_thread": _P, "delete_proposal_comment": _P,
    "get_public_project": _U, "get_altcha_challenge": _U, "submit_public_idea": _U,
    "track_submission": _U, "set_submission_updates": _U,
    "resend_verification_email": _U, "erase_tracked_submission": _U,
    "verify_submission_email": _U,
    "get_public_form_settings": _S, "update_public_form_settings": _S,
    "list_moderation_queue": _S,                            # idea.moderate
    "get_idea_submission": _S,                              # submitter details: moderate, erase
    "approve_submission": _S, "reject_submission": _S,      # idea.moderate
    "erase_submitter": _S,                                  # public.erase_submitter
    "get_branding": _U, "get_brand_asset": _U,
    "get_global_branding": _S, "update_global_branding": _S,
    "upload_global_brand_asset": _S,
    "get_project_branding": _S, "update_project_branding": _S,
    "upload_project_brand_asset": _S,
    # Phase 5: keys are managed in a session only; suggestions follow their rules
    "list_my_api_keys": _S, "create_my_api_key": _S, "revoke_my_api_key": _S,
    "list_admin_api_keys": _S, "revoke_admin_api_key": _S,
    "list_proposal_suggestions": _P, "create_proposal_suggestion": _P,
    "accept_proposal_suggestion": _P, "discard_proposal_suggestion": _P,
    # Phase 6: agents are managed in a session only (platform.manage_agents); AI runs,
    # their events, the include-AI toggle and research notes follow their rules
    "list_ai_agents": _S, "register_ai_agent": _S, "get_ai_agent": _S,
    "update_ai_agent": _S, "rotate_ai_agent_key": _S, "test_ai_agent": _S,
    "list_idea_ai_runs": _P, "request_ai_evaluation": _P, "request_ai_research": _P,
    "request_ai_section_draft": _P, "get_ai_run": _P, "cancel_ai_run": _P,
    "stream_ai_run_events": _P, "set_evaluation_inclusion": _P,
    "get_research_note": _P, "delete_research_note": _P,
    # Phase 7: My work's counts and its full list of evaluations due (like get_my_work)
    "get_my_work_counts": _R, "list_my_evaluations_due": _R,
}
# fmt: on
"""Every API operation (``operation_id``) and what a key may do there."""


def require_session(principal: Principal) -> None:
    """403 ``insufficient_scope`` unless the principal is a session (not an API key)."""
    if principal.auth != "session":
        raise InsufficientScopeProblem


def require_key_scope(principal: Principal, scope: ApiKeyScope) -> None:
    """403 ``insufficient_scope`` unless a key has ``scope`` (sessions always pass)."""
    if not principal.has_scope(scope):
        raise InsufficientScopeProblem


def check_route_for_key(principal: Principal, operation_id: str | None) -> None:
    """The route-level gate for a request authenticated by an API key (see the module
    docstring): a service account's key is refused everywhere (c22: MCP only), ``read``
    routes need the ``read`` scope, ``session`` and ``public`` routes and unknown
    operations are refused, ``policy`` routes are left to the policy. Sessions always
    pass."""
    if principal.auth == "session":
        return
    if principal.user.is_service_account:
        # c22 (run scope): an AI agent's key works on /mcp only, never on REST.
        raise InsufficientScopeProblem
    access = ROUTE_KEY_ACCESS.get(operation_id or "")
    if access is KeyAccess.POLICY:
        return
    if access is KeyAccess.READ:
        require_key_scope(principal, "read")
        return
    raise InsufficientScopeProblem
