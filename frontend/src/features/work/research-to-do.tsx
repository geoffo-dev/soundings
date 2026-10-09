import { Link } from '@tanstack/react-router'
import { ListChecks } from 'lucide-react'
import { useState } from 'react'

import type { WorkResearch } from '@/api/types'
import { useMoreResearchToDo } from '@/api/work'
import { PageSection } from '@/components/layout/page'
import { Badge, CountBadge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { DueDateLabel } from '@/components/ui/due-date'
import { badgeLabel, badgeWords } from '@/features/research/research-copy'
import { NAV_ITEM_ATTRIBUTE } from '@/lib/list-navigation'
import { cn } from '@/lib/utils'

/**
 * Phase 8b, "Research to do" (contract-phase8b §7): ideas whose research you do (as
 * their researcher, or as owner while nobody is assigned) with a required checklist
 * item open; overdue first, then soonest due, no due date last (the API's order). Only
 * shown when there is any. My work holds the first 50; "Show more" pages on.
 */
export function ResearchToDoSection({
  items,
  total,
  nextCursor,
}: {
  items: WorkResearch[] | undefined
  /** `counts.research_to_do`, which may be more than `items`. */
  total: number | undefined
  nextCursor: string | null | undefined
}) {
  const [expanded, setExpanded] = useState(false)
  const more = useMoreResearchToDo(nextCursor ?? null, expanded && Boolean(nextCursor))
  const extra = more.data?.pages.flatMap((page) => page.items) ?? []
  const shown = (items?.length ?? 0) + extra.length
  const count = Math.max(total ?? 0, shown)
  const hasMore = expanded ? more.hasNextPage : Boolean(nextCursor)
  const loadingMore = more.isFetchingNextPage || (expanded && more.isPending)

  // Nothing to research (or still loading with the rest of My work): no section at all.
  if (!items || items.length === 0) return null
  const rows = dedupeRows([...items, ...extra])

  return (
    <PageSection
      id="research"
      title={
        <>
          Research to do
          <CountBadge>{count.toLocaleString()}</CountBadge>
        </>
      }
    >
      <div className="flex flex-col gap-1.5">
        <ul className="divide-y divide-subtle overflow-hidden rounded-lg border bg-surface">
          {rows.map((item) => (
            <ResearchRow key={item.idea.id} item={item} />
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
              Show {Math.max(1, Math.min(100, count - shown)).toLocaleString()} more
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
    </PageSection>
  )
}

/** A row the first page already has can come again if My work refreshed in between. */
function dedupeRows(rows: WorkResearch[]): WorkResearch[] {
  const seen = new Set<string>()
  return rows.filter((row) => (seen.has(row.idea.id) ? false : (seen.add(row.idea.id), true)))
}

function ResearchRow({ item }: { item: WorkResearch }) {
  const { idea, progress } = item
  return (
    <li className="relative flex flex-col gap-2.5 px-4 py-3 transition-colors duration-100 hover:bg-subtle sm:flex-row sm:items-center sm:gap-4">
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <div className="flex min-w-0 items-baseline gap-2">
          <span className="shrink-0 text-xs text-muted tabular-nums">{idea.key}</span>
          <Link
            to="/ideas/$ideaKey"
            params={{ ideaKey: idea.key }}
            search={{ research: true }}
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
          {item.can_view_project ? (
            <Link
              to="/p/$slug"
              params={{ slug: idea.project.slug }}
              className="relative z-10 rounded-sm hover:text-primary hover:underline"
            >
              {idea.project.name}
            </Link>
          ) : (
            // A guest researcher can't open the project: its name as text (review S7).
            idea.project.name
          )}
          {' · '}
          {idea.status_label}
          {!item.as_owner && item.owner && <> · owner {item.owner.display_name}</>}
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 sm:shrink-0 sm:flex-nowrap">
        {item.as_owner && <Badge variant="outline">As owner</Badge>}
        <span
          role="img"
          aria-label={badgeLabel(progress)}
          className="inline-flex h-5 items-center gap-1 rounded-sm bg-subtle px-1.5 text-xs font-medium text-secondary tabular-nums"
        >
          <ListChecks aria-hidden="true" className="size-3.5" />
          <span aria-hidden="true">{badgeWords(progress)}</span>
        </span>
        <DueDateLabel value={item.due_at} hideWhenNone />
        <Button asChild variant="outline" className="relative z-10 ml-auto max-sm:h-11 max-sm:px-5">
          <Link
            to="/ideas/$ideaKey"
            params={{ ideaKey: idea.key }}
            search={{ research: true }}
            // Starts with the word it shows, so "click Answer" works by voice (WCAG 2.5.3).
            aria-label={`Answer the research checklist of ${idea.key}: ${idea.title}`}
          >
            Answer
          </Link>
        </Button>
      </div>
    </li>
  )
}
