import { ChevronRight, Lightbulb } from 'lucide-react'
import { useState } from 'react'

import type { WorkOwnedGroup } from '@/api/types'
import { useOwnedIdeas } from '@/api/work'
import { useAppCommands } from '@/components/layout/app-commands'
import { PageSection } from '@/components/layout/page'
import { CountBadge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'
import { SkeletonGroup, SkeletonListRow } from '@/components/ui/skeleton'
import { Spinner } from '@/components/ui/spinner'
import { StatusDot } from '@/components/ui/status-badge'
import { statusTone } from '@/lib/status'
import { cn } from '@/lib/utils'

import { IdeaRow } from './idea-row'

/** "Ideas I own", grouped by status in lifecycle order; Closed is collapsed. */
export function OwnedIdeasSection({
  groups,
  openCount,
}: {
  groups: WorkOwnedGroup[] | undefined
  openCount: number | undefined
}) {
  const { openCommandPalette, canCreateIdeas } = useAppCommands()
  const [showClosed, setShowClosed] = useState(false)
  const open = groups?.filter((group) => group.status !== 'closed') ?? []
  const closed = groups?.find((group) => group.status === 'closed')

  return (
    <PageSection
      id="owned"
      title={
        <>
          Ideas I own
          {openCount !== undefined && openCount > 0 && <CountBadge>{openCount}</CountBadge>}
        </>
      }
    >
      {!groups ? (
        <SkeletonGroup label="Loading your ideas" className="overflow-hidden rounded-lg border">
          <SkeletonListRow />
          <SkeletonListRow />
          <SkeletonListRow className="border-b-0" />
        </SkeletonGroup>
      ) : groups.length === 0 ? (
        <div className="rounded-lg border">
          {canCreateIdeas ? (
            <EmptyState
              size="compact"
              icon={<Lightbulb />}
              title="You don’t own any ideas yet"
              description="Open a project and volunteer for an idea you care about, or submit your own."
              action={
                <Button variant="outline" onClick={openCommandPalette}>
                  Find a project
                </Button>
              }
            />
          ) : (
            // Viewers (or people in no project) can't own or submit ideas: don't suggest it.
            <EmptyState
              size="compact"
              icon={<Lightbulb />}
              title="No ideas to own"
              description="Project members submit and own ideas. To join in, ask a project admin to add you as a member."
            />
          )}
        </div>
      ) : (
        <div className="flex flex-col gap-5">
          {open.length === 0 && (
            <p className="rounded-lg border px-4 py-3 text-sm text-muted">
              All the ideas you own are closed.
            </p>
          )}
          {open.map((group) => (
            <OwnedGroup key={group.status} group={group} />
          ))}
          {closed && (
            <div className="flex flex-col gap-2">
              <button
                type="button"
                aria-expanded={showClosed}
                aria-controls="owned-closed"
                onClick={() => setShowClosed((value) => !value)}
                className="-mx-1 flex w-fit items-center gap-1.5 rounded-md px-1 py-0.5 text-sm font-medium text-muted transition-colors hover:text-primary"
              >
                <ChevronRight
                  aria-hidden="true"
                  className={cn(
                    'size-4 transition-transform duration-150',
                    showClosed && 'rotate-90',
                  )}
                />
                {showClosed ? 'Hide closed' : 'Show closed'}
                <span className="tabular-nums">({closed.count})</span>
              </button>
              {showClosed && (
                <div id="owned-closed">
                  <OwnedGroup group={closed} hideHeading />
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </PageSection>
  )
}

function OwnedGroup({
  group,
  hideHeading = false,
}: {
  group: WorkOwnedGroup
  hideHeading?: boolean
}) {
  const [expanded, setExpanded] = useState(false)
  const more = useOwnedIdeas(group.status, group.next_cursor, {
    enabled: expanded && Boolean(group.next_cursor),
  })
  const extra = more.data?.pages.flatMap((page) => page.items) ?? []
  const shown = group.ideas.length + extra.length
  const hasMore = expanded ? more.hasNextPage : Boolean(group.next_cursor)
  const headingId = `owned-${group.status}`
  const closed = group.status === 'closed'

  return (
    <section
      aria-labelledby={hideHeading ? undefined : headingId}
      aria-label={hideHeading ? group.label : undefined}
    >
      {!hideHeading && (
        <h3
          id={headingId}
          className="flex items-center gap-2 px-1 pb-1.5 text-sm font-medium text-secondary"
        >
          <StatusDot tone={statusTone(group.status, null)} />
          {group.label}
          <span className="font-normal text-muted tabular-nums">{group.count}</span>
        </h3>
      )}
      <ul className="divide-y divide-subtle overflow-hidden rounded-lg border bg-surface">
        {[...group.ideas, ...extra].map((idea) => (
          <IdeaRow key={idea.id} idea={idea} showStatus={closed} />
        ))}
      </ul>
      {hasMore && (
        <Button
          variant="ghost"
          size="sm"
          className="mt-1.5 text-muted"
          disabled={more.isFetchingNextPage || (expanded && more.isPending)}
          onClick={() => {
            if (!expanded) setExpanded(true)
            else void more.fetchNextPage()
          }}
        >
          {(more.isFetchingNextPage || (expanded && more.isPending)) && <Spinner />}
          Show {Math.min(50, group.count - shown)} more
        </Button>
      )}
      {more.isError && (
        <p role="alert" className="mt-1.5 flex items-center gap-2 px-1 text-sm text-danger">
          Couldn’t load more.
          <Button variant="link" size="sm" onClick={() => void more.refetch()}>
            Try again
          </Button>
        </p>
      )}
    </section>
  )
}
