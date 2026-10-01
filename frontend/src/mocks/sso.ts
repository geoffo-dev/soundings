/**
 * A stand-in for the IdP round trip in `npm run dev:mock`. MSW's service worker
 * never sees top-level navigations, so the SPA calls these instead of
 * navigating to `GET /api/v1/auth/login` and posting `/auth/logout/redirect`
 * when mocks are on (features/auth/sso.ts). Knobs: mocks/auth-config.ts.
 */
import {
  MOCK_SSO_ERROR_STORAGE_KEY,
  MOCK_SSO_USER_STORAGE_KEY,
  mockAuthConfig,
  readSetting,
} from './auth-config'
import { getDb, USERS } from './db'
import { findUser, isPickable } from './domain'
import { endSession, startSession } from './session'

/** Contract-phase2 §3.2 step 3: a same-origin SPA path, else `/`. */
export function safeNext(next: string | null | undefined): string {
  if (!next || !next.startsWith('/') || next.startsWith('//') || next.startsWith('/\\')) return '/'
  // eslint-disable-next-line no-control-regex -- rejecting control characters is the point
  if (/[\\\s\u0000-\u001f\u007f]/.test(next) || next.length > 2048) return '/'
  if (next === '/api' || next.startsWith('/api/')) return '/'
  return next
}

const IDP_ROUND_TRIP_MS = 350

function go(href: string): void {
  window.setTimeout(() => window.location.assign(href), IDP_ROUND_TRIP_MS)
}

/** `GET /auth/login?next=` → the IdP → `GET /auth/callback`, all in one step. */
export function mockSsoSignIn(next: string | null | undefined): void {
  go(mockSsoOutcome(next))
}

/** Where the round trip ends: the `next` path with a new SSO session, or /login?error=…. */
export function mockSsoOutcome(next: string | null | undefined): string {
  const target = safeNext(next)
  const failure = (code: string) =>
    `/login?error=${code}${target === '/' ? '' : `&next=${encodeURIComponent(target)}`}`
  if (!mockAuthConfig().sso) return '/login?error=sso_unavailable'
  const error = readSetting(MOCK_SSO_ERROR_STORAGE_KEY)
  if (error) return failure(error)
  const key = readSetting(MOCK_SSO_USER_STORAGE_KEY) ?? 'alice'
  const users: Partial<Record<string, string>> = USERS
  const user = findUser(getDb(), users[key] ?? USERS.alice)
  if (!user) return failure('no_account')
  // Deactivated, service and break-glass accounts are never matched (§3.3).
  if (!isPickable(user)) return failure('account_disabled')
  startSession(user.id, 'sso')
  return target
}

/** `POST /auth/logout/redirect`: ends the session; the mock IdP signs out at once. */
export function mockLogoutRedirect(): void {
  endSession()
  go('/login?signed_out=1')
}
