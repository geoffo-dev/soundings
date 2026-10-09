import { describe, expect, it } from 'vitest'

import type { AuditAction, AuditEntry } from '@/api/types'

import {
  actionsFor,
  AUDIT_CATEGORIES,
  auditFields,
  auditText,
  describeAuditEntry,
  isBreakGlassEntry,
  type NameResolver,
} from './audit-phrases'

const ALICE = { id: 'u-alice', display_name: 'Alice Anders', avatar_url: null, initials: 'AA' }
const PRIYA = { id: 'u-priya', display_name: 'Priya Natarajan', avatar_url: null, initials: 'PN' }
const CUST = { id: 'p-cust', slug: 'customer-innovation', key: 'CUST', name: 'Customer Innovation' }

function entry(action: string, overrides: Partial<AuditEntry> = {}): AuditEntry {
  return {
    id: 'e-1',
    created_at: '2026-09-30T10:00:00Z',
    action,
    actor_id: ALICE.id,
    actor: ALICE,
    target_type: null,
    target_id: null,
    target_label: null,
    project: null,
    details: {},
    ...overrides,
  }
}

const names: NameResolver = {
  user: (id) =>
    ({ 'u-bob': 'Bob Brown', 'u-carol': 'Carol Chen' })[id] ?? (id === 'u-gone' ? null : undefined),
  group: (id) => ({ 'g-tools': 'Tools members', 'g-viewers': 'Viewers' })[id],
}

const say = (e: AuditEntry, resolver = names) => auditText(describeAuditEntry(e), resolver)

describe('audit sentences', () => {
  it('names the user a group member entry is about', () => {
    const e = entry('group.member_add', {
      target_type: 'group',
      target_id: 'g-innovation',
      target_label: 'Innovation members',
      details: { rule: 'platform.manage_groups', user_id: 'u-bob' },
    })
    expect(say(e)).toBe('Alice Anders added Bob Brown to group Innovation members')
    expect(say({ ...e, action: 'group.member_remove' })).toBe(
      'Alice Anders removed Bob Brown from group Innovation members',
    )
  })

  it('words ids it could not resolve, and deleted things', () => {
    const e = entry('group.member_add', {
      target_type: 'group',
      target_id: 'g-x',
      target_label: null,
      details: { user_id: 'u-unknown' },
    })
    expect(say(e)).toBe('Alice Anders added a user to a deleted group')
    expect(say({ ...e, details: { user_id: 'u-gone' } })).toBe(
      'Alice Anders added a deleted user to a deleted group',
    )
    expect(say({ ...e, actor: null })).toMatch(/^A deleted user added/)
  })

  it('describes sign-ins by method and how the account was linked', () => {
    const signIn = (details: Record<string, unknown>) =>
      say(entry('session.sign_in', { target_type: 'user', target_id: ALICE.id, details }))
    expect(signIn({ method: 'sso', matched_by: 'identity' })).toBe(
      'Alice Anders signed in with SSO',
    )
    expect(signIn({ method: 'sso', matched_by: 'external_id' })).toBe(
      'Alice Anders signed in with SSO, linked by external ID',
    )
    expect(signIn({ method: 'sso', matched_by: 'email' })).toBe(
      'Alice Anders signed in with SSO, linked by verified email',
    )
    expect(signIn({ method: 'break_glass' })).toBe(
      'Alice Anders signed in with the break-glass account',
    )
    expect(signIn({ method: 'dev_login' })).toBe(
      'Alice Anders signed in with the development login',
    )
  })

  it('never pins a denied sign-in on an actor and says why', () => {
    const denied = entry('session.sign_in_denied', {
      actor_id: null,
      actor: null,
      target_type: 'user',
      target_id: 'u-jonas',
      target_label: 'Jonas Weber',
      details: { method: 'sso', reason: 'account_disabled' },
    })
    expect(say(denied)).toBe('SSO sign-in denied for Jonas Weber: the account is deactivated')
    expect(
      say({
        ...denied,
        target_type: null,
        target_id: null,
        target_label: null,
        details: { method: 'sso', reason: 'no_match' },
      }),
    ).toBe('An SSO sign-in was denied: no matching account')
    expect(
      say({
        ...denied,
        target_type: null,
        target_id: null,
        details: { method: 'break_glass', reason: 'invalid_credentials' },
      }),
    ).toBe('A break-glass sign-in was denied: wrong username or password')
  })

  it('describes user changes, one clause per flag', () => {
    const update = (details: Record<string, unknown>) =>
      say(
        entry('user.update', {
          actor: PRIYA,
          actor_id: PRIYA.id,
          target_type: 'user',
          target_id: 'u-bob',
          target_label: 'Bob Brown',
          details,
        }),
      )
    expect(update({ fields: ['is_active'], is_active: false, sessions_ended: 2 })).toBe(
      'Priya Natarajan deactivated Bob Brown (2 sessions ended)',
    )
    expect(update({ fields: ['is_active'], is_active: true })).toBe(
      'Priya Natarajan reactivated Bob Brown',
    )
    expect(update({ fields: ['is_platform_admin'], is_platform_admin: true })).toBe(
      'Priya Natarajan made Bob Brown a platform admin',
    )
    expect(update({ fields: ['display_name', 'email'] })).toBe(
      'Priya Natarajan changed the name and email of Bob Brown',
    )
    expect(
      update({ fields: ['is_platform_admin', 'display_name'], is_platform_admin: false }),
    ).toBe(
      'Priya Natarajan removed platform admin rights from Bob Brown and changed the name of Bob Brown',
    )
  })

  it('describes pre-created users and external IDs without values', () => {
    const created = entry('user.create', {
      target_type: 'user',
      target_id: 'u-lena',
      target_label: 'Lena Novak',
      details: { source: 'admin', is_platform_admin: false, external_id_kinds: ['employee_no'] },
    })
    expect(say(created)).toBe('Alice Anders added Lena Novak')
    expect(say({ ...created, details: { source: 'admin', is_platform_admin: true } })).toBe(
      'Alice Anders added Lena Novak as a platform admin',
    )
    expect(say({ ...created, details: { source: 'sso' } })).toBe(
      'Lena Novak joined at their first SSO sign-in',
    )
    expect(
      say({
        ...created,
        action: 'user.external_ids_replace',
        details: { kinds: ['employee_no', 'gitlab'] },
      }),
    ).toBe('Alice Anders set the external IDs of Lena Novak (employee_no, gitlab)')
  })

  it('lists the groups a sign-in sync marked and unmarked as synced', () => {
    const sync = entry('user.groups_sync', {
      actor: { ...ALICE, id: 'u-carol', display_name: 'Carol Chen' },
      actor_id: 'u-carol',
      target_type: 'user',
      target_id: 'u-carol',
      target_label: 'Carol Chen',
      details: {
        added_group_ids: ['g-tools'],
        removed_group_ids: ['g-viewers'],
        claim_found: true,
      },
    })
    expect(say(sync)).toBe(
      'Sign-in sync for Carol Chen: now a synced member of Tools members; no longer a synced member of Viewers',
    )
    expect(
      say({
        ...sync,
        details: {
          added_group_ids: [],
          removed_group_ids: ['g-tools', 'g-viewers'],
          claim_found: false,
        },
      }),
    ).toBe(
      'Sign-in sync for Carol Chen: no longer a synced member of Tools members and Viewers (the token had no groups claim)',
    )
  })

  it('describes group mapping changes', () => {
    const mapping = entry('group.mapping_replace', {
      target_type: 'group',
      target_id: 'g-viewers',
      target_label: 'Viewers',
      details: {
        from_sync_mode: 'managed',
        sync_mode: 'additive',
        from_idp_values: ['viewers'],
        idp_values: ['viewers'],
      },
    })
    expect(say(mapping)).toBe('Alice Anders changed the mapping of group Viewers: now additive')
    expect(
      say({
        ...mapping,
        details: {
          from_sync_mode: 'managed',
          sync_mode: 'managed',
          from_idp_values: ['a'],
          idp_values: [],
        },
      }),
    ).toBe('Alice Anders changed the mapping of group Viewers: no longer mapped')
  })

  it('describes project access through people and groups', () => {
    expect(
      say(
        entry('project.group_grant_add', {
          target_type: 'group',
          target_id: 'g-tools',
          target_label: 'Tools members',
          project: CUST,
          details: { role: 'member' },
        }),
      ),
    ).toBe('Alice Anders gave group Tools members the member role in Customer Innovation')
    // The backend targets the user; older mock data names them in details.
    expect(
      say(
        entry('project.member_update', {
          target_type: 'user',
          target_id: 'u-bob',
          target_label: 'Bob Brown',
          project: CUST,
          details: { from_role: 'viewer', role: 'member' },
        }),
      ),
    ).toBe(
      'Alice Anders changed the role of Bob Brown in Customer Innovation from viewer to member',
    )
    expect(
      say(
        entry('project.member_update', {
          target_type: 'project',
          target_id: CUST.id,
          target_label: CUST.name,
          project: CUST,
          details: { user_id: 'u-carol', from_role: 'viewer', role: 'member' },
        }),
      ),
    ).toBe(
      'Alice Anders changed the role of Carol Chen in Customer Innovation from viewer to member',
    )
  })

  it('describes ideas: status, owner, evaluators and evaluations', () => {
    const onIdea = (action: string, details: Record<string, unknown>) =>
      say(
        entry(action, {
          target_type: 'idea',
          target_id: 'i-12',
          target_label: 'CUST-12',
          project: CUST,
          details,
        }),
      )
    expect(
      onIdea('idea.status_change', {
        from_status: 'shortlisted',
        to_status: 'closed',
        to_resolution: 'accepted',
      }),
    ).toBe('Alice Anders moved CUST-12 from Shortlisted to Accepted')
    expect(onIdea('idea.owner_change', { from_owner_id: null, to_owner_id: 'u-bob' })).toBe(
      'Alice Anders made Bob Brown the owner of CUST-12',
    )
    expect(onIdea('idea.owner_change', { to_owner_id: ALICE.id })).toBe(
      'Alice Anders took on CUST-12 as owner',
    )
    expect(onIdea('idea.owner_change', { to_owner_id: null })).toBe(
      'Alice Anders removed the owner of CUST-12',
    )
    expect(onIdea('evaluation.submit', { evaluation_id: 'x' })).toBe(
      'Alice Anders submitted an evaluation of CUST-12',
    )
    expect(onIdea('evaluation.close', { rule: 'evaluation.close' })).toBe(
      'Alice Anders closed evaluation of CUST-12',
    )
    expect(onIdea('evaluation.reopen', { rule: 'evaluation.close' })).toBe(
      'Alice Anders reopened evaluation of CUST-12',
    )
    // The backend's evaluator entries target the evaluator, with the idea id in details.
    expect(
      say(
        entry('evaluator.add', {
          target_type: 'user',
          target_id: 'u-bob',
          target_label: 'Bob Brown',
          project: CUST,
          details: { idea_id: 'i-12' },
        }),
      ),
    ).toBe('Alice Anders asked Bob Brown to evaluate an idea in Customer Innovation')
    // …resolved to its key by the screen once known.
    expect(
      auditText(
        describeAuditEntry(
          entry('evaluator.remove', {
            target_type: 'user',
            target_id: 'u-bob',
            target_label: 'Bob Brown',
            project: CUST,
            details: { idea_id: 'i-12' },
          }),
        ),
        { ...names, idea: (id) => (id === 'i-12' ? 'CUST-12' : undefined) },
      ),
    ).toBe('Alice Anders removed Bob Brown as an evaluator of CUST-12')
    expect(
      say(
        entry('idea.delete', {
          target_type: 'idea',
          target_id: 'i-3',
          project: CUST,
          details: { number: 3 },
        }),
      ),
    ).toBe('Alice Anders deleted CUST-3')
  })

  it('describes the admin email actions without any address', () => {
    expect(
      say(entry('email.test_send', { details: { outbound_email_id: 'x', to_self: true } })),
    ).toBe('Alice Anders sent a test email to themselves')
    expect(
      say(entry('email.test_send', { details: { outbound_email_id: 'x', to_self: false } })),
    ).toBe('Alice Anders sent a test email to another address')
    expect(say(entry('email.retry', { details: { outbound_email_id: 'x' } }))).toBe(
      'Alice Anders retried a failed email',
    )
    expect(say(entry('email.retry', { details: { count: 3 } }))).toBe(
      'Alice Anders retried 3 failed emails (Retry all failed)',
    )
  })

  it('describes moderation, erasure and branding without personal data', () => {
    const onIdea = (action: string, details: Record<string, unknown>, extra = {}) =>
      say(
        entry(action, {
          target_type: 'idea',
          target_id: 'i-9',
          target_label: 'GREEN-9',
          details,
          ...extra,
        }),
      )
    expect(onIdea('submission.approve', { rule: 'idea.moderate' })).toBe(
      'Alice Anders approved GREEN-9 from the public form',
    )
    // Rejected ideas are deleted: the key comes from details.
    expect(
      say(
        entry('submission.reject', {
          target_type: 'idea',
          target_id: 'i-11',
          details: { rule: 'idea.moderate', key: 'GREEN-11' },
        }),
      ),
    ).toBe('Alice Anders rejected and deleted GREEN-11 from the public form')
    expect(onIdea('submission.erase', { rule: 'public.erase_submitter' })).toBe(
      'Alice Anders erased the submitter’s details of GREEN-9',
    )
    expect(
      onIdea('submission.erase', { reason: 'submitter' }, { actor: null, actor_id: null }),
    ).toBe('The submitter of GREEN-9 erased their details')
    expect(
      onIdea('submission.erase', { reason: 'retention' }, { actor: null, actor_id: null }),
    ).toBe('The submitter’s details of GREEN-9 were erased automatically (closed for 180 days)')
    expect(
      say(
        entry('branding.update', {
          details: { rule: 'platform.edit_branding', fields: ['primary_color', 'logo_asset_id'] },
        }),
      ),
    ).toBe('Alice Anders changed the primary colour and logo of the branding')
    expect(say(entry('branding.update'))).toBe('Alice Anders changed the branding')
    expect(
      say(
        entry('project.update', {
          project: CUST,
          details: { fields: ['public_submission_enabled', 'public_moderation_required'] },
        }),
      ),
    ).toBe('Alice Anders changed the public form and public form moderation of Customer Innovation')
  })

  it('describes API keys by their prefix, never more', () => {
    const own = {
      target_type: 'user' as const,
      target_id: ALICE.id,
      target_label: ALICE.display_name,
    }
    expect(
      say(
        entry('api_key.create', {
          ...own,
          details: {
            rule: 'api_key.manage_own',
            key_id: 'k-1',
            prefix: 'sdg_Ab12Cd34Ef56',
            scopes: ['read', 'evaluate', 'mcp'],
            restricted: true,
            project_ids: [CUST.id],
            expires_at: '2027-01-02T10:00:00Z',
          },
        }),
      ),
    ).toBe(
      'Alice Anders created API key sdg_Ab12Cd34Ef56: Read, Evaluate and AI assistants (MCP); 1 project; expires 2 Jan 2027',
    )
    expect(
      say(
        entry('api_key.create', {
          actor: PRIYA,
          actor_id: PRIYA.id,
          target_type: 'user',
          target_id: 'u-agent',
          target_label: 'Research agent',
          details: { prefix: 'sdg_Zz', scopes: ['read'], restricted: false, expires_at: null },
        }),
      ),
    ).toBe(
      'Priya Natarajan created API key sdg_Zz for Research agent: Read; all projects; never expires',
    )
    expect(
      say(
        entry('api_key.revoke', {
          ...own,
          details: { rule: 'api_key.manage_own', prefix: 'sdg_Ab' },
        }),
      ),
    ).toBe('Alice Anders revoked API key sdg_Ab')
    expect(
      say(
        entry('api_key.revoke', {
          ...own,
          actor: PRIYA,
          actor_id: PRIYA.id,
          details: { rule: 'api_key.manage_any', prefix: 'sdg_Ab' },
        }),
      ),
    ).toBe('Priya Natarajan revoked API key sdg_Ab of Alice Anders')
    expect(
      say(
        entry('api_key.revoke', {
          ...own,
          actor: PRIYA,
          actor_id: PRIYA.id,
          details: { rule: 'platform.manage_users', prefix: 'sdg_Ab', reason: 'deactivated' },
        }),
      ),
    ).toBe('Priya Natarajan deactivated Alice Anders, which revoked API key sdg_Ab')
  })

  it('describes MCP calls with their tool, target and outcome', () => {
    const call = (details: Record<string, unknown>, overrides: Partial<AuditEntry> = {}) =>
      say(
        entry('mcp.call', {
          details: { auth: 'api_key', api_key_id: 'k-1', ...details },
          ...overrides,
        }),
      )
    const onIdea = {
      target_type: 'idea' as const,
      target_id: 'i-12',
      target_label: 'CUST-12',
      project: CUST,
    }
    expect(
      call({ tool: 'get_idea', rule: 'idea.view', decision: 'allow', code: null }, onIdea),
    ).toBe('Alice Anders’s key called get_idea on CUST-12')
    expect(
      call({ tool: 'get_idea', rule: 'idea.view', decision: 'deny', code: 'not_found' }, onIdea),
    ).toBe('Alice Anders’s key called get_idea on CUST-12: denied (not found)')
    expect(
      call({ tool: 'submit_evaluation', decision: 'allow', code: 'evaluation_closed' }, onIdea),
    ).toBe('Alice Anders’s key called submit_evaluation on CUST-12: failed (evaluation closed)')
    expect(
      call(
        { tool: 'create_idea', decision: 'deny', code: 'insufficient_scope' },
        { target_type: 'project', target_id: CUST.id, target_label: CUST.name, project: CUST },
      ),
    ).toBe(
      'Alice Anders’s key called create_idea in Customer Innovation: denied (insufficient scope)',
    )
    expect(call({ tool: 'search_ideas', decision: 'allow' })).toBe(
      'Alice Anders’s key called search_ideas',
    )
    expect(call({ tool: 'unknown', decision: 'deny', code: 'unknown_tool' })).toBe(
      'Alice Anders’s key called an unknown tool: denied (unknown tool)',
    )
    expect(
      call({ tool: null, rule: 'mcp.connect', decision: 'deny', code: 'insufficient_scope' }),
    ).toBe('Alice Anders’s key was refused by the MCP server: it doesn’t allow AI assistants (MCP)')
  })

  it('describes AI agents, runs and the include toggle without agent text', () => {
    const agentTarget = {
      target_type: 'user' as const,
      target_id: 'u-agent',
      target_label: 'Idea evaluator',
    }
    const onIdea = {
      target_type: 'idea' as const,
      target_id: 'i-7',
      target_label: 'CUST-7',
      project: CUST,
    }
    expect(
      say(
        entry('ai_agent.register', {
          actor: PRIYA,
          actor_id: PRIYA.id,
          ...agentTarget,
          details: {
            namespace: 'soundings',
            name: 'idea-evaluator',
            purposes: ['research', 'evaluate'],
          },
        }),
      ),
    ).toBe(
      'Priya Natarajan registered AI agent Idea evaluator (soundings/idea-evaluator) for evaluation and research',
    )
    expect(
      say(
        entry('ai_agent.update', {
          ...agentTarget,
          details: { changed: ['enabled'], enabled: false },
        }),
      ),
    ).toBe(
      'Alice Anders disabled AI agent Idea evaluator, which stopped its runs and revoked its key',
    )
    expect(
      say(
        entry('ai_agent.update', {
          ...agentTarget,
          details: { changed: ['purposes', 'project_ids'] },
        }),
      ),
    ).toBe('Alice Anders changed the purposes and projects of AI agent Idea evaluator')
    expect(say(entry('ai_run.request', { ...onIdea, details: { kind: 'evaluate' } }))).toBe(
      'Alice Anders asked an AI agent to evaluate CUST-7',
    )
    expect(
      say(
        entry('ai_run.request', {
          ...onIdea,
          details: { kind: 'draft_section', section_key: 'risks' },
        }),
      ),
    ).toBe('Alice Anders asked an AI agent to draft Risks of CUST-7')
    // With its agent: named once the screen resolves it, "an AI agent" until then.
    const asked = describeAuditEntry(
      entry('ai_run.request', { ...onIdea, details: { kind: 'research', agent_id: 'ag-1' } }),
    )
    expect(auditText(asked)).toBe('Alice Anders asked an AI agent to research CUST-7')
    expect(
      auditText(asked, {
        user: () => undefined,
        group: () => undefined,
        agent: (id) => (id === 'ag-1' ? 'Research agent' : undefined),
      }),
    ).toBe('Alice Anders asked AI agent Research agent to research CUST-7')
    expect(say(entry('ai_run.cancel', { ...onIdea, details: { rule: 'ai.cancel_run' } }))).toBe(
      'Alice Anders cancelled an AI run on CUST-7',
    )
    expect(
      say(
        entry('evaluation.include_ai', {
          ...onIdea,
          details: { evaluator_id: 'u-carol', include: true },
        }),
      ),
    ).toBe('Alice Anders counted Carol Chen’s evaluation of CUST-7 in the score')
    expect(
      say(
        entry('evaluation.include_ai', {
          ...onIdea,
          details: { evaluator_id: 'u-carol', include: false },
        }),
      ),
    ).toBe('Alice Anders left Carol Chen’s evaluation of CUST-7 out of the score')
    const noteDeleted = describeAuditEntry(
      entry('ai_note.delete', {
        ...onIdea,
        details: { rule: 'ai.delete_note', note_id: 'n-1', run_id: 'r-1', agent_id: 'ag-1' },
      }),
    )
    expect(auditText(noteDeleted)).toBe(
      'Alice Anders deleted a research note by an AI agent on CUST-7',
    )
    expect(
      auditText(noteDeleted, {
        user: () => undefined,
        group: () => undefined,
        agent: (id) => (id === 'ag-1' ? 'Research agent' : undefined),
      }),
    ).toBe('Alice Anders deleted a research note by AI agent Research agent on CUST-7')
    expect(say(entry('ai_note.delete', { ...onIdea, details: { rule: 'ai.delete_note' } }))).toBe(
      'Alice Anders deleted an AI research note on CUST-7',
    )
    expect(
      say(
        entry('evaluator.remove', {
          ...onIdea,
          actor: null,
          actor_id: null,
          details: { evaluator_id: 'u-carol', reason: 'ai_run_ended' },
        }),
      ),
    ).toBe(
      'Carol Chen was taken off the evaluators of CUST-7: its AI run ended without an evaluation',
    )
  })

  it('says an account was anonymised at the console, with counts only', () => {
    const anonymised = entry('user.anonymise', {
      actor: null,
      actor_id: null,
      target_type: 'user',
      target_id: 'u-jonas',
      target_label: 'Former user 3f2a',
      details: { identities: 1, external_ids: 2, api_keys: 0, sessions: 1 },
    })
    expect(say(anonymised)).toBe(
      'The deactivated account Former user 3f2a was anonymised at the console (removed: 1 SSO link, 2 external IDs, 1 session)',
    )
    expect(say({ ...anonymised, details: {} })).toBe(
      'The deactivated account Former user 3f2a was anonymised at the console',
    )
  })

  it('words the Phase 8 template, research step, checklist and override entries', () => {
    const inProject = { target_type: 'project' as const, target_id: CUST.id, project: CUST }
    expect(
      say(
        entry('project.proposal_template_replace', {
          ...inProject,
          details: { added: ['the_ask'], archived: ['market'], reordered: true },
        }),
      ),
    ).toBe('Alice Anders changed the proposal template of Customer Innovation')
    expect(
      say(
        entry('project.research_step_change', {
          ...inProject,
          details: { from: 'off', to: 'before_evaluation' },
        }),
      ),
    ).toBe('Alice Anders set the research step of Customer Innovation to Before evaluation')
    expect(
      say(entry('project.research_step_change', { ...inProject, details: { to: 'off' } })),
    ).toBe('Alice Anders set the research step of Customer Innovation to Off')
    expect(
      say(entry('project.research_checklist_replace', { ...inProject, details: { added: 1 } })),
    ).toBe('Alice Anders changed the research checklist of Customer Innovation')
    const override = entry('idea.research_override', {
      target_type: 'idea',
      target_id: 'i-7',
      target_label: 'CUST-7',
      project: CUST,
      details: {
        operation: 'change_idea_status',
        from_status: 'research',
        to_status: 'evaluating',
        open_items: 2,
        reason: 'Legal asked us to start now',
      },
    })
    expect(say(override)).toBe(
      'Alice Anders moved CUST-7 past research without finishing it (to Evaluating), 2 required items open: “Legal asked us to start now”',
    )
    expect(say({ ...override, details: { open_items: 1 } })).toBe(
      'Alice Anders moved CUST-7 past research without finishing it, 1 required item open',
    )
    // Worded by the request it let through: an invite never reads "moved … (to New)".
    const by = (operation: string) =>
      say({
        ...override,
        details: { operation, from_status: 'new', to_status: 'new', open_items: 2 },
      })
    expect(by('add_evaluators')).toBe(
      'Alice Anders invited evaluators to CUST-7 without finishing its research, 2 required items open',
    )
    expect(by('request_ai_evaluation')).toBe(
      'Alice Anders asked AI to evaluate CUST-7 without finishing its research, 2 required items open',
    )
    expect(by('create_proposal')).toBe(
      'Alice Anders started the proposal for CUST-7 without finishing its research, 2 required items open',
    )
  })

  it('words the Phase 8b research assignment entries', () => {
    const base = {
      target_type: 'idea' as const,
      target_id: 'i-12',
      target_label: 'TOOL-12',
      project: CUST,
    }
    const people: NameResolver = {
      ...names,
      user: (id) => ({ 'u-bob': 'Bob Brown', 'u-ann': 'Ann Lee' })[id],
    }
    const change = (details: Record<string, unknown>) =>
      say(entry('idea.researcher_change', { ...base, details }), people)
    expect(
      change({
        from_user_id: null,
        to_user_id: 'u-bob',
        reason: 'assigned',
        outside_project: true,
      }),
    ).toBe('Alice Anders asked Bob Brown to research TOOL-12, outside the project')
    expect(change({ from_user_id: 'u-ann', to_user_id: 'u-bob', reason: 'assigned' })).toBe(
      'Alice Anders asked Bob Brown to research TOOL-12',
    )
    expect(change({ from_user_id: null, to_user_id: 'u-alice', reason: 'assigned' })).toBe(
      'Alice Anders took on the research of TOOL-12',
    )
    expect(change({ from_user_id: 'u-bob', to_user_id: null, reason: 'removed' })).toBe(
      'Alice Anders removed Bob Brown as researcher of TOOL-12',
    )
    expect(change({ from_user_id: 'u-alice', to_user_id: null, reason: 'handed_back' })).toBe(
      'Alice Anders handed back the research of TOOL-12',
    )
    expect(change({ from_user_id: 'u-bob', to_user_id: null, reason: 'deactivated' })).toBe(
      'Bob Brown was removed as researcher of TOOL-12 (account deactivated)',
    )
    expect(change({ from_user_id: 'u-bob', to_user_id: null, reason: 'closed' })).toBe(
      'Bob Brown was removed as researcher of TOOL-12 (idea closed)',
    )
    expect(change({ from_user_id: 'u-bob', to_user_id: null, reason: 'step_off' })).toBe(
      'Bob Brown was removed as researcher of TOOL-12 (research step turned off)',
    )
    expect(change({ from_user_id: 'u-bob', to_user_id: null, reason: 'left_project' })).toBe(
      'Bob Brown was removed as researcher of TOOL-12 (left the project)',
    )
  })

  it('falls back to the raw action for unknown actions', () => {
    expect(say(entry('agent.something_new'))).toBe('Alice Anders: agent.something_new')
  })
})

describe('audit categories', () => {
  it('put every action in exactly one category', () => {
    const every: Record<AuditAction, true> = {
      'session.sign_in': true,
      'session.sign_in_denied': true,
      'session.sign_out': true,
      'user.create': true,
      'user.update': true,
      'user.external_ids_replace': true,
      'user.identity_link': true,
      'user.identity_unlink': true,
      'user.sessions_end': true,
      'user.groups_sync': true,
      'user.anonymise': true,
      'group.create': true,
      'group.update': true,
      'group.delete': true,
      'group.mapping_replace': true,
      'group.member_add': true,
      'group.member_remove': true,
      'project.create': true,
      'project.update': true,
      'project.member_add': true,
      'project.member_update': true,
      'project.member_remove': true,
      'project.group_grant_add': true,
      'project.group_grant_update': true,
      'project.group_grant_remove': true,
      'project.rubric_replace': true,
      'idea.delete': true,
      'idea.owner_change': true,
      'idea.status_change': true,
      'evaluator.add': true,
      'evaluator.remove': true,
      'evaluation.submit': true,
      'evaluation.close': true,
      'evaluation.reopen': true,
      'email.test_send': true,
      'email.retry': true,
      'submission.approve': true,
      'submission.reject': true,
      'submission.erase': true,
      'branding.update': true,
      'api_key.create': true,
      'api_key.revoke': true,
      'mcp.call': true,
      'ai_agent.register': true,
      'ai_agent.update': true,
      'ai_run.request': true,
      'ai_run.cancel': true,
      'evaluation.include_ai': true,
      'ai_note.delete': true,
      'project.proposal_template_replace': true,
      'project.research_step_change': true,
      'project.research_checklist_replace': true,
      'idea.research_override': true,
      'idea.researcher_change': true,
    }
    const listed = AUDIT_CATEGORIES.flatMap((c) => [...c.actions])
    expect([...listed].sort()).toEqual(Object.keys(every).sort())
  })

  it('turns categories into the API action filter', () => {
    expect(actionsFor(['denied', 'status'])).toEqual([
      'session.sign_in_denied',
      'idea.status_change',
      'idea.research_override',
    ])
    expect(actionsFor(undefined)).toEqual([])
  })
})

describe('audit details', () => {
  it('lists raw fields with details sorted and flags break-glass sessions', () => {
    const e = entry('user.sessions_end', {
      target_type: 'user',
      target_id: 'u-bob',
      details: { rule: 'platform.manage_users', count: 2, auth_method: 'break_glass' },
    })
    expect(auditFields(e).map((row) => row.label)).toEqual([
      'action',
      'created_at',
      'actor_id',
      'target',
      'auth_method',
      'count',
      'rule',
    ])
    expect(auditFields(e).find((row) => row.label === 'count')?.value).toBe('2')
    expect(isBreakGlassEntry(e)).toBe(true)
    expect(isBreakGlassEntry(entry('session.sign_out', { details: { auth_method: 'sso' } }))).toBe(
      false,
    )
  })
})
