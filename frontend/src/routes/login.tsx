import { createFileRoute, redirect } from '@tanstack/react-router'

import { LoginPage } from '@/features/auth/login-page'
import { optionalUser, safeNextPath } from '@/features/auth/session'
import { searchString } from '@/lib/search-params'

export const Route = createFileRoute('/login')({
  validateSearch: (search: Record<string, unknown>): { next?: string } => ({
    next: searchString(search.next, 2000),
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
  const { next } = Route.useSearch()
  return <LoginPage next={next} />
}
