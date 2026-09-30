import type { InfiniteData, UseInfiniteQueryResult } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useVirtualizer } from '@tanstack/react-virtual'
import { ThumbsUp } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'

import type { IdeaPage, IdeaSort, IdeaSummary } from '@/api/types'
import { Button } from '@/components/ui/button'
import { RelativeTime } from '@/components/ui/relative-time'
import { SkeletonGroup, SkeletonListRow } from '@/components/ui/skeleton'
import { StatusBadge } from '@/components/ui/status-badge'
import {
  SortableTableHead,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { NAV_ITEM_ATTRIBUTE, useListNavigation } from '@/lib/list-navigation'
import { cn } from '@/lib/utils'

import { EvaluatorProgress, IdeaScore, OwnerAvatar } from '@/features/project/idea-meta'
import { nextSort, sortDirectionFor, type SortColumn } from '@/features/project/project-search'

/** Fetch the next page when the last rendered row is this close to the end. */
const PREFETCH_ROWS = 30

/**
 * The table turns into stacked cards below this container width (Table's
 * `container-cards`, `@3xl` = 48rem); the virtualizer estimates row heights
 * from it.
 */
const CARDS_BELOW_PX = 768
const ROW_HEIGHT = { table: 44, card: 84 } as const

/*
 * Columns by the room the table has (container queries, so it works with the
 * sidebar open or closed): under 48rem rows are cards; up to 56rem the votes
 * column and the evaluator ticks go, so titles always keep ~280px.
 */
const WIDE_ONLY = '@3xl:@max-4xl:hidden'

export type IdeaListQuery = UseInfiniteQueryResult<InfiniteData<IdeaPage>>

/**
 * The List (SPEC §5 screen 2): a virtualised table — only the rows in view
 * are rendered, pages load as you scroll (cursor pagination), so 10,000
 * ideas scroll as smoothly as 10. Headers sort through the API; j/k or ↑/↓
 * move between rows and Enter opens one. When narrow, rows become stacked cards.
 */
export function ListView({
  query,
  sort,
  onSortChange,
  resetKey,
}: {
  query: IdeaListQuery
  sort: IdeaSort | undefined
  onSortChange: (sort: IdeaSort | undefined) => void
  /** Changes when the filters or sort change: scroll back to the top. */
  resetKey: string
}) {
  const items = query.data?.pages.flatMap((page) => page.items) ?? []
  const total = query.data?.pages[0]?.total ?? items.length
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const [cards, setCards] = useState(false)
  const { listRef } = useListNavigation()
  const containerRef = useCallback(
    (node: HTMLDivElement | null) => {
      scrollRef.current = node
      const cleanupNav = listRef(node)
      if (!node || typeof ResizeObserver === 'undefined') return cleanupNav
      const observer = new ResizeObserver(([entry]) => {
        if (entry) setCards(entry.contentRect.width < CARDS_BELOW_PX)
      })
      observer.observe(node)
      return () => {
        observer.disconnect()
        cleanupNav?.()
      }
    },
    [listRef],
  )

  // The virtualizer is mutable by design; this component isn't compiler-memoised.
  // eslint-disable-next-line react-hooks/incompatible-library -- TanStack Virtual (documented)
  const virtualizer = useVirtualizer({
    count: items.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => (cards ? ROW_HEIGHT.card : ROW_HEIGHT.table),
    getItemKey: (index) => items[index]?.id ?? index,
    overscan: 12,
  })
  const rows = virtualizer.getVirtualItems()
  const lastIndex = rows.at(-1)?.index ?? -1
  const { hasNextPage, isFetchingNextPage, fetchNextPage, isError } = query

  // Infinite scroll: keep a page ahead of the reader.
  useEffect(() => {
    if (
      lastIndex >= items.length - PREFETCH_ROWS &&
      hasNextPage &&
      !isFetchingNextPage &&
      !isError
    ) {
      void fetchNextPage()
    }
  }, [lastIndex, items.length, hasNextPage, isFetchingNextPage, isError, fetchNextPage])

  // New filters or sort: start from the top.
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: 0 })
  }, [resetKey])

  // Spacers stand in for the rows that aren't rendered. Before the first rows are measured
  // the bottom one holds the whole estimated height, so the list (content-sized) has a height.
  const paddingTop = rows[0]?.start ?? 0
  const paddingBottom = virtualizer.getTotalSize() - (rows.at(-1)?.end ?? 0)

  const sortable = (column: SortColumn) => ({
    sorted: sortDirectionFor(sort, column),
    onSort: () => onSortChange(nextSort(sort, column)),
  })

  return (
    <div
      className={cn(
        // Content height when short, the remaining height (scrolling) when long.
        'flex min-h-0 flex-col overflow-hidden rounded-lg border transition-opacity duration-150',
        query.isPlaceholderData && 'opacity-60',
      )}
      aria-busy={query.isPlaceholderData || undefined}
    >
      <Table
        mobile="container-cards"
        containerRef={containerRef}
        containerClassName="h-full overflow-y-auto overscroll-contain"
        className="@3xl:table-fixed"
        aria-label="Ideas"
        aria-rowcount={total + 1}
      >
        <TableHeader className="sticky top-0 z-10 bg-surface after:absolute after:inset-x-0 after:bottom-0 after:h-px after:bg-border [&_tr]:border-b-0">
          <TableRow aria-rowindex={1}>
            <SortableTableHead {...sortable('title')}>Idea</SortableTableHead>
            <TableHead className="w-16">Owner</TableHead>
            <TableHead className="w-20 @4xl:w-28">Evaluators</TableHead>
            <SortableTableHead className="w-24" {...sortable('score')}>
              Score
            </SortableTableHead>
            <TableHead className="w-32">Status</TableHead>
            <SortableTableHead
              className={cn('w-20', WIDE_ONLY)}
              align="right"
              {...sortable('votes')}
            >
              Votes
            </SortableTableHead>
            <SortableTableHead className="w-28" align="right" {...sortable('updated')}>
              Updated
            </SortableTableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {paddingTop > 0 && <Spacer height={paddingTop} />}
          {rows.map((row) => {
            const idea = items[row.index]
            if (!idea) return null
            return (
              <IdeaTableRow
                key={row.key}
                idea={idea}
                index={row.index}
                measure={virtualizer.measureElement}
              />
            )
          })}
          {paddingBottom > 0 && <Spacer height={paddingBottom} />}
        </TableBody>
      </Table>
      {isFetchingNextPage && (
        <SkeletonGroup label="Loading more ideas" className="border-t border-subtle">
          <SkeletonListRow className="border-b-0" />
        </SkeletonGroup>
      )}
      {isError && items.length > 0 && (
        <p
          role="alert"
          className="flex items-center justify-center gap-2 border-t border-subtle py-2 text-sm text-danger"
        >
          Couldn’t load more ideas.
          <Button variant="link" size="sm" onClick={() => void fetchNextPage()}>
            Try again
          </Button>
        </p>
      )}
    </div>
  )
}

function Spacer({ height }: { height: number }) {
  return (
    <tr aria-hidden="true" className="@max-3xl:block">
      <td colSpan={7} className="p-0 @max-3xl:block" style={{ height }} />
    </tr>
  )
}

function IdeaTableRow({
  idea,
  index,
  measure,
}: {
  idea: IdeaSummary
  index: number
  measure: (node: Element | null) => void
}) {
  return (
    <TableRow
      ref={measure}
      data-index={index}
      aria-rowindex={index + 2}
      className="relative @max-3xl:gap-x-3 @max-3xl:gap-y-1.5 @3xl:h-11"
    >
      <TableCell primary className="min-w-0 @max-3xl:order-first">
        <Link
          to="/ideas/$ideaKey"
          params={{ ideaKey: idea.key }}
          {...{ [NAV_ITEM_ATTRIBUTE]: '' }}
          className={cn(
            'flex min-w-0 items-baseline gap-2.5 outline-none',
            // The whole row is the link; the focus ring outlines the row.
            'after:absolute after:inset-0 after:rounded-sm',
            'focus-visible:after:outline-2 focus-visible:after:-outline-offset-2 focus-visible:after:outline-focus',
          )}
        >
          <span className="min-w-16 shrink-0 text-xs whitespace-nowrap text-muted tabular-nums @3xl:min-w-20">
            {idea.key}
          </span>
          <span className="truncate font-medium text-primary">{idea.title}</span>
        </Link>
      </TableCell>
      <TableCell className="@max-3xl:order-2">
        <OwnerAvatar owner={idea.owner} size="sm" />
      </TableCell>
      <TableCell
        className={cn('@max-3xl:order-3', idea.evaluator_progress.total === 0 && '@max-3xl:hidden')}
      >
        {/* Ticks only where there is room; "2/3" always. */}
        <EvaluatorProgress
          progress={idea.evaluator_progress}
          className="@max-4xl:[&>span:first-child]:hidden"
        />
      </TableCell>
      <TableCell
        className={cn('@max-3xl:order-4', !idea.score && !idea.score_hidden && '@max-3xl:hidden')}
      >
        <IdeaScore idea={idea} className="relative z-10" />
      </TableCell>
      <TableCell className="@max-3xl:order-1">
        <StatusBadge
          variant="plain"
          status={idea.status}
          resolution={idea.resolution}
          label={idea.status_label}
          className="max-w-full truncate"
        />
      </TableCell>
      <TableCell
        className={cn(
          'text-right tabular-nums @max-3xl:order-5',
          WIDE_ONLY,
          idea.vote_count === 0 && '@max-3xl:hidden',
        )}
      >
        <span
          className={cn(
            'inline-flex items-center gap-1',
            idea.vote_count === 0
              ? 'text-muted'
              : idea.has_voted
                ? 'text-accent'
                : 'text-secondary',
          )}
        >
          <ThumbsUp aria-hidden="true" className="size-3.5 @3xl:hidden" />
          {idea.vote_count}
          <span className="sr-only">{idea.vote_count === 1 ? 'vote' : 'votes'}</span>
        </span>
      </TableCell>
      <TableCell className="text-right @max-3xl:order-6 @max-3xl:ml-auto">
        <RelativeTime
          date={idea.last_activity_at}
          style="narrow"
          tooltip={false}
          className="text-sm text-muted"
        />
      </TableCell>
    </TableRow>
  )
}

/** Skeleton rows of the final size while the first page loads. */
export function ListSkeleton() {
  return (
    <SkeletonGroup label="Loading ideas" className="overflow-hidden rounded-lg border">
      <div className="h-9 border-b" />
      {Array.from({ length: 10 }, (_, index) => (
        <SkeletonListRow key={index} />
      ))}
    </SkeletonGroup>
  )
}
