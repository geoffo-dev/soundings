import { createFileRoute, redirect } from '@tanstack/react-router'

import { ProjectSettingsPage } from '@/features/project/project-settings-page'
import {
  MOVED_SETTINGS_TABS,
  SETTINGS_TABS,
  type SettingsTab,
} from '@/features/project/settings/settings-tabs'
import { searchEnum } from '@/lib/search-params'

const TAB_TITLES: Record<SettingsTab, string> = {
  general: 'General',
  members: 'Members',
  rubric: 'Rubric',
  research: 'Research',
  'proposal-template': 'Proposal template',
  'public-form': 'Public form',
}

type MovedTab = keyof typeof MOVED_SETTINGS_TABS
const MOVED_TABS = Object.keys(MOVED_SETTINGS_TABS) as MovedTab[]
const isMoved = (tab: string | undefined): tab is MovedTab =>
  tab !== undefined && (MOVED_TABS as string[]).includes(tab)

/** /p/$slug/settings?tab=members|rubric|research|proposal-template|public-form (General is the default). */
export const Route = createFileRoute('/_app/p/$slug/settings')({
  validateSearch: (search: Record<string, unknown>): { tab?: SettingsTab | MovedTab } => ({
    tab: searchEnum(search.tab, [...SETTINGS_TABS, ...MOVED_TABS]),
  }),
  // Old links: ?tab=statuses and ?tab=branding are sections of General and Public form now.
  beforeLoad: ({ search, params }) => {
    if (!isMoved(search.tab)) return
    const moved = MOVED_SETTINGS_TABS[search.tab]
    throw redirect({
      to: '/p/$slug/settings',
      params,
      search: { tab: moved.tab === 'general' ? undefined : moved.tab },
      hash: moved.section,
      replace: true,
    })
  },
  staticData: { crumb: 'Settings' },
  // "Rubric · Customer Innovation · Soundings": the project and the tab (a11y review).
  head: ({ match, matches }) => {
    const project = matches.find((m) => (m.routeId as string) === '/_app/p/$slug')?.loaderData as
      { crumb?: string } | undefined
    const tab = TAB_TITLES[isMoved(match.search.tab) ? 'general' : (match.search.tab ?? 'general')]
    return {
      meta: [
        {
          title: `${tab} · ${project?.crumb ? `${project.crumb} settings` : 'Project settings'} · Soundings`,
        },
      ],
    }
  },
  component: ProjectSettingsRoute,
})

function ProjectSettingsRoute() {
  const { slug } = Route.useParams()
  const { tab } = Route.useSearch()
  return <ProjectSettingsPage slug={slug} tab={isMoved(tab) ? undefined : tab} />
}
