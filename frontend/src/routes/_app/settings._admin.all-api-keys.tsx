import { createFileRoute, redirect } from '@tanstack/react-router'

import { validateAdminKeysSearch } from '@/features/api-keys/admin-keys-search'

/**
 * /settings/all-api-keys?q=&state=&user_id= (Phase 5): now "Everyone's keys" on
 * Settings → API keys. Old links (and bookmarks) land there with their filters;
 * anyone but a platform admin still gets the not-found page first (`_admin`).
 */
export const Route = createFileRoute('/_app/settings/_admin/all-api-keys')({
  validateSearch: validateAdminKeysSearch,
  beforeLoad: ({ search }) => {
    throw redirect({
      to: '/settings/api-keys',
      search: { ...search, everyone: true },
      replace: true,
    })
  },
})
