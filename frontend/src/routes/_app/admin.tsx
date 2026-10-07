import { createFileRoute, notFound } from '@tanstack/react-router'

import { PageNotFound } from '@/components/not-found'
import { AdminOverview } from '@/features/admin/settings-frame'

/**
 * /admin: the admin sections (platform admins; the sidebar's "Admin"). Anyone
 * else gets the ordinary not-found page, as for the admin pages themselves.
 */
export const Route = createFileRoute('/_app/admin')({
  beforeLoad: ({ context }) => {
    if (!context.user.is_platform_admin) throw notFound()
  },
  loader: () => ({ crumb: 'Admin' }),
  head: ({ match }) => ({
    meta: [
      { title: match.status === 'notFound' ? 'Page not found · Soundings' : 'Admin · Soundings' },
    ],
  }),
  notFoundComponent: PageNotFound,
  component: AdminOverview,
})
