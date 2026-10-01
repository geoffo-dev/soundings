import { createFileRoute } from '@tanstack/react-router'

import { SsoPage } from '@/features/admin/sso/sso-page'

/** /settings/sso — the effective sign-in configuration, read-only. */
export const Route = createFileRoute('/_app/settings/_admin/sso')({
  // A loader crumb (not staticData): it is only shown once the admin check passed.
  loader: () => ({ crumb: 'Sign-in (SSO)' }),
  head: () => ({ meta: [{ title: 'Sign-in (SSO) · Settings · Soundings' }] }),
  component: SsoPage,
})
