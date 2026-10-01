import { Link } from '@tanstack/react-router'
import { ArrowUpRight, Monitor, Moon, Sun } from 'lucide-react'

import { useProjects } from '@/api/projects'
import { Page, PageHeader, PageSection } from '@/components/layout/page'
import { ProjectTile } from '@/components/layout/project-tile'
import { useTheme } from '@/components/theme-provider'
import { Avatar } from '@/components/ui/avatar'
import { SegmentedControl } from '@/components/ui/segmented-control'
import { Skeleton, SkeletonGroup } from '@/components/ui/skeleton'
import { useCurrentUser } from '@/features/auth/current-user'
import type { ThemePreference } from '@/lib/theme'

const THEMES: { value: ThemePreference; label: string; icon: typeof Sun }[] = [
  { value: 'light', label: 'Light', icon: Sun },
  { value: 'dark', label: 'Dark', icon: Moon },
  { value: 'system', label: 'System', icon: Monitor },
]

/**
 * /settings: who you're signed in as, the theme, and links to the settings of
 * the projects you manage.
 */
export function SettingsPage() {
  const me = useCurrentUser()
  const { preference, setPreference } = useTheme()
  const projects = useProjects()
  const managed = projects.data?.filter((project) => project.permissions.can_manage) ?? []

  return (
    <Page>
      <PageHeader title="Settings" description="Your account, appearance and projects." />

      <PageSection id="account" title="Account">
        <div className="flex items-center gap-3 rounded-lg border px-4 py-3">
          <Avatar name={me.display_name} src={me.avatar_url} size="md" decorative />
          <div className="flex min-w-0 flex-col">
            <span className="truncate text-sm font-medium text-primary">{me.display_name}</span>
            <span className="truncate text-sm text-muted">{me.email}</span>
          </div>
        </div>
      </PageSection>

      <PageSection
        id="appearance"
        title="Appearance"
        description="System follows your device’s light or dark setting. Saved on this device."
      >
        <SegmentedControl
          aria-labelledby="appearance-heading"
          value={preference}
          onValueChange={setPreference}
          className="self-start"
          options={THEMES.map(({ value, label, icon: Icon }) => ({
            value,
            label: (
              <span className="inline-flex items-center gap-1.5">
                <Icon aria-hidden="true" className="size-3.5" />
                {label}
              </span>
            ),
            ariaLabel: label,
          }))}
        />
      </PageSection>

      {(projects.isPending || managed.length > 0) && (
        <PageSection
          id="projects"
          title="Projects you manage"
          description="Members, rubric and status labels are set per project."
        >
          {projects.isPending ? (
            <SkeletonGroup label="Loading projects" className="flex flex-col gap-2">
              <Skeleton className="h-11 w-full" />
              <Skeleton className="h-11 w-full" />
            </SkeletonGroup>
          ) : (
            <ul className="divide-y divide-subtle overflow-hidden rounded-lg border">
              {managed.map((project) => (
                <li key={project.id}>
                  <Link
                    to="/p/$slug/settings"
                    params={{ slug: project.slug }}
                    className="group flex h-11 items-center gap-3 px-4 text-sm font-medium text-primary transition-colors hover:bg-subtle focus-visible:-outline-offset-2"
                  >
                    <ProjectTile name={project.name} />
                    <span className="flex-1 truncate">{project.name}</span>
                    <ArrowUpRight
                      aria-hidden="true"
                      className="size-4 text-muted transition-colors group-hover:text-primary"
                    />
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </PageSection>
      )}
    </Page>
  )
}
