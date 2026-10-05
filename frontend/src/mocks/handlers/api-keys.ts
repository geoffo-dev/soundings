/**
 * API keys (contract-phase5 §2 "Your API keys", "Admin settings → API keys",
 * §3.1): session-only key management. Check order for your keys: 401 → 422
 * (shape) → 403 (c20) → 404 → 422 business (`invalid_project`) → 409; admin
 * keys: 401 → 422 → 403 → 404.
 */
import type { ApiKeyScope, ApiKeyState } from '@/api/types'
import {
  adminApiKeyOut,
  API_KEY_LOOKUP_LENGTH,
  API_KEY_MAX_LIFETIME_MS,
  API_KEY_MIN_LIFETIME_MS,
  API_KEY_NAME_MAX_LENGTH,
  API_KEY_PREFIX,
  API_KEY_SCOPES,
  API_KEY_SECRET_LENGTH,
  apiKeyOut,
  canonicalScopes,
  keyPrefix,
  keyState,
  liveKeys,
  MAX_API_KEYS_PER_USER,
  MAX_KEY_PROJECTS,
  randomBase62,
  revokeKey,
  type MockApiKey,
} from '@/mocks/api-keys'
import { recordAudit } from '@/mocks/access'
import { ID_KIND, newId } from '@/mocks/db'
import { canViewProject, findUser, paginate } from '@/mocks/domain'
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
  queryText,
  queryUuid,
  readJson,
  route,
  type RouteContext,
} from '@/mocks/http'
import { sessionAuthMethod } from '@/mocks/session'

import { isUuid, uuidParam } from './common'

const STATES: ApiKeyState[] = ['active', 'expired', 'dormant']

function nameField(body: Record<string, unknown>): string {
  const value = body.name
  if (typeof value !== 'string') {
    failValidation([{ loc: ['body', 'name'], msg: 'Field required', type: 'missing' }])
  }
  const name = value.trim()
  if (!name || name.length > API_KEY_NAME_MAX_LENGTH) {
    failValidation([
      {
        loc: ['body', 'name'],
        msg: `String should have 1 to ${API_KEY_NAME_MAX_LENGTH} characters`,
        type: 'string_too_long',
      },
    ])
  }
  // SingleLine: no line breaks or other control characters.
  const control = Array.from({ length: name.length }, (_, i) => name.charCodeAt(i)).some(
    (code) => code < 0x20 || code === 0x7f || code === 0x2028 || code === 0x2029,
  )
  if (control) {
    failValidation([
      { loc: ['body', 'name'], msg: 'Must be a single line of text', type: 'value_error' },
    ])
  }
  return name
}

function scopesField(body: Record<string, unknown>): ApiKeyScope[] {
  const value = body.scopes
  if (
    !Array.isArray(value) ||
    value.length < 1 ||
    value.length > 4 ||
    !value.every((scope) => API_KEY_SCOPES.includes(scope as ApiKeyScope))
  ) {
    failValidation([
      {
        loc: ['body', 'scopes'],
        msg: 'Choose 1 to 4 of read, write, evaluate, mcp',
        type: 'value_error',
      },
    ])
  }
  return canonicalScopes(value as ApiKeyScope[])
}

function expiryField(body: Record<string, unknown>): string | null {
  const value = body.expires_at
  if (value === undefined || value === null) return null
  // An offset is required (AwareDatetime).
  if (typeof value !== 'string' || !/(Z|[+-]\d{2}:\d{2})$/.test(value)) {
    failValidation([
      {
        loc: ['body', 'expires_at'],
        msg: 'Input should have timezone info',
        type: 'timezone_aware',
      },
    ])
  }
  const at = Date.parse(value)
  const now = Date.now()
  if (
    Number.isNaN(at) ||
    at < now + API_KEY_MIN_LIFETIME_MS ||
    at > now + API_KEY_MAX_LIFETIME_MS
  ) {
    failValidation([
      {
        loc: ['body', 'expires_at'],
        msg: 'Value error, the expiry must be at least an hour and at most a year ahead',
        type: 'value_error',
      },
    ])
  }
  return new Date(at).toISOString()
}

function projectIdsField(body: Record<string, unknown>): string[] | null {
  const value = body.project_ids
  if (value === undefined || value === null) return null
  if (
    !Array.isArray(value) ||
    value.length < 1 ||
    value.length > MAX_KEY_PROJECTS ||
    !value.every(isUuid)
  ) {
    failValidation([
      {
        loc: ['body', 'project_ids'],
        msg: `Choose 1 to ${MAX_KEY_PROJECTS} projects`,
        type: 'value_error',
      },
    ])
  }
  return [...new Set(value.map((id) => id.toLowerCase()))]
}

function ownKey(ctx: RouteContext): MockApiKey {
  const id = uuidParam(ctx, 'keyId')
  const key = ctx.db.apiKeys.find((k) => k.id === id && k.user_id === ctx.user.id)
  if (!key) notFound('API key not found.')
  return key
}

function requirePlatformAdmin(ctx: RouteContext): void {
  if (!ctx.user.is_platform_admin) forbidden('forbidden', 'Only platform admins can do this.')
}

export const apiKeyHandlers = [
  route('get', '/me/api-keys', ({ db, user }) => {
    const items = liveKeys(db, user.id)
    return {
      items: items.map((key) => apiKeyOut(db, key)),
      max_keys: MAX_API_KEYS_PER_USER,
      can_create: !user.is_break_glass && items.length < MAX_API_KEYS_PER_USER,
    }
  }),

  route('post', '/me/api-keys', async (ctx) => {
    const body = await readJson(ctx.request)
    allowOnly(body, ['name', 'scopes', 'expires_at', 'project_ids'])
    const name = nameField(body)
    const scopes = scopesField(body)
    const expiresAt = expiryField(body)
    const projectIds = projectIdsField(body)
    const { db, user } = ctx
    // c20: a key would outlive the emergency (contract-phase5 §3.1).
    if (user.is_break_glass) {
      forbidden('break_glass_account', 'The break-glass account can’t create API keys.')
    }
    if (projectIds) {
      const ok = projectIds.every((id) => {
        const project = db.projects.find((p) => p.id === id)
        return project && canViewProject(db, project, user)
      })
      if (!ok) {
        failValidation(
          [
            {
              loc: ['body', 'project_ids'],
              msg: 'Choose projects you can view',
              type: 'invalid_project',
            },
          ],
          'invalid_project',
        )
      }
    }
    const live = liveKeys(db, user.id)
    if (live.length >= MAX_API_KEYS_PER_USER) {
      conflict('too_many_api_keys', 'You have 25 API keys. Revoke keys you no longer use.')
    }
    if (live.some((key) => key.name.toLowerCase() === name.toLowerCase())) {
      conflict('api_key_name_taken', 'You already have a key with this name.')
    }
    const lookup = randomBase62(API_KEY_LOOKUP_LENGTH)
    const secret = `${API_KEY_PREFIX}${lookup}_${randomBase62(API_KEY_SECRET_LENGTH)}`
    const key: MockApiKey = {
      id: newId(db, ID_KIND.phase5),
      user_id: user.id,
      name,
      lookup_id: lookup,
      scopes,
      project_ids: projectIds,
      expires_at: expiresAt,
      created_at: new Date().toISOString(),
      created_by_id: user.id,
      created_auth_method: sessionAuthMethod(),
      last_used_at: null,
      revoked_at: null,
      revoked_by_id: null,
    }
    db.apiKeys.push(key)
    recordAudit(
      db,
      user,
      'api_key.create',
      { type: 'user', id: user.id },
      {
        rule: 'api_key.manage_own',
        key_id: key.id,
        prefix: keyPrefix(key),
        scopes,
        restricted: projectIds !== null,
        project_ids: projectIds,
        expires_at: expiresAt,
      },
    )
    return created({ key: apiKeyOut(db, key), secret })
  }),

  route('delete', '/me/api-keys/:keyId', (ctx) => {
    const key = ownKey(ctx)
    revokeKey(ctx.db, key, ctx.user, 'api_key.manage_own')
    return noContent()
  }),

  route('get', '/admin/api-keys', (ctx) => {
    const q = queryText(ctx.url, 'q', 100)
    const userId = queryUuid(ctx.url, 'user_id')
    const [state] = queryEnum(ctx.url, 'state', STATES)
    const limit = queryLimit(ctx.url, 50, 200)
    requirePlatformAdmin(ctx)
    const { db } = ctx
    const needle = q?.toLowerCase() ?? ''
    const now = Date.now()
    const keys = liveKeys(db)
      .filter((key) => !userId || key.user_id === userId)
      .filter((key) => !state || keyState(db, key, now) === state)
      .filter((key) => {
        if (!q) return true
        // A prefix or lookup id matches exactly (a leaked key's), names and owners partly.
        if (q === keyPrefix(key) || q === key.lookup_id) return true
        const owner = findUser(db, key.user_id)
        return [key.name, owner?.display_name ?? '', owner?.email ?? ''].some((text) =>
          text.toLowerCase().includes(needle),
        )
      })
    const { page, next_cursor } = paginate(
      keys,
      ctx.url.searchParams.get('cursor'),
      limit,
      `admin-keys:${needle}:${userId ?? ''}:${state ?? ''}`,
    )
    return {
      items: page.map((key) => adminApiKeyOut(db, key)),
      next_cursor,
      total: keys.length,
    }
  }),

  route('delete', '/admin/api-keys/:keyId', (ctx) => {
    const id = uuidParam(ctx, 'keyId')
    requirePlatformAdmin(ctx)
    const key = ctx.db.apiKeys.find((k) => k.id === id)
    if (!key) notFound('API key not found.')
    revokeKey(ctx.db, key, ctx.user, 'api_key.manage_any')
    return noContent()
  }),
]
