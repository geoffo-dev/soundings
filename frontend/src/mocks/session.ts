/**
 * The mock API's "session": which fixture user is signed in, and how. Kept in
 * cookies (like the real `soundings_session`, but readable by JS) so it
 * survives reloads, is shared by tabs and the /design iframe, and is cleared
 * together with the CSRF cookie.
 */
import { CSRF_COOKIE, readCookie } from '@/api/client'

export const MOCK_SESSION_COOKIE = 'soundings_mock_session'
/** `sso`, `break_glass` or `dev_login` (contract-phase2 §1); missing = `dev_login`. */
export const MOCK_AUTH_METHOD_COOKIE = 'soundings_mock_auth_method'

export type MockAuthMethod = 'sso' | 'break_glass' | 'dev_login'

const METHODS: readonly MockAuthMethod[] = ['sso', 'break_glass', 'dev_login']

function cookieJar(): { cookie: string } | null {
  return typeof document === 'undefined' ? null : document
}

export function sessionUserId(): string | null {
  const jar = cookieJar()
  return jar ? (readCookie(MOCK_SESSION_COOKIE, jar.cookie) ?? null) : null
}

/**
 * The method cookie as set at sign-in, or null for a session created without
 * one (Playwright's fixture cookies): such sessions work whatever is configured.
 */
export function storedAuthMethod(): MockAuthMethod | null {
  const jar = cookieJar()
  const value = jar ? readCookie(MOCK_AUTH_METHOD_COOKIE, jar.cookie) : undefined
  return METHODS.includes(value as MockAuthMethod) ? (value as MockAuthMethod) : null
}

/** How the current session signed in (the mock's `user_sessions.auth_method`). */
export function sessionAuthMethod(): MockAuthMethod {
  return storedAuthMethod() ?? 'dev_login'
}

export function csrfToken(): string | null {
  const jar = cookieJar()
  return jar ? (readCookie(CSRF_COOKIE, jar.cookie) ?? null) : null
}

/** Every sign-in: sets the session, its method and a fresh CSRF token, like the backend. */
export function startSession(userId: string, method: MockAuthMethod = 'dev_login'): void {
  const jar = cookieJar()
  if (!jar) return
  const token = Math.random().toString(36).slice(2) + Date.now().toString(36)
  jar.cookie = `${MOCK_SESSION_COOKIE}=${encodeURIComponent(userId)}; path=/; SameSite=Lax`
  jar.cookie = `${MOCK_AUTH_METHOD_COOKIE}=${method}; path=/; SameSite=Lax`
  jar.cookie = `${CSRF_COOKIE}=${token}; path=/; SameSite=Lax`
}

export function endSession(): void {
  const jar = cookieJar()
  if (!jar) return
  const expired = 'expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/; SameSite=Lax'
  jar.cookie = `${MOCK_SESSION_COOKIE}=; ${expired}`
  jar.cookie = `${MOCK_AUTH_METHOD_COOKIE}=; ${expired}`
  jar.cookie = `${CSRF_COOKIE}=; ${expired}`
}
