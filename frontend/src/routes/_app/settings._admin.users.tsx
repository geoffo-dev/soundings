import { createFileRoute, Outlet } from '@tanstack/react-router'

import { UsersPage } from '@/features/admin/users/users-page'
import { validateUsersSearch } from '@/features/admin/users/users-search'

/** /settings/users?q=&status=&admins=1&unlinked=1 — the user sheet is the child route. */
export const Route = createFileRoute('/_app/settings/_admin/users')({
  validateSearch: validateUsersSearch,
  // A loader crumb (not staticData): it is only shown once the admin check passed.
  loader: () => ({ crumb: 'Users' }),
  head: () => ({ meta: [{ title: 'Users · Admin · Soundings' }] }),
  component: UsersRoute,
})

function UsersRoute() {
  const search = Route.useSearch()
  const navigate = Route.useNavigate()
  return (
    <UsersPage
      search={search}
      onSearchChange={(patch) =>
        void navigate({ search: (prev) => ({ ...prev, ...patch }), replace: true })
      }
    >
      <Outlet />
    </UsersPage>
  )
}
