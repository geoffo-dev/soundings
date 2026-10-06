import type { AuditAction } from '@/api/types'

/*
 * The audit log's action categories (the Action filter and the `action` URL
 * parameter). Kept apart from audit-phrases.ts because the route's search
 * validation needs them in the main bundle; the sentences load with the page.
 */

/** Every action, by area (the Action filter); each action in exactly one category. */
export const AUDIT_CATEGORIES = [
  {
    id: 'sign_ins',
    label: 'Sign-ins and sign-outs',
    actions: ['session.sign_in', 'session.sign_out'],
  },
  { id: 'denied', label: 'Denied sign-ins', actions: ['session.sign_in_denied'] },
  {
    id: 'users',
    label: 'User changes',
    actions: [
      'user.create',
      'user.update',
      'user.external_ids_replace',
      'user.identity_link',
      'user.identity_unlink',
      'user.sessions_end',
    ],
  },
  { id: 'group_sync', label: 'Group sync at sign-in', actions: ['user.groups_sync'] },
  {
    id: 'groups',
    label: 'Group changes',
    actions: [
      'group.create',
      'group.update',
      'group.delete',
      'group.mapping_replace',
      'group.member_add',
      'group.member_remove',
    ],
  },
  {
    id: 'project_access',
    label: 'Project access',
    actions: [
      'project.member_add',
      'project.member_update',
      'project.member_remove',
      'project.group_grant_add',
      'project.group_grant_update',
      'project.group_grant_remove',
    ],
  },
  {
    id: 'project_settings',
    label: 'Project settings',
    actions: ['project.create', 'project.update', 'project.rubric_replace'],
  },
  {
    id: 'assignments',
    label: 'Owners and evaluators',
    actions: ['idea.owner_change', 'evaluator.add', 'evaluator.remove'],
  },
  {
    id: 'evaluations',
    label: 'Evaluations',
    actions: ['evaluation.submit', 'evaluation.close', 'evaluation.reopen'],
  },
  { id: 'status', label: 'Status changes', actions: ['idea.status_change'] },
  { id: 'deleted_ideas', label: 'Deleted ideas', actions: ['idea.delete'] },
  { id: 'email', label: 'Email (test and retry)', actions: ['email.test_send', 'email.retry'] },
  {
    id: 'public_submissions',
    label: 'Public submissions',
    actions: ['submission.approve', 'submission.reject', 'submission.erase'],
  },
  { id: 'branding', label: 'Branding', actions: ['branding.update'] },
  {
    id: 'api_keys',
    label: 'API keys and MCP',
    actions: ['api_key.create', 'api_key.revoke', 'mcp.call'],
  },
  {
    id: 'ai',
    label: 'AI agents and runs',
    actions: [
      'ai_agent.register',
      'ai_agent.update',
      'ai_run.request',
      'ai_run.cancel',
      'evaluation.include_ai',
    ],
  },
] as const satisfies readonly { id: string; label: string; actions: readonly AuditAction[] }[]

export type AuditCategory = (typeof AUDIT_CATEGORIES)[number]['id']
export const AUDIT_CATEGORY_IDS = AUDIT_CATEGORIES.map<AuditCategory>((c) => c.id)

/** The API's `action` filter for the chosen categories. */
export function actionsFor(categories: readonly AuditCategory[] | undefined): AuditAction[] {
  if (!categories?.length) return []
  return AUDIT_CATEGORIES.filter((c) => categories.includes(c.id)).flatMap((c) => [...c.actions])
}
