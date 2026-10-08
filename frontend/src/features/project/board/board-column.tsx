import { useDroppable } from '@dnd-kit/core'
import { useInfiniteQuery } from '@tanstack/react-query'
import { ChevronsLeftRight, ChevronsRightLeft } from 'lucide-react'
import { useState, type ReactNode } from 'react'

import { ideaListInfiniteOptions } from '@/api/ideas'
import type {
  BoardColumn as BoardColumnData,
  IdeaFilters,
  IdeaSummary,
  Resolution,
  StatusLabels,
} from '@/api/types'
import { Button } from '@/components/ui/button'
import { SkeletonBoardCard, SkeletonGroup } from '@/components/ui/skeleton'
import { Spinner } from '@/components/ui/spinner'
import { StatusDot } from '@/components/ui/status-badge'
import { WithTooltip } from '@/components/ui/tooltip'
import { NAV_COLUMN_ATTRIBUTE } from '@/lib/list-navigation'
import { CLOSED_RESOLUTIONS, statusTone } from '@/lib/status'
import { cn } from '@/lib/utils'

import { BoardCard } from './board-card'
import type { ColumnDropData } from './keyboard'

const PAGE_SIZE = 50

const COLUMN_HINTS: Record<BoardColumnData['status'], string> = {
  new: 'New ideas land here.',
  research: 'Ideas being checked: done elsewhere already? The right teams consulted?',
  evaluating: 'Ideas being scored by evaluators.',
  shortlisted: 'The most promising ideas.',
  proposal: 'Ideas with a proposal in the works.',
  closed: 'Accepted, rejected and parked ideas.',
}

export const columnId = (status: string) => `column:${status}`

const COMPACT = new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 })

/** One status column: header with count, cards, "Show more", and a drop target. */
export function BoardColumn({
  slug,
  column,
  filters,
  labels,
  canDrop,
  headerAnchor,
  collapsed = false,
  onToggleCollapsed,
}: {
  slug: string
  column: BoardColumnData
  filters: IdeaFilters
  labels: StatusLabels
  /** Someone is dragging a card that could land here. */
  canDrop: boolean
  /** Wraps the header (the Closed column anchors the resolution picker to it). */
  headerAnchor?: (header: ReactNode) => ReactNode
  collapsed?: boolean
  onToggleCollapsed?: () => void
}) {
  const { setNodeRef, isOver } = useDroppable({
    id: columnId(column.status),
    data: { type: 'column', status: column.status } satisfies ColumnDropData,
  })
  const closed = column.status === 'closed'
  const [resolution, setResolution] = useState<Resolution | null>(null)
  const headingId = `board-column-${column.status}`

  const header = (
    <div className="flex h-8 items-center gap-2 px-1.5">
      <h2
        id={headingId}
        className="flex min-w-0 items-center gap-2 text-sm font-medium text-primary"
      >
        <StatusDot tone={statusTone(column.status, null)} />
        <span className="truncate">{column.label}</span>
        {/* The collapsed column is narrow: 1,234 reads "1.2K" there, so its name stays whole. */}
        {collapsed && column.count >= 1000 ? (
          <span className="shrink-0 font-normal text-muted tabular-nums">
            <span aria-hidden="true">{COMPACT.format(column.count)}</span>
            <span className="sr-only">{column.count.toLocaleString()}</span>
          </span>
        ) : (
          <span className="shrink-0 font-normal text-muted tabular-nums">
            {column.count.toLocaleString()}
          </span>
        )}
      </h2>
      {onToggleCollapsed && (
        <WithTooltip content={collapsed ? `Show ${column.label.toLowerCase()} ideas` : 'Collapse'}>
          <Button
            id={`${headingId}-toggle`}
            variant="ghost"
            size="icon-sm"
            className="ml-auto"
            aria-expanded={!collapsed}
            aria-controls={`${headingId}-body`}
            aria-label={collapsed ? `Show ${column.label} ideas` : `Collapse ${column.label}`}
            onClick={onToggleCollapsed}
          >
            {collapsed ? <ChevronsLeftRight /> : <ChevronsRightLeft />}
          </Button>
        </WithTooltip>
      )}
    </div>
  )

  return (
    <section
      ref={setNodeRef}
      aria-labelledby={headingId}
      data-over={isOver || undefined}
      {...{ [NAV_COLUMN_ATTRIBUTE]: '' }}
      className={cn(
        'flex max-h-full min-h-0 shrink-0 snap-start flex-col gap-2 rounded-lg bg-background p-2',
        'transition-[background-color,box-shadow] duration-150',
        // Phones: one column per screen, snapping. Wider: columns share the width (six,
        // with the research step, still fit beside the sidebar at 1440 px).
        collapsed ? 'w-11/12 sm:w-40' : 'w-11/12 sm:w-auto sm:max-w-sm sm:min-w-44 sm:flex-1',
        canDrop && 'ring-1 ring-border',
        isOver && 'bg-accent-subtle ring-accent/40',
      )}
    >
      {headerAnchor ? headerAnchor(header) : header}
      <div id={`${headingId}-body`} className="flex min-h-0 flex-1 flex-col">
        {closed && collapsed ? (
          <ResolutionSummary
            column={column}
            labels={labels}
            onPick={(value) => {
              setResolution(value)
              onToggleCollapsed?.()
            }}
          />
        ) : (
          <>
            {closed && (
              <ResolutionTabs
                column={column}
                labels={labels}
                value={resolution}
                onChange={setResolution}
              />
            )}
            {closed && resolution ? (
              <ResolutionCards
                slug={slug}
                filters={filters}
                resolution={resolution}
                labels={labels}
              />
            ) : (
              <ColumnCards slug={slug} column={column} filters={filters} />
            )}
          </>
        )}
      </div>
    </section>
  )
}

/** The column's first page from the board, plus "Show more" via `list_ideas` and the column's cursor. */
function ColumnCards({
  slug,
  column,
  filters,
}: {
  slug: string
  column: BoardColumnData
  filters: IdeaFilters
}) {
  const [expanded, setExpanded] = useState(false)
  const more = useInfiniteQuery({
    ...ideaListInfiniteOptions(
      slug,
      { ...filters, status: [column.status], resolution: undefined },
      { pageSize: PAGE_SIZE, initialCursor: column.next_cursor },
    ),
    enabled: expanded && Boolean(column.next_cursor),
  })
  const extra = expanded ? (more.data?.pages.flatMap((page) => page.items) ?? []) : []
  const cards = dedupe([...column.items, ...extra]).filter((idea) => idea.status === column.status)
  const hasMore = expanded ? more.hasNextPage : Boolean(column.next_cursor)
  const loading = expanded && (more.isPending || more.isFetchingNextPage)

  return (
    <CardList
      ideas={cards}
      empty={COLUMN_HINTS[column.status]}
      footer={
        <>
          {hasMore && (
            <Button
              variant="ghost"
              size="sm"
              className="w-full text-muted"
              disabled={loading}
              onClick={() => (expanded ? void more.fetchNextPage() : setExpanded(true))}
            >
              {loading && <Spinner />}
              Show {Math.max(1, Math.min(PAGE_SIZE, column.count - cards.length))} more
            </Button>
          )}
          {more.isError && <LoadMoreError onRetry={() => void more.refetch()} />}
        </>
      }
    />
  )
}

/** Closed, one resolution: its own list (the board only has "all closed"). */
function ResolutionCards({
  slug,
  filters,
  resolution,
  labels,
}: {
  slug: string
  filters: IdeaFilters
  resolution: Resolution
  labels: StatusLabels
}) {
  const list = useInfiniteQuery(
    ideaListInfiniteOptions(
      slug,
      { ...filters, status: ['closed'], resolution: [resolution] },
      { pageSize: PAGE_SIZE },
    ),
  )
  if (list.isPending) {
    return (
      <SkeletonGroup label={`Loading ${labels[resolution]} ideas`} className="flex flex-col gap-2">
        <SkeletonBoardCard />
        <SkeletonBoardCard />
      </SkeletonGroup>
    )
  }
  if (list.isError) return <LoadMoreError onRetry={() => void list.refetch()} />
  const cards = dedupe(list.data.pages.flatMap((page) => page.items)).filter(
    (idea) => idea.status === 'closed' && idea.resolution === resolution,
  )
  return (
    <CardList
      ideas={cards}
      empty={`No ${labels[resolution].toLowerCase()} ideas.`}
      footer={
        list.hasNextPage && (
          <Button
            variant="ghost"
            size="sm"
            className="w-full text-muted"
            disabled={list.isFetchingNextPage}
            onClick={() => void list.fetchNextPage()}
          >
            {list.isFetchingNextPage && <Spinner />}
            Show more
          </Button>
        )
      }
    />
  )
}

function CardList({
  ideas,
  empty,
  footer,
}: {
  ideas: IdeaSummary[]
  empty: string
  footer?: ReactNode
}) {
  return (
    <div className="-mx-2 flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto overscroll-contain px-2 pt-0.5 pb-1">
      {ideas.length === 0 ? (
        <p className="rounded-lg border border-dashed px-3 py-6 text-center text-sm text-muted">
          {empty}
        </p>
      ) : (
        <ul className="flex flex-col gap-2">
          {ideas.map((idea) => (
            <li key={idea.id}>
              <BoardCard idea={idea} />
            </li>
          ))}
        </ul>
      )}
      {footer}
    </div>
  )
}

/** Collapsed Closed column: counts per resolution; each opens the column filtered to it. */
function ResolutionSummary({
  column,
  labels,
  onPick,
}: {
  column: BoardColumnData
  labels: StatusLabels
  onPick: (resolution: Resolution) => void
}) {
  return (
    <ul className="flex flex-col gap-0.5">
      {CLOSED_RESOLUTIONS.map((resolution) => (
        <li key={resolution}>
          <button
            type="button"
            onClick={() => onPick(resolution)}
            className="flex h-8 w-full items-center gap-2 rounded-md px-2 text-sm text-secondary transition-colors hover:bg-subtle hover:text-primary"
          >
            <StatusDot tone={resolution} />
            {labels[resolution]}
            <span className="ml-auto text-muted tabular-nums">
              {column.resolution_counts?.[resolution] ?? 0}
            </span>
          </button>
        </li>
      ))}
    </ul>
  )
}

/** Expanded Closed column: All · Accepted · Rejected · Parked. */
function ResolutionTabs({
  column,
  labels,
  value,
  onChange,
}: {
  column: BoardColumnData
  labels: StatusLabels
  value: Resolution | null
  onChange: (value: Resolution | null) => void
}) {
  const options: { value: Resolution | null; label: string; count: number }[] = [
    { value: null, label: 'All', count: column.count },
    ...CLOSED_RESOLUTIONS.map((resolution) => ({
      value: resolution,
      label: labels[resolution],
      count: column.resolution_counts?.[resolution] ?? 0,
    })),
  ]
  return (
    <div role="group" aria-label="Show closed ideas" className="mb-2 flex flex-wrap gap-1 px-0.5">
      {options.map((option) => (
        <button
          key={option.label}
          type="button"
          aria-pressed={value === option.value}
          onClick={() => onChange(option.value)}
          className={cn(
            'inline-flex h-6 items-center gap-1.5 rounded-md px-2 text-xs font-medium transition-colors',
            // The chosen filter stands out by more than a fill (WCAG 1.4.11).
            value === option.value
              ? 'bg-surface font-semibold text-primary ring-1 ring-control'
              : 'text-muted hover:bg-subtle hover:text-primary',
          )}
        >
          {option.value && <StatusDot tone={option.value} className="size-1.5" />}
          {option.label}
          <span className="font-normal text-muted tabular-nums">{option.count}</span>
        </button>
      ))}
    </div>
  )
}

function LoadMoreError({ onRetry }: { onRetry: () => void }) {
  return (
    <p
      role="alert"
      className="flex items-center justify-center gap-2 px-1 py-2 text-sm text-danger"
    >
      Couldn’t load more.
      <Button variant="link" size="sm" onClick={onRetry}>
        Try again
      </Button>
    </p>
  )
}

function dedupe(ideas: IdeaSummary[]): IdeaSummary[] {
  const seen = new Set<string>()
  return ideas.filter((idea) => (seen.has(idea.id) ? false : (seen.add(idea.id), true)))
}
