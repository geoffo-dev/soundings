import type { QueryClient } from '@tanstack/react-query'
import { redirect, type AnyRouter, type ParsedLocation } from '@tanstack/react-router'

import { meQueryOptions } from '@/api/auth'
import { isApiError } from '@/api/errors'
import { queryKeys } from '@/api/keys'
import { retryIfCancelled, setUnauthorizedHandler } from '@/api/query'
import type { CurrentUser } from '@/api/types'
import { clearDrafts } from '@/lib/drafts'

/**
 * Only same-site paths are allowed as `?next=` targets (no open redirects).
 * Returns "/" for anything else: other origins (`//host`, `/\host`, which browsers
 * read as `//host`), control characters, the login page itself, and API paths
 * (the server refuses those as `next` too: contract-phase2 §3.2). Paths with
 * `.`/`..` segments or an empty segment (`//`), even encoded, are refused too:
 * `/..//host` resolves to `//host` after another hop (review N1).
 */
export function safeNextPath(next: unknown): string {
  if (typeof next !== 'string' || !next.startsWith('/') || next.startsWith('//')) return '/'
  // eslint-disable-next-line no-control-regex -- rejecting control characters is the point
  if (/[\\\u0000-\u001f\u007f]/.test(next)) return '/'
  let url: URL
  try {
    url = new URL(next, window.location.origin)
  } catch {
    return '/'
  }
  if (url.origin !== window.location.origin) return '/'
  let path: string
  let raw: string
  try {
    path = decodeURIComponent(url.pathname)
    // The path as written (the URL parser has already resolved dot segments).
    raw = decodeURIComponent(next.split(/[?#]/, 1)[0] ?? '')
  } catch {
    return '/'
  }
  if (raw.includes('//') || raw.split('/').some((segment) => segment === '.' || segment === '..')) {
    return '/'
  }
  if (path.startsWith('/login') || /^\/api(\/|$)/.test(path)) return '/'
  return next
}

/**
 * The auth guard for signed-in routes (`beforeLoad` of routes/_app.tsx): loads
 * the current user (cached) or redirects to /login?next=<this page>.
 */
export async function requireUser(
  queryClient: QueryClient,
  location: ParsedLocation,
): Promise<CurrentUser> {
  try {
    return await retryIfCancelled(() =>
      queryClient.query({ ...meQueryOptions(), staleTime: 'static' }),
    )
  } catch (error) {
    if (isApiError(error) && error.status === 401) {
      throw redirect({ to: '/login', search: { next: location.href }, replace: true })
    }
    throw error
  }
}

/** For the login page: the signed-in user, or null (never throws on 401). */
export async function optionalUser(queryClient: QueryClient): Promise<CurrentUser | null> {
  try {
    return await queryClient.query({ ...meQueryOptions(), staleTime: 'static' })
  } catch (error) {
    if (isApiError(error) && error.status === 401) return null
    throw error
  }
}

/**
 * A 401 from any request after sign-in means the session ended (expired,
 * revoked, signed out in another tab, its sign-in method switched off): go to
 * /login?next=<here>&expired=1 once (the page says so, calmly), then drop
 * everything cached for the old session.
 */
export function installUnauthorizedHandler(router: AnyRouter, queryClient: QueryClient): void {
  let redirecting = false
  setUnauthorizedHandler(() => {
    const { location } = router.state
    if (redirecting || location.pathname === '/login') return
    redirecting = true
    // Forget the user first, so /login doesn't bounce straight back.
    queryClient.removeQueries({ queryKey: queryKeys.auth.me() })
    // Unsent drafts belong to the session that ended (ASVS 8.2.3).
    clearDrafts()
    void router
      .navigate({
        to: '/login',
        search: { next: location.href, expired: true },
        replace: true,
        // Nothing can be saved any more, so unsaved-changes guards don't ask.
        ignoreBlocker: true,
      })
      .finally(() => {
        // Everything but the sign-in page's own (public) queries, which are
        // already loading there: removing those would leave it pending forever.
        queryClient.removeQueries({ predicate: (query) => !isSignInQuery(query.queryKey) })
        redirecting = false
      })
  })
}

/** The login page's queries: public, and the same for every session. */
function isSignInQuery(key: readonly unknown[]): boolean {
  const config = queryKeys.auth.config()
  const devUsers = queryKeys.auth.devUsers()
  return key[0] === config[0] && (key[1] === config[1] || key[1] === devUsers[1])
}
