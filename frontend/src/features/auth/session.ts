import type { QueryClient } from '@tanstack/react-query'
import { redirect, type AnyRouter, type ParsedLocation } from '@tanstack/react-router'

import { meQueryOptions } from '@/api/auth'
import { isApiError } from '@/api/errors'
import { queryKeys } from '@/api/keys'
import { retryIfCancelled, setUnauthorizedHandler } from '@/api/query'
import type { CurrentUser } from '@/api/types'
import { toast } from '@/components/ui/toaster'
import { clearDrafts } from '@/lib/drafts'

/**
 * Only same-site paths are allowed as `?next=` targets (no open redirects).
 * Returns "/" for anything else: other origins (`//host`, `/\host`, which browsers
 * read as `//host`), control characters, and the login page itself.
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
  if (url.origin !== window.location.origin || url.pathname.startsWith('/login')) return '/'
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
 * revoked, signed out in another tab): go to /login?next=<here> once, then
 * drop everything cached for the old session.
 */
export function installUnauthorizedHandler(router: AnyRouter, queryClient: QueryClient): void {
  let redirecting = false
  setUnauthorizedHandler(() => {
    const { location } = router.state
    if (redirecting || location.pathname === '/login') return
    redirecting = true
    // Forget the user first, so /login doesn't bounce straight back.
    queryClient.removeQueries({ queryKey: queryKeys.auth.me() })
    toast.info('Your session has ended', {
      id: 'session-ended',
      description: 'Sign in again to carry on where you left off.',
    })
    // Unsent drafts belong to the session that ended (ASVS 8.2.3).
    clearDrafts()
    void router
      .navigate({
        to: '/login',
        search: { next: location.href },
        replace: true,
        // Nothing can be saved any more, so unsaved-changes guards don't ask.
        ignoreBlocker: true,
      })
      .finally(() => {
        queryClient.clear()
        redirecting = false
      })
  })
}
