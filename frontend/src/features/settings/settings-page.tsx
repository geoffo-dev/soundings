import { Link } from '@tanstack/react-router'
import { ArrowUpRight, Settings } from 'lucide-react'

import { useProjects } from '@/api/projects'
import { Page, PageHeader, PageSection } from '@/components/layout/page'
import { ProjectTile } from '@/components/layout/project-tile'
import { EmptyState } from '@/components/ui/empty-state'
import { Skeleton, SkeletonGroup } from '@/components/ui/skeleton'

/**
 * /settings — Phase 1 placeholder for profile and platform administration.
 * Projects the user manages link to their own settings page.
 */
export function SettingsPage() {
  const projects = useProjects()
  const managed = projects.data?.filter((project) => project.permissions.can_manage) ?? []
  return (
    <Page>
      <PageHeader title="Settings" description="Your profile, notifications and administration." />
      <div className="rounded-lg border">
        <EmptyState
          icon={<Settings />}
          title="More settings arrive with sign-in in Phase 2"
          description="Profile, notification preferences, users, groups and single sign-on will live here. Sensible defaults apply until then."
        />
      </div>
      {(projects.isPending || managed.length > 0) && (
        <PageSection
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
