import { Link } from '@tanstack/react-router'
import { CircleCheckBig } from 'lucide-react'
import { useState } from 'react'

import type { WorkEvaluation } from '@/api/types'
import { useMoreEvaluationsDue } from '@/api/work'
import { PageSection } from '@/components/layout/page'
import { Badge, CountBadge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { DueDateLabel } from '@/components/ui/due-date'
import { EmptyState } from '@/components/ui/empty-state'
import { Skeleton, SkeletonGroup } from '@/components/ui/skeleton'
import { NAV_ITEM_ATTRIBUTE } from '@/lib/list-navigation'
import { cn } from '@/lib/utils'

/**
 * "Evaluations due": overdue first, then soonest (the API's order). The most
 * urgent row carries the page's one primary action. My work holds the first 50;
 * "Show more" pages on (100 at a time), so someone who owes a thousand still gets
 * a page that opens at once.
 */
export function EvaluationsDueSection({
  items,
  total,
  nextCursor,
}: {
  items: WorkEvaluation[] | undefined
  /** Everything owed (`counts.evaluations_due`), which may be more than `items`. */
  total: number | undefined
  nextCursor: string | null | undefined
}) {
  const [expanded, setExpanded] = useState(false)
  const more = useMoreEvaluationsDue(nextCursor ?? null, expanded && Boolean(nextCursor))
  const extra = more.data?.pages.flatMap((page) => page.items) ?? []
  const shown = (items?.length ?? 0) + extra.length
  const count = Math.max(total ?? 0, shown)
  const hasMore = expanded ? more.hasNextPage : Boolean(nextCursor)
  const loadingMore = more.isFetchingNextPage || (expanded && more.isPending)
  const rows = items ? dedupeRows([...items, ...extra]) : []

  return (
    <PageSection
      id="evaluations"
      title={
        <>
          Evaluations due
          {count > 0 && <CountBadge>{count.toLocaleString()}</CountBadge>}
        </>
      }
    >
      {!items ? (
        <SkeletonGroup
          label="Loading evaluations"
          className="divide-y divide-subtle overflow-hidden rounded-lg border"
        >
          {[0, 1].map((i) => (
            <div key={i} className="flex min-h-16 items-center gap-4 px-4 py-3">
              <div className="flex flex-1 flex-col gap-2">
                <Skeleton className="h-3.5 w-[min(20rem,70%)]" />
                <Skeleton className="h-3 w-[min(12rem,50%)]" />
              </div>
              <Skeleton className="hidden h-3.5 w-24 sm:block" />
              <Skeleton className="h-8 w-20" />
            </div>
          ))}
        </SkeletonGroup>
      ) : items.length === 0 ? (
        <div className="rounded-lg border">
          <EmptyState
            size="inline"
            icon={<CircleCheckBig />}
            title="Nothing to evaluate"
            description="When someone asks for your view on an idea, it shows here."
          />
        </div>
      ) : (
        <div className="flex flex-col gap-1.5">
          <ul className="divide-y divide-subtle overflow-hidden rounded-lg border bg-surface">
            {rows.map((item, index) => (
              <EvaluationRow key={item.idea.id} item={item} primary={index === 0} />
            ))}
          </ul>
          {hasMore && (
            <div className="flex items-center gap-3 px-1">
              <Button
                variant="ghost"
                size="sm"
                className="text-muted"
                loading={loadingMore}
                onClick={() => {
                  if (!expanded) setExpanded(true)
                  else void more.fetchNextPage()
                }}
              >
                Show {Math.min(100, count - shown).toLocaleString()} more
              </Button>
              <span className="text-sm text-muted tabular-nums">
                {shown.toLocaleString()} of {count.toLocaleString()}
              </span>
            </div>
          )}
          {more.isError && (
            <p role="alert" className="flex items-center gap-2 px-1 text-sm text-danger">
              Couldn’t load more.
              <Button variant="link" size="sm" onClick={() => void more.refetch()}>
                Try again
              </Button>
            </p>
          )}
        </div>
      )}
    </PageSection>
  )
}

/** A row the first page already has can come again if My work refreshed in between. */
function dedupeRows(rows: WorkEvaluation[]): WorkEvaluation[] {
  const seen = new Set<string>()
  return rows.filter((row) => (seen.has(row.idea.id) ? false : (seen.add(row.idea.id), true)))
}

function EvaluationRow({ item, primary }: { item: WorkEvaluation; primary: boolean }) {
  const { idea } = item
  return (
    <li
      data-evaluate-key={idea.key}
      className="relative flex flex-col gap-2.5 px-4 py-3 transition-colors duration-100 hover:bg-subtle sm:flex-row sm:items-center sm:gap-4"
    >
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <div className="flex min-w-0 items-baseline gap-2">
          <span className="shrink-0 text-xs text-muted tabular-nums">{idea.key}</span>
          <Link
            to="/ideas/$ideaKey"
            params={{ ideaKey: idea.key }}
            {...{ [NAV_ITEM_ATTRIBUTE]: '' }}
            className={cn(
              'line-clamp-2 text-base font-medium text-primary outline-none sm:truncate',
              // The whole row is the link; the focus ring outlines the row.
              'after:absolute after:inset-0 after:content-[""]',
              'focus-visible:after:ring-2 focus-visible:after:ring-focus focus-visible:after:ring-inset',
            )}
          >
            {idea.title}
          </Link>
        </div>
        <p className="truncate text-sm text-muted">
          {idea.project.name}
          {item.owner && <> · owner {item.owner.display_name}</>}
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 sm:shrink-0 sm:flex-nowrap">
        {item.state === 'draft' && <Badge>Draft saved</Badge>}
        <DueDateLabel value={item.due_at} />
        {/* Every row's button sits at its end, the same size on phones too (only the
            most urgent one is primary). Its name starts with the word it shows, so
            "click Continue" works by voice (WCAG 2.5.3). */}
        <Button
          asChild
          variant={primary ? 'primary' : 'outline'}
          className="relative z-10 ml-auto max-sm:h-11 max-sm:px-5"
        >
          <Link
            to="/ideas/$ideaKey"
            params={{ ideaKey: idea.key }}
            search={{ evaluate: true }}
            aria-label={
              item.state === 'draft'
                ? `Continue evaluating ${idea.key}: ${idea.title}`
                : `Evaluate ${idea.key}: ${idea.title}`
            }
          >
            {item.state === 'draft' ? 'Continue' : 'Evaluate'}
          </Link>
        </Button>
      </div>
    </li>
  )
}
