import { createFileRoute, Outlet } from '@tanstack/react-router'

/**
 * /settings: your account (index) and, for platform admins, the admin pages
 * (`settings._admin.*`: Users, Groups, Sign-in (SSO), Audit log). Each page
 * renders the shared settings frame (features/admin/settings-frame.tsx).
 */
export const Route = createFileRoute('/_app/settings')({
  staticData: { crumb: 'Settings' },
  head: () => ({ meta: [{ title: 'Settings · Soundings' }] }),
  component: Outlet,
})
