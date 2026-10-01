import { createFileRoute } from '@tanstack/react-router'

import { NotificationPreferencesPage } from '@/features/notifications/preferences-page'

/** /settings/notifications — your email preferences per notification type (everyone). */
export const Route = createFileRoute('/_app/settings/notifications')({
  staticData: { crumb: 'Notifications' },
  head: () => ({ meta: [{ title: 'Notifications · Settings · Soundings' }] }),
  component: NotificationPreferencesPage,
})
