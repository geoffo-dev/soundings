"""Every API operation declares the role-matrix rule(s) it is authorised by (role
matrix section 7: "a meta-test fails if any route has no rule"), and every rule
named here exists in the policy. The contract (docs/api/contract-phase1.md section 2)
is the source; keep this table in step with it."""

from __future__ import annotations

from app.authz import POLICY, Rule
from tests.test_contract_routes import CONTRACT

SIGNED_IN = "signed in"  # a session is enough; contents are filtered by view rules
PUBLIC = "public"  # no principal needed (sign-in methods, logout)

ROUTE_RULES: dict[str, tuple[str, ...]] = {
    "get_me": (SIGNED_IN,),
    "list_dev_users": (PUBLIC,),
    "dev_login": (PUBLIC,),
    "logout": (PUBLIC,),
    "search_users": ("user.search", "project.view"),
    "list_projects": ("project.view",),
    "create_project": ("project.create",),
    "get_project": ("project.view",),
    "update_project": ("project.edit_settings", "project.rename_status_labels"),
    "list_project_members": ("project.view",),
    "add_project_member": ("project.manage_members",),
    "update_project_member": ("project.manage_members",),
    "remove_project_member": ("project.manage_members",),
    "replace_rubric": ("project.edit_rubric",),
    "list_project_tags": ("project.view", "idea.view"),
    "list_ideas": ("project.view", "idea.view", "score.view_aggregate"),
    "get_board": ("project.view", "idea.view", "score.view_aggregate"),
    "create_idea": ("idea.create",),
    "get_idea": ("idea.view", "score.view_aggregate"),
    "update_idea": ("idea.edit_own", "idea.edit_any"),
    "delete_idea": ("idea.delete",),
    "change_idea_status": ("idea.change_status",),
    "set_idea_owner": ("idea.assign_owner", "idea.release_owner"),
    "volunteer_as_owner": ("idea.volunteer_owner",),
    "add_evaluators": ("evaluator.manage",),
    "remove_evaluator": ("evaluator.manage",),
    "set_evaluation_due_date": ("idea.set_due_date",),
    "close_evaluation": ("evaluation.close",),
    "reopen_evaluation": ("evaluation.close",),
    "list_evaluations": ("idea.view", "evaluation.view_others"),
    "get_my_evaluation": ("evaluation.view_own",),
    "save_my_evaluation": ("evaluation.submit_own",),
    "vote_idea": ("idea.vote",),
    "unvote_idea": ("idea.vote",),
    "watch_idea": ("idea.watch",),
    "unwatch_idea": ("idea.watch",),
    "list_idea_activity": ("idea.view",),
    "create_comment": ("comment.create",),
    "update_comment": ("comment.edit_own",),
    "delete_comment": ("comment.edit_own", "comment.delete_any"),
    "get_my_work": (SIGNED_IN, "idea.view", "score.view_aggregate"),
    "list_my_owned_ideas": (SIGNED_IN, "idea.view", "score.view_aggregate"),
    "global_search": (SIGNED_IN, "project.view", "idea.view"),
    # Phase 2 (docs/api/contract-phase2.md section 2)
    "get_auth_config": (PUBLIC,),
    "sso_login": (PUBLIC,),
    "sso_callback": (PUBLIC,),
    "break_glass_login": (PUBLIC,),
    "logout_redirect": (PUBLIC,),
    "list_admin_users": ("platform.manage_users",),
    "create_admin_user": ("platform.manage_users",),
    "get_admin_user": ("platform.manage_users",),
    "update_admin_user": ("platform.manage_users",),
    "replace_user_external_ids": ("platform.manage_users",),
    "unlink_user_identity": ("platform.manage_users",),
    "end_user_sessions": ("platform.manage_users",),
    "list_admin_groups": ("platform.manage_groups",),
    "create_group": ("platform.manage_groups",),
    "test_group_mapping": ("platform.manage_groups",),
    "get_group": ("platform.manage_groups",),
    "update_group": ("platform.manage_groups",),
    "delete_group": ("platform.manage_groups",),
    "replace_group_mapping": ("platform.manage_groups",),
    "list_group_members": ("platform.manage_groups",),
    "add_group_member": ("platform.manage_groups",),
    "remove_group_member": ("platform.manage_groups",),
    "search_groups": ("user.search",),
    "list_project_group_grants": ("project.view",),
    "add_project_group_grant": ("project.manage_members",),
    "update_project_group_grant": ("project.manage_members",),
    "remove_project_group_grant": ("project.manage_members",),
    "list_project_access": ("project.view",),
    "list_audit_entries": ("platform.view_audit_log",),
    "get_sso_config": ("platform.configure_sso",),
    # Phase 3 (docs/api/contract-phase3.md section 2)
    "list_notifications": (SIGNED_IN, "idea.view"),
    "get_notification_summary": (SIGNED_IN, "idea.view"),
    "mark_notification_read": (SIGNED_IN, "idea.view"),
    "mark_all_notifications_read": (SIGNED_IN, "idea.view"),
    "get_notification_preferences": ("self.manage_profile",),
    "update_notification_preferences": ("self.manage_profile",),
    "get_unsubscribe": ("self.unsubscribe",),
    "confirm_unsubscribe": ("self.unsubscribe",),
    "get_email_config": ("platform.configure_email",),
    "send_test_email": ("platform.configure_email",),
    "list_outbox_emails": ("platform.configure_email",),
    "retry_failed_outbox_emails": ("platform.configure_email",),
    "get_outbox_email": ("platform.configure_email",),
    "retry_outbox_email": ("platform.configure_email",),
}


def test_every_operation_has_a_rule() -> None:
    assert set(ROUTE_RULES) == {operation_id for _, _, operation_id in CONTRACT}


def test_every_named_rule_is_in_the_policy() -> None:
    named = {rule for rules in ROUTE_RULES.values() for rule in rules} - {SIGNED_IN, PUBLIC}

    assert named <= {str(rule) for rule in POLICY}
    assert all(Rule(rule) in POLICY for rule in named)
