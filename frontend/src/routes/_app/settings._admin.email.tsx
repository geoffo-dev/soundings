import { createFileRoute } from '@tanstack/react-router'

import { EmailPage } from '@/features/admin/email/email-page'
import { validateEmailSearch } from '@/features/admin/email/email-search'

/** /settings/email?status=failed&type=digest — SMTP settings (read-only), test email, outbox. */
export const Route = createFileRoute('/_app/settings/_admin/email')({
  validateSearch: validateEmailSearch,
  // A loader crumb (not staticData): it is only shown once the admin check passed.
  loader: () => ({ crumb: 'Email' }),
  head: () => ({ meta: [{ title: 'Email · Settings · Soundings' }] }),
  component: EmailRoute,
})

function EmailRoute() {
  const search = Route.useSearch()
  const navigate = Route.useNavigate()
  return (
    <EmailPage
      search={search}
      onSearchChange={(patch) =>
        void navigate({ search: (prev) => ({ ...prev, ...patch }), replace: true })
      }
    />
  )
}
