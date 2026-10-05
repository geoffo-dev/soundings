import { createFileRoute } from '@tanstack/react-router'

import { ApiKeysPage } from '@/features/api-keys/api-keys-page'

/** /settings/api-keys — your personal API keys and how to connect an MCP client (everyone). */
export const Route = createFileRoute('/_app/settings/api-keys')({
  staticData: { crumb: 'API keys' },
  head: () => ({ meta: [{ title: 'API keys · Settings · Soundings' }] }),
  component: ApiKeysPage,
})
