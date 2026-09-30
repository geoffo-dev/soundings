/**
 * The mock API's "session": which fixture user is signed in. Kept in a
 * cookie (like the real `soundings_session`, but readable by JS) so it
 * survives reloads, is shared by tabs and the /design iframe, and is cleared
 * together with the CSRF cookie.
 */
import { CSRF_COOKIE, readCookie } from '@/api/client'

export const MOCK_SESSION_COOKIE = 'soundings_mock_session'

function cookieJar(): { cookie: string } | null {
  return typeof document === 'undefined' ? null : document
}

export function sessionUserId(): string | null {
  const jar = cookieJar()
  return jar ? (readCookie(MOCK_SESSION_COOKIE, jar.cookie) ?? null) : null
}

export function csrfToken(): string | null {
  const jar = cookieJar()
  return jar ? (readCookie(CSRF_COOKIE, jar.cookie) ?? null) : null
}

/** dev_login: sets the session and a fresh CSRF token, like the backend. */
export function startSession(userId: string): void {
  const jar = cookieJar()
  if (!jar) return
  const token = Math.random().toString(36).slice(2) + Date.now().toString(36)
  jar.cookie = `${MOCK_SESSION_COOKIE}=${encodeURIComponent(userId)}; path=/; SameSite=Lax`
  jar.cookie = `${CSRF_COOKIE}=${token}; path=/; SameSite=Lax`
}

export function endSession(): void {
  const jar = cookieJar()
  if (!jar) return
  const expired = 'expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/; SameSite=Lax'
  jar.cookie = `${MOCK_SESSION_COOKIE}=; ${expired}`
  jar.cookie = `${CSRF_COOKIE}=; ${expired}`
}
