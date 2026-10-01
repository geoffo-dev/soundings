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
    }
    const listed = AUDIT_CATEGORIES.flatMap((c) => [...c.actions])
    expect([...listed].sort()).toEqual(Object.keys(every).sort())
  })

  it('turns categories into the API action filter', () => {
    expect(actionsFor(['denied', 'status'])).toEqual([
      'session.sign_in_denied',
      'idea.status_change',
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
