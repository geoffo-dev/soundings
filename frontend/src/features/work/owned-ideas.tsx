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

  // Viewers can't own or submit ideas: a section they can't act on isn't shown (unless
  // they still own some from before).
  if (!canCreateIdeas && groups?.length === 0) return null

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
          <EmptyState
            size="inline"
            icon={<Lightbulb />}
            title="You don’t own any ideas yet"
            description="Volunteer for one you care about, or submit your own."
            action={
              <Button variant="ghost" size="sm" onClick={openCommandPalette}>
                Find a project
              </Button>
            }
          />
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

/**
 * A group shows its first 10 ideas, then "Show N more" adds 50 at a time: first the
 * rest of what My work already sent (up to 50 per group), then pages from
 * `next_cursor`. An owner of hundreds of ideas gets a page that renders at once.
 */
const OWNED_PREVIEW = 10
const OWNED_STEP = 50

function OwnedGroup({
  group,
  hideHeading = false,
}: {
  group: WorkOwnedGroup
  hideHeading?: boolean
}) {
  const [limit, setLimit] = useState(OWNED_PREVIEW)
  const [expanded, setExpanded] = useState(false)
  const more = useOwnedIdeas(group.status, group.next_cursor, {
    enabled: expanded && Boolean(group.next_cursor),
  })
  const extra = more.data?.pages.flatMap((page) => page.items) ?? []
  const loaded = [...group.ideas, ...extra]
  const rows = loaded.slice(0, limit)
  const serverHasMore = expanded ? more.hasNextPage : Boolean(group.next_cursor)
  const hasMore = loaded.length > rows.length || serverHasMore
  const loadingMore = more.isFetchingNextPage || (expanded && more.isPending)
  const headingId = `owned-${group.status}`
  const closed = group.status === 'closed'

  function showMore() {
    const next = rows.length + OWNED_STEP
    setLimit(next)
    if (loaded.length >= next || !serverHasMore) return
    if (!expanded) setExpanded(true)
    else void more.fetchNextPage()
  }

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
        {rows.map((idea) => (
          <IdeaRow key={idea.id} idea={idea} showStatus={closed} />
        ))}
      </ul>
      {hasMore && (
        <div className="mt-1.5 flex items-center gap-3 px-1">
          <Button
            variant="ghost"
            size="sm"
            className="text-muted"
            loading={loadingMore}
            onClick={showMore}
          >
            Show {Math.max(1, Math.min(OWNED_STEP, group.count - rows.length))} more
          </Button>
          <span className="text-sm text-muted tabular-nums">
            {rows.length} of {group.count}
          </span>
        </div>
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
