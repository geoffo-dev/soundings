import { createFileRoute } from '@tanstack/react-router'

import { GlobalBrandingPage } from '@/features/branding/global-branding-page'

/** /settings/branding — the instance's branding (platform admins; contract-phase4 §3.10). */
export const Route = createFileRoute('/_app/settings/_admin/branding')({
  // A loader crumb (not staticData): it is only shown once the admin check passed.
  loader: () => ({ crumb: 'Branding' }),
  head: () => ({ meta: [{ title: 'Branding · Admin · Soundings' }] }),
  component: GlobalBrandingPage,
})
