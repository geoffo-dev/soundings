import { createFileRoute } from '@tanstack/react-router'

import { validateApiKeysSearch } from '@/features/api-keys/admin-keys-search'
import { ApiKeysPage } from '@/features/api-keys/api-keys-page'

/**
 * /settings/api-keys — your personal API keys and how to connect an MCP client
 * (everyone); `?everyone=1&q=&state=&user_id=` is every key (platform admins).
 */
export const Route = createFileRoute('/_app/settings/api-keys')({
  validateSearch: validateApiKeysSearch,
  staticData: { crumb: 'API keys' },
  head: () => ({ meta: [{ title: 'API keys · Settings · Soundings' }] }),
  component: ApiKeysRoute,
})

function ApiKeysRoute() {
  const search = Route.useSearch()
  const navigate = Route.useNavigate()
  return (
    <ApiKeysPage
      search={search}
      onSearchChange={(patch) =>
        void navigate({ search: (prev) => ({ ...prev, ...patch }), replace: true })
      }
    />
  )
}
