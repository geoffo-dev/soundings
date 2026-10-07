import { createFileRoute } from '@tanstack/react-router'

import { GroupsPage } from '@/features/admin/groups/groups-page'

/** /settings/groups — every group, the "Test mapping" sheet and "New group". */
export const Route = createFileRoute('/_app/settings/_admin/groups/')({
  // A loader crumb (not staticData): it is only shown once the admin check passed.
  loader: () => ({ crumb: 'Groups' }),
  head: () => ({ meta: [{ title: 'Groups · Admin · Soundings' }] }),
  component: GroupsPage,
})
