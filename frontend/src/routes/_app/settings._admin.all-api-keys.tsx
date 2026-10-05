import { createFileRoute } from '@tanstack/react-router'

import { AdminApiKeysPage } from '@/features/api-keys/admin-api-keys-page'
import { validateAdminKeysSearch } from '@/features/api-keys/admin-keys-search'

/** /settings/all-api-keys?q=&state=&user_id= — every key that isn't revoked (platform admins). */
export const Route = createFileRoute('/_app/settings/_admin/all-api-keys')({
  validateSearch: validateAdminKeysSearch,
  // A loader crumb (not staticData): it is only shown once the admin check passed.
  loader: () => ({ crumb: 'All API keys' }),
  head: () => ({ meta: [{ title: 'All API keys · Settings · Soundings' }] }),
  component: AdminApiKeysRoute,
})

function AdminApiKeysRoute() {
  const search = Route.useSearch()
  const navigate = Route.useNavigate()
  return (
    <AdminApiKeysPage
      search={search}
      onSearchChange={(patch) =>
        void navigate({ search: (prev) => ({ ...prev, ...patch }), replace: true })
      }
    />
  )
}
