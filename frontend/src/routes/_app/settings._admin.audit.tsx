import { createFileRoute } from '@tanstack/react-router'

import { AuditPage } from '@/features/admin/audit/audit-page'
import { validateAuditSearch } from '@/features/admin/audit/audit-search'

/** /settings/audit?actor=&action=&project=&from=&to=&target=type:id — newest first. */
export const Route = createFileRoute('/_app/settings/_admin/audit')({
  validateSearch: validateAuditSearch,
  // A loader crumb (not staticData): it is only shown once the admin check passed.
  loader: () => ({ crumb: 'Audit log' }),
  head: () => ({ meta: [{ title: 'Audit log · Admin · Soundings' }] }),
  component: AuditRoute,
})

function AuditRoute() {
  const search = Route.useSearch()
  const navigate = Route.useNavigate()
  return (
    <AuditPage
      search={search}
      onSearchChange={(patch) =>
        void navigate({ search: (prev) => ({ ...prev, ...patch }), replace: true })
      }
    />
  )
}
