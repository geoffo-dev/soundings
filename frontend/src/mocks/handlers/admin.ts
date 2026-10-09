import type { AuditAction, AuditTargetType, GroupSyncMode } from '@/api/types'

import {
  adminUser,
  adminUserSummary,
  auditEntry,
  findGroup,
  groupDetail,
  groupMember,
  groupMembership,
  groupSummary,
  isSystemAccount,
  normaliseIdpValue,
  recordAudit,
  ssoConfig,
  testMapping,
} from '@/mocks/access'
import { revokeAllKeys } from '@/mocks/api-keys'
import { clearAssignment } from '@/mocks/researchers'
import { ID_KIND, newId, type MockDb, type MockUser } from '@/mocks/db'
import { findUser, isPickable, paginate } from '@/mocks/domain'
import {
  allowOnly,
  conflict,
  created,
  failValidation,
  forbidden,
  noContent,
  notFound,
  queryEnum,
  queryLimit,
  queryOptionalBool,
  queryText,
  queryUuid,
  readJson,
  route,
  stringField,
  type RouteContext,
} from '@/mocks/http'
import { endSession } from '@/mocks/session'

import { isUuid, uuidParam } from '@/mocks/handlers/common'

/**
 * Admin settings (contract-phase2 §2 "Admin"): users, groups, the mapping test,
 * the audit log and the SSO view. Platform admins only; check order 401 → 422
 * (shape) → 403 → 404 → 403 specific → 422 business → 409.
 */

const SYNC_MODES: GroupSyncMode[] = ['managed', 'additive']
const KIND = /^[a-z][a-z0-9_]{0,39}$/
const TARGET_TYPES: AuditTargetType[] = ['user', 'project', 'idea', 'group']
/** Every audit action (exhaustive: a new one fails the type check until it is listed). */
const AUDIT_ACTION_SET: Record<AuditAction, true> = {
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
const AUDIT_ACTIONS = Object.keys(AUDIT_ACTION_SET) as AuditAction[]

function requirePlatformAdmin(ctx: RouteContext): void {
  if (!ctx.user.is_platform_admin) forbidden('forbidden', 'Only platform admins can do this.')
}

function adminRoute(
  method: 'get' | 'post' | 'put' | 'patch' | 'delete',
  path: string,
  resolver: (ctx: RouteContext) => unknown,
) {
  return route(method, `/admin${path}`, resolver)
}

function userParam(ctx: RouteContext): MockUser {
  const id = uuidParam(ctx, 'userId')
  requirePlatformAdmin(ctx)
  const user = findUser(ctx.db, id)
  if (!user) notFound('User not found.')
  return user
}

function emailField(body: Record<string, unknown>, required: boolean): string | undefined {
  const email = stringField(body, 'email', { required, min: 3, max: 320 })
  if (email === undefined) return undefined
  if (!/^[^@\s]+@[^@\s]+$/.test(email)) {
    failValidation([
      { loc: ['body', 'email'], msg: 'Enter a valid email address', type: 'value_error' },
    ])
  }
  if (/\.invalid$/i.test(email)) {
    failValidation([
      {
        loc: ['body', 'email'],
        msg: 'Addresses under .invalid are reserved for system accounts',
        type: 'value_error',
      },
    ])
  }
  return email
}

function booleanField(body: Record<string, unknown>, field: string): boolean | undefined {
  const value = body[field]
  if (value === undefined || value === null) return undefined
  if (typeof value !== 'boolean') {
    failValidation([
      { loc: ['body', field], msg: 'Input should be a valid boolean', type: 'bool_type' },
    ])
  }
  return value
}

function externalIdsField(
  value: unknown,
  field = 'external_ids',
): { kind: string; value: string }[] {
  if (value === undefined || value === null) return []
  if (!Array.isArray(value) || value.length > 20) {
    failValidation([
      { loc: ['body', field], msg: 'A list of at most 20 external IDs', type: 'list_type' },
    ])
  }
  const kinds = new Set<string>()
  return value.map((raw: unknown, index) => {
    const item = (typeof raw === 'object' && raw !== null ? raw : {}) as Record<string, unknown>
    const kind = typeof item.kind === 'string' ? item.kind.trim() : ''
    const id = typeof item.value === 'string' ? item.value.trim() : ''
    if (!KIND.test(kind)) {
      failValidation([
        {
          loc: ['body', field, index, 'kind'],
          msg: 'Lower-case letters, digits and _, starting with a letter',
          type: 'string_pattern_mismatch',
        },
      ])
    }
    if (id.length < 1 || id.length > 200) {
      failValidation([
        {
          loc: ['body', field, index, 'value'],
          msg: 'Between 1 and 200 characters',
          type: 'string_too_long',
        },
      ])
    }
    if (kinds.has(kind)) {
      failValidation([
        {
          loc: ['body', field, index, 'kind'],
          msg: 'One external ID per kind',
          type: 'value_error',
        },
      ])
    }
    kinds.add(kind)
    return { kind, value: id }
  })
}

function ensureExternalIdsFree(
  db: MockDb,
  ids: { kind: string; value: string }[],
  userId: string | null,
): void {
  for (const { kind, value } of ids) {
    const taken = db.externalIds.some(
      (e) =>
        e.user_id !== userId && e.kind === kind && e.value.toLowerCase() === value.toLowerCase(),
    )
    if (taken) conflict('external_id_taken', `Another user has this ${kind}.`)
  }
}

function emailTaken(db: MockDb, email: string, userId: string | null): boolean {
  return db.users.some((u) => u.id !== userId && u.email.toLowerCase() === email.toLowerCase())
}

/** c18: another active platform admin besides `userId` and the break-glass account. */
function otherPlatformAdmins(db: MockDb, userId: string): number {
  return db.users.filter(
    (u) => u.id !== userId && u.is_active && u.is_platform_admin && !u.is_break_glass,
  ).length
}

function idpValuesField(value: unknown, field = 'idp_values'): string[] {
  if (value === undefined || value === null) return []
  if (!Array.isArray(value) || value.length > 50) {
    failValidation([
      { loc: ['body', field], msg: 'A list of at most 50 values', type: 'list_type' },
    ])
  }
  const values = new Set<string>()
  for (const [index, raw] of value.entries()) {
    const normalised = typeof raw === 'string' && raw.length <= 255 ? normaliseIdpValue(raw) : ''
    if (!normalised) {
      failValidation([
        {
          loc: ['body', field, index],
          msg: 'A group value from your identity provider, e.g. /innovation/members',
          type: 'value_error',
        },
      ])
    }
    values.add(normalised)
  }
  return [...values].sort()
}

function syncModeField(value: unknown, fallback?: GroupSyncMode): GroupSyncMode {
  if ((value === undefined || value === null) && fallback) return fallback
  if (!SYNC_MODES.includes(value as GroupSyncMode)) {
    failValidation([
      { loc: ['body', 'sync_mode'], msg: "Input should be 'managed' or 'additive'", type: 'enum' },
    ])
  }
  return value as GroupSyncMode
}

function groupNameTaken(db: MockDb, name: string, groupId: string | null): boolean {
  return db.groups.some((g) => g.id !== groupId && g.name.toLowerCase() === name.toLowerCase())
}

function groupParam(ctx: RouteContext) {
  const id = uuidParam(ctx, 'groupId')
  requirePlatformAdmin(ctx)
  const group = findGroup(ctx.db, id)
  if (!group) notFound('Group not found.')
  return group
}

const byDisplayName = (a: MockUser, b: MockUser) =>
  a.display_name.toLowerCase().localeCompare(b.display_name.toLowerCase()) ||
  a.id.localeCompare(b.id)

const USER_RULE = { rule: 'platform.manage_users' }
const GROUP_RULE = { rule: 'platform.manage_groups' }

export const adminHandlers = [
  /* ---------------------------------------------------------------- */
  /* Users (§3.4)                                                      */
  /* ---------------------------------------------------------------- */

  adminRoute('get', '/users', (ctx) => {
    const q = (queryText(ctx.url, 'q', 100) ?? '').toLowerCase()
    const active = queryOptionalBool(ctx.url, 'active')
    const platformAdmin = queryOptionalBool(ctx.url, 'platform_admin')
    const hasIdentity = queryOptionalBool(ctx.url, 'has_identity')
    const limit = queryLimit(ctx.url)
    requirePlatformAdmin(ctx)
    const { db } = ctx
    const users = db.users
      .filter(
        (u) => !q || u.display_name.toLowerCase().includes(q) || u.email.toLowerCase().includes(q),
      )
      .filter((u) => active === null || u.is_active === active)
      .filter((u) => platformAdmin === null || u.is_platform_admin === platformAdmin)
      .filter(
        (u) =>
          hasIdentity === null ||
          db.identities.some((identity) => identity.user_id === u.id) === hasIdentity,
      )
      .sort(byDisplayName)
    const { page, next_cursor } = paginate(
      users,
      ctx.url.searchParams.get('cursor'),
      limit,
      `admin-users:${q}:${String(active)}:${String(platformAdmin)}:${String(hasIdentity)}`,
    )
    return { items: page.map((u) => adminUserSummary(db, u)), next_cursor }
  }),

  adminRoute('post', '/users', async (ctx) => {
    const body = await readJson(ctx.request)
    allowOnly(body, ['email', 'display_name', 'is_platform_admin', 'external_ids'])
    const email = emailField(body, true) ?? ''
    const displayName = stringField(body, 'display_name', { required: true, max: 100 }) ?? ''
    const isPlatformAdmin = booleanField(body, 'is_platform_admin') ?? false
    const externalIds = externalIdsField(body.external_ids)
    requirePlatformAdmin(ctx)
    const { db } = ctx
    if (emailTaken(db, email, null)) conflict('email_taken', 'Another user has this email.')
    ensureExternalIdsFree(db, externalIds, null)
    const user: MockUser = {
      id: newId(db, ID_KIND.user),
      display_name: displayName,
      email,
      avatar_url: null,
      is_platform_admin: isPlatformAdmin,
      is_active: true,
      is_service_account: false,
      is_break_glass: false,
      created_at: new Date().toISOString(),
      last_seen_at: null,
    }
    db.users.push(user)
    for (const id of externalIds) db.externalIds.push({ user_id: user.id, ...id })
    recordAudit(
      db,
      ctx.user,
      'user.create',
      { type: 'user', id: user.id },
      {
        ...USER_RULE,
        source: 'admin',
        is_platform_admin: isPlatformAdmin,
        external_id_kinds: externalIds.map((e) => e.kind).sort(),
      },
    )
    return created(adminUser(db, user))
  }),

  adminRoute('get', '/users/:userId', (ctx) => adminUser(ctx.db, userParam(ctx))),

  adminRoute('patch', '/users/:userId', async (ctx) => {
    uuidParam(ctx, 'userId')
    const body = await readJson(ctx.request)
    allowOnly(body, ['display_name', 'email', 'is_active', 'is_platform_admin'])
    const displayName = stringField(body, 'display_name', { max: 100, min: 1 })
    const emailValue = body.email ?? undefined
    const isActive = booleanField(body, 'is_active')
    const isPlatformAdmin = booleanField(body, 'is_platform_admin')
    const user = userParam(ctx)
    const { db } = ctx
    // c17: not your own active or platform-admin flag.
    const self = user.id === ctx.user.id
    if (
      self &&
      ((isActive !== undefined && isActive !== user.is_active) ||
        (isPlatformAdmin !== undefined && isPlatformAdmin !== user.is_platform_admin))
    ) {
      forbidden(
        'cannot_change_self',
        'You can’t deactivate yourself or remove your own admin rights.',
      )
    }
    const email = emailValue === undefined ? undefined : emailField(body, false)
    const emailChanges = email !== undefined && email !== user.email
    const adminChanges = isPlatformAdmin !== undefined && isPlatformAdmin !== user.is_platform_admin
    if (isSystemAccount(user) && (emailChanges || adminChanges)) {
      conflict('system_account', 'System accounts keep their email and admin rights.')
    }
    if (email !== undefined && emailChanges && emailTaken(db, email, user.id)) {
      conflict('email_taken', 'Another user has this email.')
    }
    const losesAdmin =
      user.is_active &&
      user.is_platform_admin &&
      !user.is_break_glass &&
      (isPlatformAdmin === false || isActive === false)
    if (losesAdmin && otherPlatformAdmins(db, user.id) === 0) {
      conflict('last_platform_admin', 'Soundings needs at least one other platform admin.')
    }
    const fields: string[] = []
    const details: Record<string, unknown> = {}
    if (displayName !== undefined && displayName !== user.display_name) {
      user.display_name = displayName
      fields.push('display_name')
    }
    if (email !== undefined && emailChanges) {
      user.email = email
      fields.push('email')
    }
    if (isActive !== undefined && isActive !== user.is_active) {
      user.is_active = isActive
      fields.push('is_active')
      details.is_active = isActive
      if (!isActive) {
        details.sessions_ended = db.sessions[user.id] ?? 0
        db.sessions[user.id] = 0
      }
    }
    if (isPlatformAdmin !== undefined && adminChanges) {
      user.is_platform_admin = isPlatformAdmin
      fields.push('is_platform_admin')
      details.is_platform_admin = isPlatformAdmin
    }
    if (fields.length > 0) {
      recordAudit(
        db,
        ctx.user,
        'user.update',
        { type: 'user', id: user.id },
        {
          ...USER_RULE,
          fields,
          ...details,
        },
      )
    }
    // Deactivating revokes every key, each audited (contract-phase5 §2), after the update.
    if (isActive === false && fields.includes('is_active')) {
      revokeAllKeys(db, ctx.user, user)
      // Phase 8b (contract-phase8b §3.5): deactivation ends their research assignments.
      for (const idea of db.ideas) {
        if (idea.researcher_id === user.id) clearAssignment(db, idea, ctx.user, 'deactivated')
      }
    }
    return adminUser(db, user)
  }),

  adminRoute('put', '/users/:userId/external-ids', async (ctx) => {
    uuidParam(ctx, 'userId')
    const body = await readJson(ctx.request)
    allowOnly(body, ['external_ids'])
    if (!Array.isArray(body.external_ids)) {
      failValidation([{ loc: ['body', 'external_ids'], msg: 'Field required', type: 'missing' }])
    }
    const externalIds = externalIdsField(body.external_ids)
    const user = userParam(ctx)
    const { db } = ctx
    if (isSystemAccount(user)) {
      conflict('system_account', 'System accounts can’t have external IDs.')
    }
    ensureExternalIdsFree(db, externalIds, user.id)
    db.externalIds = db.externalIds.filter((e) => e.user_id !== user.id)
    for (const id of externalIds) db.externalIds.push({ user_id: user.id, ...id })
    recordAudit(
      db,
      ctx.user,
      'user.external_ids_replace',
      { type: 'user', id: user.id },
      {
        ...USER_RULE,
        kinds: externalIds.map((e) => e.kind).sort(),
      },
    )
    return adminUser(db, user)
  }),

  adminRoute('delete', '/users/:userId/identities/:identityId', (ctx) => {
    const identityId = uuidParam(ctx, 'identityId')
    const user = userParam(ctx)
    const { db } = ctx
    const identity = db.identities.find((i) => i.id === identityId && i.user_id === user.id)
    if (!identity) notFound('Identity not found.')
    db.identities.splice(db.identities.indexOf(identity), 1)
    // The mock doesn't track each session's method: treat them all as SSO sessions.
    const ended = db.sessions[user.id] ?? 0
    db.sessions[user.id] = 0
    recordAudit(
      db,
      ctx.user,
      'user.identity_unlink',
      { type: 'user', id: user.id },
      {
        ...USER_RULE,
        identity_id: identity.id,
        issuer: identity.issuer,
        sessions_ended: ended,
      },
    )
    if (user.id === ctx.user.id && ended > 0) endSession()
    return noContent()
  }),

  adminRoute('delete', '/users/:userId/sessions', (ctx) => {
    const user = userParam(ctx)
    const { db } = ctx
    const count = db.sessions[user.id] ?? 0
    db.sessions[user.id] = 0
    recordAudit(
      db,
      ctx.user,
      'user.sessions_end',
      { type: 'user', id: user.id },
      {
        ...USER_RULE,
        count,
      },
    )
    // Your own sessions too, this one included.
    if (user.id === ctx.user.id) endSession()
    return noContent()
  }),

  /* ---------------------------------------------------------------- */
  /* Groups (§3.5, §3.6, §3.12)                                        */
  /* ---------------------------------------------------------------- */

  adminRoute('get', '/groups', (ctx) => {
    const q = (queryText(ctx.url, 'q', 80) ?? '').toLowerCase()
    const limit = queryLimit(ctx.url)
    requirePlatformAdmin(ctx)
    const groups = ctx.db.groups
      .filter((group) => !q || group.name.toLowerCase().includes(q))
      .sort(
        (a, b) =>
          a.name.toLowerCase().localeCompare(b.name.toLowerCase()) || a.id.localeCompare(b.id),
      )
    const { page, next_cursor } = paginate(
      groups,
      ctx.url.searchParams.get('cursor'),
      limit,
      `admin-groups:${q}`,
    )
    return { items: page.map((group) => groupSummary(ctx.db, group)), next_cursor }
  }),

  adminRoute('post', '/groups', async (ctx) => {
    const body = await readJson(ctx.request)
    allowOnly(body, ['name', 'description', 'sync_mode', 'idp_values'])
    const name = stringField(body, 'name', { required: true, max: 80 }) ?? ''
    const description = stringField(body, 'description', { max: 500 }) ?? ''
    const syncMode = syncModeField(body.sync_mode, 'managed')
    const idpValues = idpValuesField(body.idp_values)
    requirePlatformAdmin(ctx)
    const { db } = ctx
    if (groupNameTaken(db, name, null)) conflict('group_name_taken', 'A group has this name.')
    const now = new Date().toISOString()
    const group = {
      id: newId(db, ID_KIND.group),
      name,
      description,
      sync_mode: syncMode,
      idp_values: idpValues,
      created_at: now,
      updated_at: now,
    }
    db.groups.push(group)
    recordAudit(
      db,
      ctx.user,
      'group.create',
      { type: 'group', id: group.id },
      {
        ...GROUP_RULE,
        sync_mode: syncMode,
        idp_values: idpValues,
      },
    )
    return created(groupDetail(db, group))
  }),

  adminRoute('post', '/groups/test-mapping', async (ctx) => {
    const body = await readJson(ctx.request)
    allowOnly(body, ['claims', 'user_id'])
    const claims = body.claims
    if (typeof claims !== 'object' || claims === null || Array.isArray(claims)) {
      failValidation([
        { loc: ['body', 'claims'], msg: 'Paste a JSON object of claims', type: 'dict_type' },
      ])
    }
    const userId = body.user_id ?? null
    if (userId !== null && !isUuid(userId)) {
      failValidation([
        { loc: ['body', 'user_id'], msg: 'Input should be a valid UUID', type: 'uuid_parsing' },
      ])
    }
    requirePlatformAdmin(ctx)
    const user = userId === null ? null : findUser(ctx.db, userId.toLowerCase())
    if (userId !== null && !user) {
      failValidation(
        [{ loc: ['body', 'user_id'], msg: 'Unknown user', type: 'user_not_found' }],
        'user_not_found',
      )
    }
    return testMapping(ctx.db, claims as Record<string, unknown>, user ?? null)
  }),

  adminRoute('get', '/groups/:groupId', (ctx) => groupDetail(ctx.db, groupParam(ctx))),

  adminRoute('patch', '/groups/:groupId', async (ctx) => {
    uuidParam(ctx, 'groupId')
    const body = await readJson(ctx.request)
    allowOnly(body, ['name', 'description'])
    const name = stringField(body, 'name', { max: 80, min: 1 })
    const description = stringField(body, 'description', { max: 500 })
    const group = groupParam(ctx)
    const { db } = ctx
    if (name !== undefined && groupNameTaken(db, name, group.id)) {
      conflict('group_name_taken', 'A group has this name.')
    }
    const fields: string[] = []
    if (name !== undefined && name !== group.name) {
      group.name = name
      fields.push('name')
    }
    if (description !== undefined && description !== group.description) {
      group.description = description
      fields.push('description')
    }
    if (fields.length > 0) {
      group.updated_at = new Date().toISOString()
      recordAudit(
        db,
        ctx.user,
        'group.update',
        { type: 'group', id: group.id },
        {
          ...GROUP_RULE,
          fields,
        },
      )
    }
    return groupDetail(db, group)
  }),

  adminRoute('delete', '/groups/:groupId', (ctx) => {
    const group = groupParam(ctx)
    const { db } = ctx
    const memberCount = groupDetail(db, group).member_count
    const projectIds = db.groupGrants
      .filter((g) => g.group_id === group.id)
      .map((g) => g.project_id)
    db.groups.splice(db.groups.indexOf(group), 1)
    db.groupMembers = db.groupMembers.filter((m) => m.group_id !== group.id)
    db.groupGrants = db.groupGrants.filter((g) => g.group_id !== group.id)
    recordAudit(
      db,
      ctx.user,
      'group.delete',
      { type: 'group', id: group.id },
      {
        ...GROUP_RULE,
        member_count: memberCount,
        project_ids: projectIds,
      },
    )
    return noContent()
  }),

  adminRoute('put', '/groups/:groupId/mapping', async (ctx) => {
    uuidParam(ctx, 'groupId')
    const body = await readJson(ctx.request)
    allowOnly(body, ['sync_mode', 'idp_values'])
    const syncMode = syncModeField(body.sync_mode)
    if (!Array.isArray(body.idp_values)) {
      failValidation([{ loc: ['body', 'idp_values'], msg: 'Field required', type: 'missing' }])
    }
    const idpValues = idpValuesField(body.idp_values)
    const group = groupParam(ctx)
    const changed =
      syncMode !== group.sync_mode || idpValues.join('\n') !== group.idp_values.join('\n')
    if (changed) {
      recordAudit(
        ctx.db,
        ctx.user,
        'group.mapping_replace',
        { type: 'group', id: group.id },
        {
          ...GROUP_RULE,
          from_sync_mode: group.sync_mode,
          sync_mode: syncMode,
          from_idp_values: group.idp_values,
          idp_values: idpValues,
        },
      )
      group.sync_mode = syncMode
      group.idp_values = idpValues
      group.updated_at = new Date().toISOString()
    }
    return groupDetail(ctx.db, group)
  }),

  adminRoute('get', '/groups/:groupId/members', (ctx) => {
    const q = (queryText(ctx.url, 'q', 100) ?? '').toLowerCase()
    const limit = queryLimit(ctx.url)
    const group = groupParam(ctx)
    const { db } = ctx
    const rows = db.groupMembers
      .filter((m) => m.group_id === group.id)
      .map((m) => ({ m, user: findUser(db, m.user_id) }))
      .filter((row): row is { m: (typeof row)['m']; user: MockUser } => row.user !== undefined)
      .filter(
        ({ user }) =>
          !q || user.display_name.toLowerCase().includes(q) || user.email.toLowerCase().includes(q),
      )
      .sort((a, b) => byDisplayName(a.user, b.user))
    const { page, next_cursor } = paginate(
      rows,
      ctx.url.searchParams.get('cursor'),
      limit,
      `group-members:${group.id}:${q}`,
    )
    return {
      items: page.map(({ m }) => groupMember(db, m)).filter((m) => m !== null),
      next_cursor,
    }
  }),

  adminRoute('post', '/groups/:groupId/members', async (ctx) => {
    uuidParam(ctx, 'groupId')
    const body = await readJson(ctx.request)
    allowOnly(body, ['user_id'])
    if (!isUuid(body.user_id)) {
      failValidation([
        { loc: ['body', 'user_id'], msg: 'Input should be a valid UUID', type: 'uuid_parsing' },
      ])
    }
    const group = groupParam(ctx)
    const { db } = ctx
    const user = findUser(db, body.user_id.toLowerCase())
    if (!isPickable(user)) {
      failValidation(
        [{ loc: ['body', 'user_id'], msg: 'Unknown or inactive user', type: 'user_not_found' }],
        'user_not_found',
      )
    }
    let membership = groupMembership(db, group.id, user.id)
    if (membership?.manual) conflict('already_member', 'Already a member of this group.')
    if (membership) membership.manual = true
    else {
      membership = {
        group_id: group.id,
        user_id: user.id,
        manual: true,
        synced: false,
        joined_at: new Date().toISOString(),
      }
      db.groupMembers.push(membership)
    }
    recordAudit(
      db,
      ctx.user,
      'group.member_add',
      { type: 'group', id: group.id },
      {
        ...GROUP_RULE,
        user_id: user.id,
      },
    )
    return created(groupMember(db, membership))
  }),

  adminRoute('delete', '/groups/:groupId/members/:userId', (ctx) => {
    const userId = uuidParam(ctx, 'userId')
    const group = groupParam(ctx)
    const { db } = ctx
    const membership = groupMembership(db, group.id, userId)
    if (!membership) notFound('Not a member of this group.')
    db.groupMembers.splice(db.groupMembers.indexOf(membership), 1)
    recordAudit(
      db,
      ctx.user,
      'group.member_remove',
      { type: 'group', id: group.id },
      {
        ...GROUP_RULE,
        user_id: userId,
        manual: membership.manual,
        synced: membership.synced,
      },
    )
    return noContent()
  }),

  /* ---------------------------------------------------------------- */
  /* Audit log (§3.11) and SSO (§3.10)                                 */
  /* ---------------------------------------------------------------- */

  adminRoute('get', '/audit', (ctx) => {
    const { url } = ctx
    const actorId = queryUuid(url, 'actor_id')
    const actions = queryEnum(url, 'action', AUDIT_ACTIONS)
    const [targetType] = queryEnum(url, 'target_type', TARGET_TYPES)
    const targetId = queryUuid(url, 'target_id')
    const projectId = queryUuid(url, 'project_id')
    const since = dateParam(url, 'since')
    const until = dateParam(url, 'until')
    const limit = queryLimit(url)
    requirePlatformAdmin(ctx)
    const entries = ctx.db.audit
      .filter((e) => !actorId || e.actor_id === actorId)
      .filter((e) => actions.length === 0 || actions.includes(e.action))
      .filter((e) => !targetType || e.target_type === targetType)
      .filter((e) => !targetId || e.target_id === targetId)
      .filter((e) => !projectId || e.project_id === projectId)
      .filter((e) => since === null || Date.parse(e.created_at) >= since)
      .filter((e) => until === null || Date.parse(e.created_at) < until)
      .reverse()
    const { page, next_cursor } = paginate(
      entries,
      url.searchParams.get('cursor'),
      limit,
      `audit:${url.searchParams.toString().replace(/(^|&)(cursor|limit)=[^&]*/g, '')}`,
    )
    return { items: page.map((e) => auditEntry(ctx.db, e)), next_cursor }
  }),

  adminRoute('get', '/sso', (ctx) => {
    requirePlatformAdmin(ctx)
    return ssoConfig(ctx.url.origin)
  }),
]

/** `since` / `until`: ISO date-times with a UTC offset (422 without one). */
function dateParam(url: URL, name: string): number | null {
  const value = url.searchParams.get(name)
  if (value === null || value === '') return null
  const parsed = Date.parse(value)
  if (Number.isNaN(parsed) || !/(Z|[+-]\d{2}:?\d{2})$/i.test(value)) {
    failValidation([
      {
        loc: ['query', name],
        msg: 'Input should be a date-time with a time zone',
        type: 'timezone_aware',
      },
    ])
  }
  return parsed
}
