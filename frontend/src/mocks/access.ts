/**
 * Business rules of the mock API for Phase 2 (docs/api/contract-phase2.md):
 * IdP value normalisation and claim extraction (§3.5), the mapping test (§3.6,
 * §3.12), role sources (§3.7), the admin views of users and groups (§3.4,
 * §3.5), the SSO view (§3.10) and the audit log (§3.11). Like domain.ts, it
 * follows the contract closely enough for UI work; the backend is the authority.
 */
import type {
  AdminUser,
  AdminUserSummary,
  AuditAction,
  AuditEntry,
  AuditTargetType,
  Group,
  GroupMember,
  GroupSearchResult,
  GroupSummary,
  MappingTestGroup,
  MappingTestResult,
  ProjectAccessEntry,
  ProjectGroupGrant,
  ProjectRole,
  RoleSource,
  SsoConfig,
  UserProjectRole,
} from '@/api/types'

import {
  MOCK_ISSUER,
  mockAuthConfig,
  mockDiscoveryStatus,
  type MockAuthConfig,
} from './auth-config'
import {
  ID_KIND,
  newId,
  type MockDb,
  type MockGroup,
  type MockGroupMember,
  type MockUser,
} from './db'
import {
  directRole,
  findUser,
  higherRole,
  initialsFor,
  projectRef,
  userRef,
  userRefById,
} from './domain'
import { sessionAuthMethod } from './session'

/** The groups claim the mock instance is configured with (`SOUNDINGS_OIDC_GROUPS_CLAIM`). */
export const MOCK_GROUPS_CLAIM = 'groups'

/* ------------------------------------------------------------------ */
/* IdP values and the groups claim (§3.5)                              */
/* ------------------------------------------------------------------ */

/** Trim, strip `/` at both ends, trim again, lower-case: `/Innovation/Admins` → `innovation/admins`. */
export function normaliseIdpValue(value: string): string {
  return value
    .trim()
    .replace(/^\/+|\/+$/g, '')
    .trim()
    .toLowerCase()
}

export interface ExtractedGroups {
  claim_found: boolean
  values: string[]
  ignored_count: number
}

/** Extraction of the configured groups claim from a claim set (§3.5 steps 1–4). */
export function extractGroupValues(claims: Record<string, unknown>, path: string): ExtractedGroups {
  let value: unknown
  let found = false
  if (Object.prototype.hasOwnProperty.call(claims, path)) {
    value = claims[path]
    found = true
  } else {
    let node: unknown = claims
    found = true
    for (const segment of path.split('.')) {
      if (typeof node !== 'object' || node === null || Array.isArray(node)) {
        found = false
        break
      }
      if (!Object.prototype.hasOwnProperty.call(node, segment)) {
        found = false
        break
      }
      node = (node as Record<string, unknown>)[segment]
    }
    value = found ? node : undefined
  }
  if (!found || value === null || value === undefined) {
    return { claim_found: found && value !== undefined, values: [], ignored_count: 0 }
  }
  let elements: unknown[]
  let ignored = 0
  if (Array.isArray(value)) elements = value.slice(0, 1000)
  else if (typeof value === 'string') elements = [value]
  else return { claim_found: true, values: [], ignored_count: 1 }
  const values = new Set<string>()
  for (const element of elements) {
    if (typeof element !== 'string') {
      ignored += 1
      continue
    }
    const normalised = normaliseIdpValue(element)
    if (!normalised) {
      ignored += 1
      continue
    }
    values.add(normalised)
  }
  return { claim_found: true, values: [...values].sort(), ignored_count: ignored }
}

/* ------------------------------------------------------------------ */
/* Groups                                                              */
/* ------------------------------------------------------------------ */

export function findGroup(db: MockDb, id: string): MockGroup | undefined {
  return db.groups.find((group) => group.id === id)
}

export function groupMembership(
  db: MockDb,
  groupId: string,
  userId: string,
): MockGroupMember | undefined {
  return db.groupMembers.find((m) => m.group_id === groupId && m.user_id === userId)
}

const byName = (a: { name: string }, b: { name: string }) =>
  a.name.localeCompare(b.name, 'en', { sensitivity: 'base' })

function activeMembers(db: MockDb, groupId: string): MockGroupMember[] {
  return db.groupMembers.filter(
    (m) => m.group_id === groupId && findUser(db, m.user_id)?.is_active === true,
  )
}

export function groupSearchResult(db: MockDb, group: MockGroup): GroupSearchResult {
  return {
    id: group.id,
    name: group.name,
    description: group.description,
    member_count: activeMembers(db, group.id).length,
  }
}

export function groupSummary(db: MockDb, group: MockGroup): GroupSummary {
  return {
    id: group.id,
    name: group.name,
    description: group.description,
    sync_mode: group.sync_mode,
    idp_values: [...group.idp_values],
    member_count: activeMembers(db, group.id).length,
    project_count: db.groupGrants.filter((grant) => grant.group_id === group.id).length,
    created_at: group.created_at,
    updated_at: group.updated_at,
  }
}

export function groupDetail(db: MockDb, group: MockGroup): Group {
  const members = activeMembers(db, group.id)
  return {
    ...groupSummary(db, group),
    manual_member_count: members.filter((m) => m.manual).length,
    synced_member_count: members.filter((m) => m.synced).length,
    project_grants: db.groupGrants
      .filter((grant) => grant.group_id === group.id)
      .map((grant) => {
        const project = db.projects.find((p) => p.id === grant.project_id)
        return project ? { project: projectRef(project), role: grant.role } : null
      })
      .filter((grant) => grant !== null)
      .sort((a, b) => byName(a.project, b.project)),
  }
}

export function groupMember(db: MockDb, membership: MockGroupMember): GroupMember | null {
  const user = findUser(db, membership.user_id)
  if (!user) return null
  return {
    user: userRef(user),
    email: user.email,
    is_active: user.is_active,
    manual: membership.manual,
    synced: membership.synced,
    joined_at: membership.joined_at,
  }
}

/* ------------------------------------------------------------------ */
/* Roles and their sources (§3.7)                                      */
/* ------------------------------------------------------------------ */

/** Direct first, then each granting group by name. */
export function roleSources(db: MockDb, projectId: string, userId: string): RoleSource[] {
  const sources: RoleSource[] = []
  const direct = directRole(db, projectId, userId)
  if (direct) sources.push({ kind: 'direct', role: direct, group: null })
  const groups = db.groupGrants
    .filter((grant) => grant.project_id === projectId)
    .map((grant) => ({ grant, group: findGroup(db, grant.group_id) }))
    .filter(
      (item): item is { grant: (typeof db.groupGrants)[number]; group: MockGroup } =>
        item.group !== undefined && groupMembership(db, item.grant.group_id, userId) !== undefined,
    )
    .sort((a, b) => byName(a.group, b.group))
  for (const { grant, group } of groups) {
    sources.push({ kind: 'group', role: grant.role, group: { id: group.id, name: group.name } })
  }
  return sources
}

function highest(sources: RoleSource[]): ProjectRole | null {
  return sources.reduce<ProjectRole | null>((role, source) => higherRole(role, source.role), null)
}

/** Every project where the user has an effective role, with its sources, by project name. */
export function userProjectRoles(db: MockDb, userId: string): UserProjectRole[] {
  return db.projects
    .map((project) => {
      const sources = roleSources(db, project.id, userId)
      const role = highest(sources)
      return role ? { project: projectRef(project), role, sources } : null
    })
    .filter((entry) => entry !== null)
    .sort((a, b) => byName(a.project, b.project))
}

export function accessEntry(db: MockDb, projectId: string, user: MockUser): ProjectAccessEntry {
  const sources = roleSources(db, projectId, user.id)
  return {
    user: userRef(user),
    email: user.email,
    role: highest(sources) ?? 'viewer',
    sources,
  }
}

export function projectGroupGrant(
  db: MockDb,
  grant: (typeof db.groupGrants)[number],
): ProjectGroupGrant | null {
  const group = findGroup(db, grant.group_id)
  if (!group) return null
  return { group: groupSearchResult(db, group), role: grant.role, granted_at: grant.granted_at }
}

/** Admins first, then by group name. */
export function projectGroupGrants(db: MockDb, projectId: string): ProjectGroupGrant[] {
  return db.groupGrants
    .filter((grant) => grant.project_id === projectId)
    .map((grant) => projectGroupGrant(db, grant))
    .filter((grant) => grant !== null)
    .sort(
      (a, b) => Number(b.role === 'admin') - Number(a.role === 'admin') || byName(a.group, b.group),
    )
}

/* ------------------------------------------------------------------ */
/* Users (§3.4)                                                        */
/* ------------------------------------------------------------------ */

export function adminUserSummary(db: MockDb, user: MockUser): AdminUserSummary {
  return {
    id: user.id,
    display_name: user.display_name,
    avatar_url: user.avatar_url,
    initials: initialsFor(user.display_name),
    email: user.email,
    is_active: user.is_active,
    is_platform_admin: user.is_platform_admin,
    is_service_account: user.is_service_account,
    is_break_glass: user.is_break_glass,
    has_identity: db.identities.some((identity) => identity.user_id === user.id),
    created_at: user.created_at,
    last_seen_at: user.last_seen_at,
  }
}

export function adminUser(db: MockDb, user: MockUser): AdminUser {
  return {
    ...adminUserSummary(db, user),
    identities: db.identities
      .filter((identity) => identity.user_id === user.id)
      .map(({ id, issuer, subject, linked_at, last_login_at }) => ({
        id,
        issuer,
        subject,
        linked_at,
        last_login_at,
      })),
    external_ids: db.externalIds
      .filter((externalId) => externalId.user_id === user.id)
      .map(({ kind, value }) => ({ kind, value }))
      .sort((a, b) => a.kind.localeCompare(b.kind)),
    groups: db.groupMembers
      .filter((m) => m.user_id === user.id)
      .map((m) => {
        const group = findGroup(db, m.group_id)
        return group
          ? { group: { id: group.id, name: group.name }, manual: m.manual, synced: m.synced }
          : null
      })
      .filter((m) => m !== null)
      .sort((a, b) => byName(a.group, b.group)),
    project_roles: userProjectRoles(db, user.id),
    active_session_count: db.sessions[user.id] ?? 0,
  }
}

/** System accounts: service accounts and the break-glass admin. */
export function isSystemAccount(user: MockUser): boolean {
  return user.is_service_account || user.is_break_glass
}

/* ------------------------------------------------------------------ */
/* The mapping test (§3.12)                                            */
/* ------------------------------------------------------------------ */

export function testMapping(
  db: MockDb,
  claims: Record<string, unknown>,
  user: MockUser | null,
  groupsClaim: string | null = MOCK_GROUPS_CLAIM,
): MappingTestResult {
  const extracted = groupsClaim
    ? extractGroupValues(claims, groupsClaim)
    : { claim_found: false, values: [], ignored_count: 0 }
  const values = new Set(extracted.values)
  const results: MappingTestGroup[] = []
  // The user's memberships after the simulated sync: groupId → still a member?
  const after = new Map<string, boolean>()
  if (user) {
    for (const m of db.groupMembers) if (m.user_id === user.id) after.set(m.group_id, true)
  }
  for (const group of [...db.groups].sort(byName)) {
    const matched = group.idp_values.filter((value) => values.has(value))
    const membership = user ? groupMembership(db, group.id, user.id) : undefined
    const manual = membership?.manual ?? false
    if (matched.length > 0) {
      results.push({
        group: { id: group.id, name: group.name },
        sync_mode: group.sync_mode,
        matched_values: matched,
        manual,
        effect: membership?.synced ? 'keep' : 'add',
      })
      after.set(group.id, true)
    } else if (membership?.synced) {
      const remove = group.sync_mode === 'managed'
      results.push({
        group: { id: group.id, name: group.name },
        sync_mode: group.sync_mode,
        matched_values: [],
        manual,
        effect: remove ? 'remove' : 'keep',
      })
      if (remove && !manual) after.delete(group.id)
    }
  }
  const project_roles: UserProjectRole[] = []
  for (const project of db.projects) {
    const sources: RoleSource[] = []
    const direct = user ? directRole(db, project.id, user.id) : null
    if (direct) sources.push({ kind: 'direct', role: direct, group: null })
    const grants = db.groupGrants
      .filter((grant) => grant.project_id === project.id && after.get(grant.group_id))
      .flatMap((grant) => {
        const group = findGroup(db, grant.group_id)
        return group ? [{ grant, group }] : []
      })
      .sort((a, b) => byName(a.group, b.group))
    for (const { grant, group } of grants) {
      sources.push({ kind: 'group', role: grant.role, group: { id: group.id, name: group.name } })
    }
    const role = highest(sources)
    if (role) project_roles.push({ project: projectRef(project), role, sources })
  }
  project_roles.sort((a, b) => byName(a.project, b.project))
  return {
    groups_claim: groupsClaim,
    claim_found: extracted.claim_found,
    values: extracted.values,
    ignored_count: extracted.ignored_count,
    groups: results,
    project_roles,
  }
}

/* ------------------------------------------------------------------ */
/* SSO view (§3.10)                                                    */
/* ------------------------------------------------------------------ */

export function ssoConfig(
  origin: string,
  config: MockAuthConfig = mockAuthConfig(),
  now = Date.now(),
): SsoConfig {
  const bases = [origin, 'https://ideas.example.com']
  return {
    enabled: config.sso,
    issuer: config.sso ? MOCK_ISSUER : null,
    client_id: config.sso ? 'soundings' : '',
    client_secret_set: config.sso,
    scopes: ['openid', 'profile', 'email'],
    groups_claim: MOCK_GROUPS_CLAIM,
    external_id_claim: 'employee_no',
    external_id_kind: 'employee_no',
    match_verified_email: true,
    auto_create_users: false,
    dev_login: config.dev_login,
    redirect_uris: bases.map((base) => ({
      base_url: base,
      redirect_uri: `${base}/api/v1/auth/callback`,
      post_logout_redirect_uri: `${base}/login?signed_out=1`,
    })),
    discovery: config.sso
      ? {
          status: mockDiscoveryStatus(),
          end_session_supported: mockDiscoveryStatus() === 'ok',
          checked_at: new Date(now - 4 * 60_000).toISOString(),
        }
      : null,
    break_glass: {
      enabled: config.break_glass_enabled,
      credentials_set: config.break_glass_enabled,
      available: config.break_glass,
    },
  }
}

/* ------------------------------------------------------------------ */
/* Audit log (§3.11)                                                   */
/* ------------------------------------------------------------------ */

/**
 * Appends an audit entry for the signed-in user (`details.auth_method` is the
 * session's method; admin actions pass their `rule`).
 */
export function recordAudit(
  db: MockDb,
  actor: MockUser | null,
  action: AuditAction,
  target: { type: AuditTargetType; id: string } | null,
  details: Record<string, unknown> = {},
  projectId: string | null = null,
): void {
  db.audit.push({
    id: newId(db, ID_KIND.audit),
    created_at: new Date().toISOString(),
    actor_id: actor?.id ?? null,
    action,
    target_type: target?.type ?? null,
    target_id: target?.id ?? null,
    project_id: projectId,
    details: actor ? { ...details, auth_method: sessionAuthMethod() } : details,
  })
}

export function auditEntry(db: MockDb, entry: MockDb['audit'][number]): AuditEntry {
  const project = entry.project_id ? db.projects.find((p) => p.id === entry.project_id) : undefined
  return {
    id: entry.id,
    created_at: entry.created_at,
    action: entry.action,
    actor_id: entry.actor_id,
    actor: userRefById(db, entry.actor_id),
    target_type: entry.target_type,
    target_id: entry.target_id,
    target_label: targetLabel(db, entry.target_type, entry.target_id),
    project: project ? projectRef(project) : null,
    details: entry.details,
  }
}

function targetLabel(db: MockDb, type: AuditTargetType | null, id: string | null): string | null {
  if (!type || !id) return null
  if (type === 'user') return findUser(db, id)?.display_name ?? null
  if (type === 'group') return findGroup(db, id)?.name ?? null
  if (type === 'project') return db.projects.find((p) => p.id === id)?.name ?? null
  const idea = db.ideas.find((i) => i.id === id)
  if (!idea) return null
  const project = db.projects.find((p) => p.id === idea.project_id)
  return project ? `${project.key}-${idea.number}` : null
}
