import { createFileRoute } from '@tanstack/react-router'
import { Settings } from 'lucide-react'

import { Page, PageHeader } from '@/components/layout/page'
import { EmptyState } from '@/components/ui/empty-state'

/** PHASE 0 PLACEHOLDER — project and admin settings arrive in later phases. */
export const Route = createFileRoute('/_app/settings')({
  staticData: { crumb: 'Settings' },
  head: () => ({ meta: [{ title: 'Settings · Soundings' }] }),
  component: () => (
    <Page>
      <PageHeader title="Settings" description="Profile, notifications and administration." />
      <div className="rounded-lg border">
        <EmptyState
          icon={<Settings />}
          title="Nothing to configure yet"
          description="Settings arrive with sign-in, email and branding. Sensible defaults apply until then."
        />
      </div>
    </Page>
  ),
})
