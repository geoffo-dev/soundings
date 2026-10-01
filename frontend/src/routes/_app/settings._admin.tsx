import { createFileRoute, notFound, Outlet } from '@tanstack/react-router'

import { PageNotFound } from '@/components/not-found'
import { SettingsFrame } from '@/features/admin/settings-frame'

/**
 * The admin settings pages (contract-phase2: platform admins only). Anyone else
 * gets the ordinary not-found page, the same as for any unknown URL: no hint
 * that the page exists, and no admin request is ever sent.
 */
export const Route = createFileRoute('/_app/settings/_admin')({
  beforeLoad: ({ context }) => {
    if (!context.user.is_platform_admin) throw notFound()
  },
  head: ({ match }) =>
    match.status === 'notFound' ? { meta: [{ title: 'Page not found · Soundings' }] } : {},
  notFoundComponent: PageNotFound,
  component: AdminSettingsLayout,
})

function AdminSettingsLayout() {
  return (
    <SettingsFrame>
      <Outlet />
    </SettingsFrame>
  )
}
