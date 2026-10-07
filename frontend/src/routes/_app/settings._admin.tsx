import { createFileRoute, notFound, Outlet } from '@tanstack/react-router'

import { PageNotFound } from '@/components/not-found'
import { AdminFrame } from '@/features/admin/settings-frame'

/**
 * The admin settings pages (contract-phase2: platform admins only). Anyone else
 * gets the ordinary not-found page, the same as for any unknown URL: no hint
 * that the page exists, and no admin request is ever sent.
 */
export const Route = createFileRoute('/_app/settings/_admin')({
  beforeLoad: ({ context }) => {
    if (!context.user.is_platform_admin) throw notFound()
  },
  // The admin pages read "Admin › Users", not "Settings › Users" (they live under
  // /settings for their URLs' sake; UX review M5).
  loader: () => ({ crumbRoot: [{ label: 'Admin', to: '/admin' }] }),
  head: ({ match }) =>
    match.status === 'notFound' ? { meta: [{ title: 'Page not found · Soundings' }] } : {},
  notFoundComponent: PageNotFound,
  component: AdminSettingsLayout,
})

function AdminSettingsLayout() {
  return (
    <AdminFrame>
      <Outlet />
    </AdminFrame>
  )
}
