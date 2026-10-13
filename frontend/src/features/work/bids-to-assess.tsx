import { Link } from '@tanstack/react-router'
import { Gavel } from 'lucide-react'

import type { WorkBidAssessment } from '@/api/types'
import { PageSection } from '@/components/layout/page'
import { CountBadge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { DueDateLabel } from '@/components/ui/due-date'
import { NAV_ITEM_ATTRIBUTE } from '@/lib/list-navigation'
import { cn } from '@/lib/utils'

/**
 * Phase 10, "Bids to assess" (contract-phase10 §11): calls being assessed where you still
 * owe assessments, overdue first, then soonest due (the API's order). Progress only:
 * never scores, prices or bidders. Shown only when there is any.
 */
export function BidsToAssessSection({
  items,
  total,
}: {
  items: WorkBidAssessment[] | undefined
  /** `counts.bid_assessments_due`: assessments owed, over every call. */
  total: number | undefined
}) {
  if (!items || items.length === 0) return null
  return (
    <PageSection
      id="bids"
      title={
        <>
          Bids to assess
          <CountBadge>{(total ?? 0).toLocaleString()}</CountBadge>
        </>
      }
    >
      <ul className="divide-y divide-subtle overflow-hidden rounded-lg border bg-surface">
        {items.map((item) => (
          <BidCallRow key={item.call.id} item={item} />
        ))}
      </ul>
    </PageSection>
  )
}

function BidCallRow({ item }: { item: WorkBidAssessment }) {
  const { idea, call, progress } = item
  const owed = Math.max(0, progress.total - progress.submitted)
  return (
    <li className="relative flex flex-col gap-2.5 px-4 py-3 transition-colors duration-100 hover:bg-subtle sm:flex-row sm:items-center sm:gap-4">
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <div className="flex min-w-0 items-baseline gap-2">
          <span className="shrink-0 text-xs text-muted tabular-nums">{idea.key}</span>
          <Link
            to="/ideas/$ideaKey"
            params={{ ideaKey: idea.key }}
            search={{ tab: 'bids' }}
            {...{ [NAV_ITEM_ATTRIBUTE]: '' }}
            className={cn(
              'line-clamp-2 text-base font-medium text-primary outline-none sm:truncate',
              'after:absolute after:inset-0 after:content-[""]',
              'focus-visible:after:ring-2 focus-visible:after:ring-focus focus-visible:after:ring-inset',
            )}
          >
            {call.title}
          </Link>
        </div>
        <p className="truncate text-sm text-muted">
          {idea.project.name} · {item.sections.map((s) => s.title).join(', ')}
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 sm:shrink-0 sm:flex-nowrap">
        {/* The section's count is assessments to submit over every call, so each row
            leads with its share of it (P10-QA-N9). */}
        <span className="flex items-center gap-1.5 text-sm text-secondary tabular-nums">
          <Gavel aria-hidden="true" className="size-3.5 text-muted" />
          {owed} to submit
          <span className="text-muted">
            · {progress.submitted} of {progress.total} submitted
          </span>
        </span>
        <DueDateLabel value={item.due_at} hideWhenNone />
        <Button asChild variant="outline" className="relative z-10 ml-auto max-sm:h-11 max-sm:px-5">
          <Link
            to="/ideas/$ideaKey"
            params={{ ideaKey: idea.key }}
            search={{ tab: 'bids' }}
            aria-label={`Assess ${owed} ${owed === 1 ? 'bid section' : 'bid sections'}: ${call.title}`}
          >
            Assess
          </Link>
        </Button>
      </div>
    </li>
  )
}
