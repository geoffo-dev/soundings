import { createFileRoute } from '@tanstack/react-router'

import { NotificationsPage } from '@/features/notifications/notifications-page'
import { searchFlag } from '@/lib/search-params'

export interface NotificationsSearch {
  /** `?unread=1`: unread only. */
  unread?: true
}

/** /notifications?unread=1 — the inbox (the bell's "See all", phones, "g i"). */
export const Route = createFileRoute('/_app/notifications')({
  validateSearch: (search: Record<string, unknown>): NotificationsSearch => ({
    unread: searchFlag(search.unread),
  }),
  staticData: { crumb: 'Notifications' },
  head: () => ({ meta: [{ title: 'Notifications · Soundings' }] }),
  component: NotificationsRoute,
})

function NotificationsRoute() {
  const search = Route.useSearch()
  const navigate = Route.useNavigate()
  return (
    <NotificationsPage
      unread={Boolean(search.unread)}
      onUnreadChange={(unread) =>
        void navigate({ search: unread ? { unread: true } : {}, replace: true })
      }
    />
  )
}
