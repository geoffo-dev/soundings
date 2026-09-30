import { createFileRoute } from '@tanstack/react-router'

import { ProjectSettingsPage } from '@/features/project/project-settings-page'
import { SETTINGS_TABS, type SettingsTab } from '@/features/project/settings/settings-tabs'
import { searchEnum } from '@/lib/search-params'

/** /p/$slug/settings?tab=members|rubric|statuses (General is the default). */
export const Route = createFileRoute('/_app/p/$slug/settings')({
  validateSearch: (search: Record<string, unknown>): { tab?: SettingsTab } => ({
    tab: searchEnum(search.tab, SETTINGS_TABS),
  }),
  staticData: { crumb: 'Settings' },
  head: () => ({ meta: [{ title: 'Project settings · Soundings' }] }),
  component: ProjectSettingsRoute,
})

function ProjectSettingsRoute() {
  const { slug } = Route.useParams()
  const { tab } = Route.useSearch()
  return <ProjectSettingsPage slug={slug} tab={tab} />
}
