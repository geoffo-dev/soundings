import { Link } from '@tanstack/react-router'
import { Activity, FolderOpen } from 'lucide-react'

import { useProjects } from '@/api/projects'
import type { WorkRecentIdea } from '@/api/types'
import { PageSection } from '@/components/layout/page'
import { ProjectTile } from '@/components/layout/project-tile'
import { Avatar } from '@/components/ui/avatar'
import { EmptyState } from '@/components/ui/empty-state'
import { RelativeTime } from '@/components/ui/relative-time'
import { Skeleton, SkeletonGroup } from '@/components/ui/skeleton'
import { activityActor, describeActivity } from '@/lib/activity'
import { NAV_ITEM_ATTRIBUTE } from '@/lib/list-navigation'

import { rowLink } from './idea-row'

/** A glance, not a feed: the full lists are a click away in each project. */
const RECENT_SHOWN = 10

/** "Recently updated in my projects": the most recently active ideas. */
export function RecentIdeasSection({ recent }: { recent: WorkRecentIdea[] | undefined }) {
  return (
    <PageSection id="recent" title="Recently updated in my projects">
      {!recent ? (
        <SkeletonGroup
          label="Loading recent activity"
          className="divide-y divide-subtle overflow-hidden rounded-lg border"
        >
          {[0, 1, 2].map((i) => (
            <div key={i} className="flex min-h-14 items-center gap-3 px-4 py-2.5">
              <Skeleton className="size-6 rounded-full" />
              <div className="flex flex-1 flex-col gap-1.5">
                <Skeleton className="h-3.5 w-[min(18rem,60%)]" />
                <Skeleton className="h-3 w-[min(14rem,45%)]" />
              </div>
              <Skeleton className="h-3 w-10" />
            </div>
          ))}
        </SkeletonGroup>
      ) : recent.length === 0 ? (
        <NoRecentActivity />
      ) : (
        <ul className="divide-y divide-subtle overflow-hidden rounded-lg border bg-surface">
          {recent.slice(0, RECENT_SHOWN).map(({ idea, latest_activity: activity }) => (
            <li key={idea.id}>
              <Link
                to="/ideas/$ideaKey"
                params={{ ideaKey: idea.key }}
                className={rowLink}
                {...{ [NAV_ITEM_ATTRIBUTE]: '' }}
              >
                {activity?.actor ? (
                  <Avatar
                    name={activity.actor.display_name}
                    src={activity.actor.avatar_url}
                    size="sm"
                    decorative
                  />
                ) : (
                  <span aria-hidden="true" className="size-6 shrink-0 rounded-full bg-subtle" />
                )}
                <span className="flex min-w-0 flex-1 flex-col">
                  <span className="flex min-w-0 items-baseline gap-2">
                    <span className="shrink-0 text-xs text-muted tabular-nums">{idea.key}</span>
                    <span className="line-clamp-2 text-sm font-medium text-primary sm:truncate">
                      {idea.title}
                    </span>
                  </span>
                  <span className="truncate text-sm text-muted">
                    {activity ? (
                      <>
                        <span className="text-secondary">{activityActor(activity)}</span>{' '}
                        {describeActivity(activity)}
                      </>
                    ) : (
                      'No activity yet'
                    )}
                    <span className="max-sm:hidden"> · {idea.project.name}</span>
                  </span>
                </span>
                <RelativeTime
                  date={activity?.created_at ?? idea.last_activity_at}
                  style="narrow"
                  className="shrink-0 text-xs text-muted"
                />
              </Link>
            </li>
          ))}
        </ul>
      )}
    </PageSection>
  )
}

/**
 * Nothing recent: either nothing happened yet, or the user isn't in any
 * project — then point them at the internal projects they can browse.
 */
function NoRecentActivity() {
  const projects = useProjects()
  const member = projects.data?.some((project) => project.my_role !== null) ?? true
  const browsable = projects.data?.filter((project) => project.my_role === null) ?? []
  if (member || browsable.length === 0) {
    return (
      <div className="rounded-lg border">
        <EmptyState
          size="inline"
          icon={<Activity />}
          title={member ? 'Nothing new in your projects' : 'You’re not in any projects yet'}
          description={
            member
              ? 'When ideas in your projects change, they show up here.'
              : 'Ask a project admin to add you. Projects you join show their latest ideas here.'
          }
        />
      </div>
    )
  }
  return (
    <div className="flex flex-col gap-3 rounded-lg border p-4">
      <div className="flex items-start gap-3">
        <FolderOpen aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-muted" />
        <div className="flex flex-col gap-0.5">
          <p className="text-base font-medium text-primary">You’re not in any projects yet</p>
          <p className="text-sm text-muted">
            Ask a project admin to add you. Meanwhile, these projects are open to everyone:
          </p>
        </div>
      </div>
      <ul className="flex flex-wrap gap-2 pl-7">
        {browsable.map((project) => (
          <li key={project.id}>
            <Link
              to="/p/$slug"
              params={{ slug: project.slug }}
              className="inline-flex h-8 items-center gap-2 rounded-md border px-2.5 text-sm font-medium text-primary transition-colors hover:bg-subtle"
            >
              <ProjectTile name={project.name} />
              {project.name}
            </Link>
          </li>
        ))}
      </ul>
    </div>
  )
}
