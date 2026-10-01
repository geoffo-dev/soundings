import { createFileRoute, redirect } from '@tanstack/react-router'

import { LoginPage } from '@/features/auth/login-page'
import { optionalUser, safeNextPath } from '@/features/auth/session'
import { searchFlag, searchString } from '@/lib/search-params'

export interface LoginSearch {
  /** Where to go after signing in (a same-site path; anything else becomes /). */
  next?: string
  /** `/login?error=<code>` from the SSO flow (contract-phase2 §4.2). */
  error?: string
  /** `/login?signed_out=1` after "Sign out". */
  signed_out?: true
  /** `/login?expired=1` when a request found the session had ended. */
  expired?: true
}

export const Route = createFileRoute('/login')({
  validateSearch: (search: Record<string, unknown>): LoginSearch => ({
    next: searchString(search.next, 2000),
    error: searchString(search.error, 64),
    signed_out: searchFlag(search.signed_out),
    expired: searchFlag(search.expired),
  }),
  beforeLoad: async ({ context, search }) => {
    // Already signed in: go where they were heading. If the API is down,
    // show the page (it has its own error state).
    const user = await optionalUser(context.queryClient).catch(() => null)
    if (user) throw redirect({ href: safeNextPath(search.next), replace: true })
  },
  head: () => ({ meta: [{ title: 'Sign in · Soundings' }] }),
  component: LoginRoute,
})

function LoginRoute() {
  const search = Route.useSearch()
  return <LoginPage {...search} />
}
