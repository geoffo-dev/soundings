/**
 * Phase 2 fixtures (contract-phase2): SSO identities, external IDs, groups that
 * mirror the dev Keycloak realm (`/innovation/admins`, `/innovation/members`,
 * `/tools/members`, `/viewers`), project grants to those groups, sessions and a
 * realistic audit log. Deterministic, relative to `db.now`.
 *
 * Group grants never change a Phase 1 fixture user's effective role (tests rely
 * on them); Kofi Boateng and Lena Novak are the people who have access only
 * through groups.
 */
import type { AuditAction, AuditTargetType, GroupSyncMode, ProjectRole } from '@/api/types'

import type { MockDb, USERS as UsersMap } from './db'

type Users = typeof UsersMap
type UserKey = keyof Users

const HOUR = 3_600_000
const DAY = 24 * HOUR

/** The dev realm's issuer (dev/keycloak/realm-soundings.json). */
export const FIXTURE_ISSUER = 'http://localhost:8080/realms/soundings'

/** Group ids for tests (kind 9). */
export const GROUPS = {
  innovationAdmins: '90000000-0000-4000-8000-000000000001',
  innovationMembers: '90000000-0000-4000-8000-000000000002',
  toolsMembers: '90000000-0000-4000-8000-000000000003',
  viewers: '90000000-0000-4000-8000-000000000004',
  champions: '90000000-0000-4000-8000-000000000005',
  contractors: '90000000-0000-4000-8000-000000000006',
} as const

type GroupKey = keyof typeof GROUPS
type ProjectKey = 'cust' | 'tool' | 'green'

interface GroupSpec {
  key: GroupKey
  name: string
  description: string
  sync_mode: GroupSyncMode
  idp_values: string[]
  createdDays: number
  /** [user, manual, synced, days since joining] */
  members: [UserKey, boolean, boolean, number][]
  grants: [ProjectKey, ProjectRole, number][]
}

const GROUP_SPECS: GroupSpec[] = [
  {
    key: 'innovationAdmins',
    name: 'Innovation admins',
    description: 'Runs the Customer Innovation programme.',
    sync_mode: 'managed',
    idp_values: ['innovation/admins'],
    createdDays: 429,
    members: [['priya', false, true, 420]],
    grants: [['cust', 'admin', 428]],
  },
  {
    key: 'innovationMembers',
    name: 'Innovation members',
    description: 'Everyone who submits and evaluates customer ideas.',
    sync_mode: 'managed',
    idp_values: ['innovation/members'],
    createdDays: 429,
    members: [
      ['alice', false, true, 409],
      ['bob', false, true, 404],
      ['carol', false, true, 399],
      ['dave', false, true, 394],
      ['farid', false, true, 379],
      ['hannah', true, false, 300],
      ['jonas', false, true, 480],
      ['kofi', false, true, 20],
    ],
    grants: [['cust', 'member', 428]],
  },
  {
    key: 'toolsMembers',
    name: 'Tools members',
    description: 'Platform and developer-experience engineers.',
    sync_mode: 'managed',
    idp_values: ['tools/members'],
    createdDays: 429,
    members: [
      ['alice', false, true, 409],
      ['bob', false, true, 404],
      ['dave', false, true, 394],
      ['farid', true, true, 379],
      ['kofi', false, true, 20],
      ['lena', true, false, 5],
    ],
    grants: [['tool', 'member', 14]],
  },
  {
    key: 'viewers',
    name: 'Viewers',
    description: 'Read-only access for stakeholders.',
    sync_mode: 'additive',
    idp_values: ['viewers'],
    createdDays: 429,
    members: [
      ['emma', false, true, 389],
      ['grace', false, true, 369],
    ],
    grants: [['green', 'viewer', 120]],
  },
  {
    key: 'champions',
    name: 'Sustainability champions',
    description: 'Volunteers who look after the sustainability backlog.',
    sync_mode: 'managed',
    idp_values: [],
    createdDays: 45,
    members: [
      ['carol', true, false, 45],
      ['grace', true, false, 44],
    ],
    grants: [['green', 'member', 45]],
  },
  {
    key: 'contractors',
    name: 'Contractors',
    description: 'External contractors. Grant access per project.',
    sync_mode: 'additive',
    idp_values: ['contractors', 'external/contractors'],
    createdDays: 12,
    members: [],
    grants: [],
  },
]

/** Keycloak subjects are UUIDs; these are fixed so audit entries can name them. */
const subject = (n: number) => `5c0f1a2e-8d3b-4c6a-9e7f-${n.toString(16).padStart(12, '0')}`

/** [user, days since linking, hours since last SSO sign-in] — Lena and break-glass have none. */
const IDENTITIES: [UserKey, number, number][] = [
  ['priya', 420, 1],
  ['alice', 409, 0.2],
  ['bob', 404, 2],
  ['carol', 399, 26],
  ['dave', 394, 75],
  ['emma', 389, 120],
  ['farid', 379, 6],
  ['grace', 369, 50],
  ['hannah', 300, 290],
  ['ivan', 29, 22],
  ['jonas', 480, 4900],
  ['kofi', 20, 3],
]

const EXTERNAL_IDS: [UserKey, string, string][] = [
  ['priya', 'employee_no', 'E1000'],
  ['priya', 'gitlab', 'pnatarajan'],
  ['alice', 'employee_no', 'E1001'],
  ['bob', 'employee_no', 'E1002'],
  ['carol', 'employee_no', 'E1003'],
  ['dave', 'employee_no', 'E1004'],
  ['farid', 'employee_no', 'E1006'],
  ['hannah', 'employee_no', 'E1008'],
  ['jonas', 'employee_no', 'E0997'],
  ['kofi', 'employee_no', 'E1011'],
  ['lena', 'employee_no', 'E1012'],
  ['lena', 'gitlab', 'lnovak'],
]

const SESSIONS: Partial<Record<UserKey, number>> = {
  priya: 2,
  alice: 1,
  bob: 1,
  carol: 1,
  emma: 1,
  farid: 2,
  ivan: 1,
  kofi: 1,
}

export function seedAccess(
  db: MockDb,
  {
    users,
    projects,
    nextId,
  }: {
    users: Users
    projects: Record<ProjectKey, string>
    nextId: (kind: number | string) => string
  },
): void {
  const now = db.now
  const iso = (ms: number) => new Date(ms).toISOString()
  const daysAgo = (days: number) => iso(now - days * DAY)

  // Identities and external IDs.
  const identityOf: Partial<Record<UserKey, { id: string; subject: string }>> = {}
  for (const [index, [user, linkedDays, loginHours]] of IDENTITIES.entries()) {
    const id = nextId('a')
    const sub = subject(index + 1)
    identityOf[user] = { id, subject: sub }
    db.identities.push({
      id,
      user_id: users[user],
      issuer: FIXTURE_ISSUER,
      subject: sub,
      linked_at: daysAgo(linkedDays),
      last_login_at: iso(now - loginHours * HOUR),
    })
  }
  for (const [user, kind, value] of EXTERNAL_IDS) {
    db.externalIds.push({ user_id: users[user], kind, value })
  }
  for (const [user, count] of Object.entries(SESSIONS) as [UserKey, number][]) {
    db.sessions[users[user]] = count
  }

  // Groups, memberships and project grants.
  for (const spec of GROUP_SPECS) {
    db.groups.push({
      id: GROUPS[spec.key],
      name: spec.name,
      description: spec.description,
      sync_mode: spec.sync_mode,
      idp_values: [...spec.idp_values].sort(),
      created_at: daysAgo(spec.createdDays),
      updated_at: daysAgo(spec.key === 'viewers' ? 60 : spec.createdDays),
    })
    for (const [user, manual, synced, days] of spec.members) {
      db.groupMembers.push({
        group_id: GROUPS[spec.key],
        user_id: users[user],
        manual,
        synced,
        joined_at: daysAgo(days),
      })
    }
    for (const [project, role, days] of spec.grants) {
      db.groupGrants.push({
        project_id: projects[project],
        group_id: GROUPS[spec.key],
        role,
        granted_at: daysAgo(days),
      })
    }
  }

  // The audit log.
  const entry = (
    at: number,
    action: AuditAction,
    actor: UserKey | null,
    target: [AuditTargetType, string] | null,
    details: Record<string, unknown>,
    project: ProjectKey | null = null,
  ) => {
    db.audit.push({
      id: nextId('b'),
      created_at: iso(at),
      actor_id: actor ? users[actor] : null,
      action,
      target_type: target?.[0] ?? null,
      target_id: target?.[1] ?? null,
      project_id: project ? projects[project] : null,
      details,
    })
  }
  const user = (key: UserKey): [AuditTargetType, string] => ['user', users[key]]
  const group = (key: GroupKey): [AuditTargetType, string] => ['group', GROUPS[key]]
  const admin = (rule: string, method = 'sso') => ({ rule, auth_method: method })
  const signIn = (at: number, key: UserKey, matchedBy = 'identity') => {
    entry(at, 'session.sign_in', key, user(key), {
      method: 'sso',
      session_id: nextId('b'),
      identity_id: identityOf[key]?.id ?? null,
      matched_by: matchedBy,
      auth_method: 'sso',
    })
  }

  // Bootstrap with the break-glass admin, before SSO was configured.
  const bootstrap = now - 430 * DAY
  entry(bootstrap, 'user.create', 'breakGlass', user('breakGlass'), {
    source: 'break_glass',
    is_platform_admin: true,
    external_id_kinds: [],
    auth_method: 'break_glass',
  })
  entry(bootstrap + 60_000, 'session.sign_in', 'breakGlass', user('breakGlass'), {
    method: 'break_glass',
    session_id: nextId('b'),
    auth_method: 'break_glass',
  })
  entry(bootstrap + 5 * 60_000, 'user.create', 'breakGlass', user('priya'), {
    ...admin('platform.manage_users', 'break_glass'),
    source: 'admin',
    is_platform_admin: true,
    external_id_kinds: ['employee_no', 'gitlab'],
  })
  for (const [index, key] of (
    ['innovationAdmins', 'innovationMembers', 'toolsMembers', 'viewers'] as const
  ).entries()) {
    const spec = GROUP_SPECS.find((g) => g.key === key)
    entry(bootstrap + (8 + index) * 60_000, 'group.create', 'breakGlass', group(key), {
      ...admin('platform.manage_groups', 'break_glass'),
      sync_mode: 'managed',
      idp_values: spec?.idp_values ?? [],
    })
  }
  entry(now - 420 * DAY, 'session.sign_in', 'priya', user('priya'), {
    method: 'sso',
    session_id: nextId('b'),
    identity_id: identityOf.priya?.id ?? null,
    matched_by: 'external_id',
    auth_method: 'sso',
  })
  entry(now - 420 * DAY + 1000, 'user.identity_link', 'priya', user('priya'), {
    identity_id: identityOf.priya?.id ?? null,
    matched_by: 'external_id',
    issuer: FIXTURE_ISSUER,
    auth_method: 'sso',
  })
  entry(now - 420 * DAY + 2000, 'user.groups_sync', 'priya', user('priya'), {
    added_group_ids: [GROUPS.innovationAdmins],
    removed_group_ids: [],
    claim_found: true,
    auth_method: 'sso',
  })

  // Day-to-day administration.
  entry(now - 60 * DAY, 'group.mapping_replace', 'priya', group('viewers'), {
    ...admin('platform.manage_groups'),
    from_sync_mode: 'managed',
    sync_mode: 'additive',
    from_idp_values: ['viewers'],
    idp_values: ['viewers'],
  })
  entry(now - 45 * DAY, 'group.create', 'priya', group('champions'), {
    ...admin('platform.manage_groups'),
    sync_mode: 'managed',
    idp_values: [],
  })
  entry(now - 45 * DAY + 60_000, 'group.member_add', 'priya', group('champions'), {
    ...admin('platform.manage_groups'),
    user_id: users.carol,
  })
  entry(now - 44 * DAY, 'group.member_add', 'priya', group('champions'), {
    ...admin('platform.manage_groups'),
    user_id: users.grace,
  })
  entry(
    now - 45 * DAY + 120_000,
    'project.group_grant_add',
    'carol',
    group('champions'),
    { ...admin('project.manage_members'), role: 'member' },
    'green',
  )
  entry(now - 30 * DAY, 'user.create', 'priya', user('ivan'), {
    ...admin('platform.manage_users'),
    source: 'admin',
    is_platform_admin: false,
    external_id_kinds: [],
  })
  entry(now - 29 * DAY, 'session.sign_in', 'ivan', user('ivan'), {
    method: 'sso',
    session_id: nextId('b'),
    identity_id: identityOf.ivan?.id ?? null,
    matched_by: 'email',
    auth_method: 'sso',
  })
  entry(now - 21 * DAY, 'user.create', 'priya', user('kofi'), {
    ...admin('platform.manage_users'),
    source: 'admin',
    is_platform_admin: false,
    external_id_kinds: ['employee_no'],
  })
  entry(now - 20 * DAY, 'session.sign_in', 'kofi', user('kofi'), {
    method: 'sso',
    session_id: nextId('b'),
    identity_id: identityOf.kofi?.id ?? null,
    matched_by: 'external_id',
    auth_method: 'sso',
  })
  entry(now - 20 * DAY + 1000, 'user.identity_link', 'kofi', user('kofi'), {
    identity_id: identityOf.kofi?.id ?? null,
    matched_by: 'external_id',
    issuer: FIXTURE_ISSUER,
    auth_method: 'sso',
  })
  entry(now - 20 * DAY + 2000, 'user.groups_sync', 'kofi', user('kofi'), {
    added_group_ids: [GROUPS.innovationMembers, GROUPS.toolsMembers],
    removed_group_ids: [],
    claim_found: true,
    auth_method: 'sso',
  })
  entry(
    now - 14 * DAY,
    'project.group_grant_add',
    'alice',
    group('toolsMembers'),
    { ...admin('project.manage_members'), role: 'member' },
    'tool',
  )
  entry(now - 12 * DAY, 'group.create', 'priya', group('contractors'), {
    ...admin('platform.manage_groups'),
    sync_mode: 'additive',
    idp_values: ['contractors', 'external/contractors'],
  })
  entry(now - 10 * DAY, 'user.update', 'priya', user('jonas'), {
    ...admin('platform.manage_users'),
    fields: ['is_active'],
    is_active: false,
    sessions_ended: 1,
  })
  entry(now - 9 * DAY, 'session.sign_in_denied', null, user('jonas'), {
    method: 'sso',
    reason: 'account_disabled',
    issuer: FIXTURE_ISSUER,
    subject: identityOf.jonas?.subject ?? null,
  })
  entry(now - 6 * DAY, 'user.groups_sync', 'farid', user('farid'), {
    added_group_ids: [GROUPS.toolsMembers],
    removed_group_ids: [],
    claim_found: true,
    auth_method: 'sso',
  })
  entry(now - 5 * DAY, 'user.create', 'priya', user('lena'), {
    ...admin('platform.manage_users'),
    source: 'admin',
    is_platform_admin: false,
    external_id_kinds: ['employee_no', 'gitlab'],
  })
  entry(now - 5 * DAY + 60_000, 'group.member_add', 'priya', group('toolsMembers'), {
    ...admin('platform.manage_groups'),
    user_id: users.lena,
  })
  entry(now - 4 * DAY, 'user.sessions_end', 'priya', user('bob'), {
    ...admin('platform.manage_users'),
    count: 2,
  })
  entry(now - 3 * DAY, 'user.external_ids_replace', 'priya', user('hannah'), {
    ...admin('platform.manage_users'),
    kinds: ['employee_no'],
  })
  entry(now - 3 * DAY + 3 * HOUR, 'session.sign_in_denied', null, null, {
    method: 'sso',
    reason: 'no_match',
    issuer: FIXTURE_ISSUER,
    subject: subject(90),
  })
  entry(now - 2 * DAY, 'session.sign_in_denied', null, null, {
    method: 'sso',
    reason: 'email_not_verified',
    issuer: FIXTURE_ISSUER,
    subject: subject(91),
  })
  entry(now - 2 * DAY + HOUR, 'session.sign_out', 'grace', user('grace'), {
    session_id: nextId('b'),
    method: 'sso',
    auth_method: 'sso',
  })
  // Shaped like the backend's: member changes target the user, with the project.
  entry(
    now - 26 * HOUR,
    'project.member_update',
    'priya',
    user('hannah'),
    { ...admin('project.manage_members'), from_role: 'viewer', role: 'member' },
    'cust',
  )

  // Recent sign-ins, one per linked person.
  for (const [key, , loginHours] of IDENTITIES) {
    if (key === 'jonas' || key === 'ivan') continue
    signIn(now - loginHours * HOUR, key)
  }

  // Phase 1 actions, from the ideas' activity.
  const ideaProject = new Map(db.ideas.map((idea) => [idea.id, idea.project_id]))
  for (const event of db.events) {
    const projectId = ideaProject.get(event.idea_id)
    if (!projectId || !event.actor_id) continue
    const action: AuditAction | null =
      event.type === 'status_changed'
        ? 'idea.status_change'
        : event.type === 'owner_changed'
          ? 'idea.owner_change'
          : event.type === 'evaluator_added'
            ? 'evaluator.add'
            : event.type === 'evaluator_removed'
              ? 'evaluator.remove'
              : event.type === 'evaluation_submitted'
                ? 'evaluation.submit'
                : event.type === 'evaluation_closed'
                  ? 'evaluation.close'
                  : event.type === 'evaluation_reopened'
                    ? 'evaluation.reopen'
                    : null
    if (!action) continue
    // As the backend records them: evaluator changes target the evaluator (the idea is
    // in details), everything else targets the idea.
    const evaluatorId = action.startsWith('evaluator.') ? event.payload.evaluator_id : undefined
    db.audit.push({
      id: nextId('b'),
      created_at: event.created_at,
      actor_id: event.actor_id,
      action,
      target_type: typeof evaluatorId === 'string' ? 'user' : 'idea',
      target_id: typeof evaluatorId === 'string' ? evaluatorId : event.idea_id,
      project_id: projectId,
      details:
        typeof evaluatorId === 'string'
          ? { rule: 'evaluator.manage', idea_id: event.idea_id, auth_method: 'sso' }
          : { ...event.payload, auth_method: 'sso' },
    })
  }

  db.audit.sort((a, b) => a.created_at.localeCompare(b.created_at) || a.id.localeCompare(b.id))
}
