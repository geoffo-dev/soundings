import { HttpResponse } from 'msw'

import { recordAudit } from '@/mocks/access'
import {
  MOCK_BREAK_GLASS_PASSWORD,
  MOCK_ISSUER,
  MOCK_BREAK_GLASS_USERNAME,
  mockAuthConfig,
} from '@/mocks/auth-config'
import { currentUser, findUser, isPickable } from '@/mocks/domain'
import {
  allowOnly,
  fail,
  failValidation,
  json,
  noContent,
  notFound,
  problemResponse,
  publicRoute,
  readJson,
  route,
} from '@/mocks/http'
import { endSession, sessionAuthMethod, startSession } from '@/mocks/session'

import { isUuid } from '@/mocks/handlers/common'

const BREAK_GLASS_WINDOW_MS = 15 * 60_000
const BREAK_GLASS_MAX_FAILURES = 5

function redirect(status: 302 | 303, location: string): Response {
  return new HttpResponse(null, { status, headers: { Location: location } })
}

export const authHandlers = [
  route('get', '/auth/me', ({ user }) => currentUser(user, sessionAuthMethod())),

  /** Contract-phase2 §3.1: which sign-in methods the login page offers. */
  publicRoute('get', '/auth/config', () => {
    const config = mockAuthConfig()
    return { sso: config.sso, dev_login: config.dev_login, break_glass: config.break_glass }
  }),

  publicRoute('get', '/auth/dev/users', ({ db }) => {
    if (!mockAuthConfig().dev_login) notFound()
    return db.users
      .filter(isPickable)
      .sort(
        (a, b) =>
          Number(b.is_platform_admin) - Number(a.is_platform_admin) ||
          a.display_name.localeCompare(b.display_name),
      )
      .map((user) => currentUser(user, null))
  }),

  publicRoute('post', '/auth/dev/login', async ({ request, db }) => {
    const body = await readJson(request)
    allowOnly(body, ['user_id'])
    if (!isUuid(body.user_id)) {
      failValidation([
        { loc: ['body', 'user_id'], msg: 'Input should be a valid UUID', type: 'uuid_parsing' },
      ])
    }
    if (!mockAuthConfig().dev_login) notFound()
    const user = findUser(db, body.user_id.toLowerCase())
    if (!isPickable(user)) {
      failValidation(
        [{ loc: ['body', 'user_id'], msg: 'Unknown or inactive user', type: 'user_not_found' }],
        'user_not_found',
      )
    }
    startSession(user.id, 'dev_login')
    recordAudit(db, user, 'session.sign_in', { type: 'user', id: user.id }, { method: 'dev_login' })
    return json(currentUser(user, 'dev_login'))
  }),

  publicRoute('post', '/auth/logout', ({ db, user }) => {
    if (user) {
      recordAudit(
        db,
        user,
        'session.sign_out',
        { type: 'user', id: user.id },
        {
          method: sessionAuthMethod(),
        },
      )
    }
    endSession()
    return noContent()
  }),

  /**
   * Browser navigations (never fetched by the SPA; the mock IdP in `mocks/sso.ts`
   * stands in for them in `dev:mock`). Here for completeness: a fetch gets the
   * same redirects the real API sends.
   */
  publicRoute('get', '/auth/login', ({ url }) => {
    if (!mockAuthConfig().sso) return redirect(302, '/login?error=sso_unavailable')
    const authorize = new URL(`${MOCK_ISSUER}/protocol/openid-connect/auth`)
    authorize.search = new URLSearchParams({
      response_type: 'code',
      client_id: 'soundings',
      redirect_uri: `${url.origin}/api/v1/auth/callback`,
      scope: 'openid profile email',
      state: 'mock-state',
      code_challenge_method: 'S256',
    }).toString()
    return redirect(302, authorize.toString())
  }),

  /** The mock keeps no login attempts, so a fetched callback is always `login_expired`. */
  publicRoute('get', '/auth/callback', ({ url }) => {
    if (!mockAuthConfig().sso) return redirect(302, '/login?error=sso_unavailable')
    const error = url.searchParams.get('error')
    if (error === 'access_denied') return redirect(302, '/login?error=login_cancelled')
    if (error) return redirect(302, '/login?error=sso_failed')
    return redirect(302, '/login?error=login_expired')
  }),

  publicRoute('post', '/auth/logout/redirect', ({ db, user }) => {
    if (user) {
      recordAudit(
        db,
        user,
        'session.sign_out',
        { type: 'user', id: user.id },
        {
          method: sessionAuthMethod(),
        },
      )
    }
    endSession()
    return redirect(303, '/login?signed_out=1')
  }),

  /** Contract-phase2 §3.8 (credentials in `mocks/auth-config.ts`). */
  publicRoute('post', '/auth/break-glass', async ({ request, db }) => {
    const body = await readJson(request)
    allowOnly(body, ['username', 'password'])
    const username = body.username
    const password = body.password
    for (const [field, value, max] of [
      ['username', username, 200],
      ['password', password, 1024],
    ] as const) {
      if (typeof value !== 'string' || value.length < 1 || value.length > max) {
        failValidation([
          { loc: ['body', field], msg: 'Field required', type: value ? 'string_type' : 'missing' },
        ])
      }
    }
    if (!mockAuthConfig().break_glass) notFound()
    const now = Date.now()
    db.breakGlassFailures = db.breakGlassFailures.filter((at) => now - at < BREAK_GLASS_WINDOW_MS)
    if (db.breakGlassFailures.length >= BREAK_GLASS_MAX_FAILURES) {
      const oldest = db.breakGlassFailures[0] ?? now
      const retryAfter = Math.max(1, Math.ceil((oldest + BREAK_GLASS_WINDOW_MS - now) / 1000))
      const response = problemResponse(
        429,
        'too_many_attempts',
        'Too many sign-in attempts. Try again later.',
      )
      response.headers.set('Retry-After', String(retryAfter))
      throw response
    }
    if (username !== MOCK_BREAK_GLASS_USERNAME || password !== MOCK_BREAK_GLASS_PASSWORD) {
      db.breakGlassFailures.push(now)
      recordAudit(db, null, 'session.sign_in_denied', null, {
        method: 'break_glass',
        reason: 'invalid_credentials',
      })
      fail(401, 'invalid_credentials', 'The username or password is wrong.')
    }
    const account = db.users.find((u) => u.is_break_glass)
    if (!account) notFound()
    if (!account.is_active) {
      recordAudit(
        db,
        null,
        'session.sign_in_denied',
        { type: 'user', id: account.id },
        {
          method: 'break_glass',
          reason: 'account_disabled',
        },
      )
      fail(403, 'account_disabled', 'The break-glass account is deactivated.')
    }
    account.is_platform_admin = true
    account.last_seen_at = new Date(now).toISOString()
    startSession(account.id, 'break_glass')
    db.sessions[account.id] = (db.sessions[account.id] ?? 0) + 1
    recordAudit(
      db,
      account,
      'session.sign_in',
      { type: 'user', id: account.id },
      {
        method: 'break_glass',
      },
    )
    return json(currentUser(account, 'break_glass'))
  }),
]
