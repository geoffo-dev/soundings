import { createFileRoute } from '@tanstack/react-router'

import { SettingsPage } from '@/features/settings/settings-page'

export const Route = createFileRoute('/_app/settings')({
  staticData: { crumb: 'Settings' },
  head: () => ({ meta: [{ title: 'Settings · Soundings' }] }),
  component: SettingsPage,
})
