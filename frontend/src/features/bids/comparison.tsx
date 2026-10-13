import { useQueries } from '@tanstack/react-query'
import { CloudOff, Lock, TriangleAlert } from 'lucide-react'

import { api, unwrap } from '@/api/client'
import { useBidComparison, useBids, useSetBidAiInclusion } from '@/api/bids'
import { queryKeys } from '@/api/keys'
import type {
  BidAiAssessment,
  BidCallView,
  BidComparison,
  BidComparisonRow,
  BidSectionScore,
} from '@/api/types'
import { AiBadge } from '@/components/ui/ai-badge'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Callout } from '@/components/ui/callout'
import { EmptyState } from '@/components/ui/empty-state'
import { Skeleton, SkeletonGroup } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { toast } from '@/components/ui/toaster'
import { HoverTooltip } from '@/components/ui/tooltip'
import { useIdeaPage } from '@/features/idea/idea-context'
import { cn } from '@/lib/utils'

import { BID_STATUS, formatPoints, formatPrice, progressText } from './bid-copy'

type CallWithView = BidCallView & { call: NonNullable<BidCallView['call']> }

/**
 * Every bid side by side (contract-phase10 §8, `bid.view_scores`): section scores (0-100),
 * the total, the rank, disagreement, the AI's assessment with "Count in totals", and the
 * rejected bids apart with their reasons. Blind cells come back hidden; while you owe any
 * assessment there is no ranking at all (`ranking_hidden`).
 */
export function Comparison({
  view,
  onOpen,
}: {
  view: CallWithView
  onOpen: (bidId: string) => void
}) {
  const { ideaKey } = useIdeaPage()
  const comparison = useBidComparison(ideaKey)

  return (
    <section aria-labelledby="comparison-heading" className="flex flex-col gap-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="comparison-heading" className="text-lg font-semibold text-primary">
          Comparison
        </h2>
        {comparison.data && (
          <span className="text-sm text-muted">
            {progressText(comparison.data.progress)}
            {comparison.data.complete ? ' · complete' : ''}
          </span>
        )}
      </div>
      {comparison.isPending ? (
        <SkeletonGroup label="Loading the comparison" className="flex flex-col gap-2">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
        </SkeletonGroup>
      ) : comparison.isError ? (
        <EmptyState
          role="alert"
          size="inline"
          icon={<CloudOff />}
          title="We couldn’t load the comparison"
          action={
            <Button size="sm" onClick={() => void comparison.refetch()}>
              Try again
            </Button>
          }
          className="rounded-lg border"
        />
      ) : (
        <ComparisonTable comparison={comparison.data} view={view} onOpen={onOpen} />
      )}
    </section>
  )
}

function ComparisonTable({
  comparison,
  view,
  onOpen,
}: {
  comparison: BidComparison
  view: CallWithView
  onOpen: (bidId: string) => void
}) {
  const { ideaKey } = useIdeaPage()
  const bids = useBids(ideaKey)
  const active = comparison.rows.filter((row) => row.bid.status !== 'rejected')
  const rejected = comparison.rows.filter((row) => row.bid.status === 'rejected')
  const reasons = new Map((bids.data?.items ?? []).map((bid) => [bid.id, bid.rejection?.reason]))
  const ai = useQueries({
    queries: active.map((row) => ({
      queryKey: queryKeys.bids.ai(ideaKey, row.bid.id),
      queryFn: ({ signal }: { signal: AbortSignal }) =>
        unwrap(
          api.GET('/api/v1/ideas/{idea}/bid-call/bids/{bid_id}/ai-assessments', {
            params: { path: { idea: ideaKey, bid_id: row.bid.id } },
            signal,
          }),
        ),
    })),
  })
  const aiOf = (bidId: string) => {
    const index = active.findIndex((row) => row.bid.id === bidId)
    return ai[index]?.data
  }
  const showPrice = comparison.price_section_id !== null

  return (
    <div className="flex flex-col gap-4">
      {comparison.ranking_hidden && (
        <Callout
          tone="info"
          icon={<Lock />}
          title="The ranking shows once you have submitted your assessments"
        >
          You assess part of this call: the bids and sections you still owe are hidden from you, and
          so is every rank, until you submit them.
        </Callout>
      )}
      {active.length === 0 ? (
        <p className="rounded-lg border px-4 py-3 text-sm text-muted">No bids to compare yet.</p>
      ) : (
        <div className="rounded-lg border">
          <Table mobile="container-cards" aria-label="Bids compared">
            <TableHeader>
              <TableRow>
                <TableHead className="w-12">Rank</TableHead>
                <TableHead>Bidder</TableHead>
                {showPrice && <TableHead className="text-right">Price</TableHead>}
                {comparison.sections.map((section) => (
                  <TableHead key={section.id} className="text-right">
                    {section.title}{' '}
                    <span className="font-normal text-muted">{section.weight}%</span>
                  </TableHead>
                ))}
                <TableHead className="text-right">Total</TableHead>
                <TableHead>AI</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {active.map((row) => (
                <ComparisonRow
                  key={row.bid.id}
                  row={row}
                  comparison={comparison}
                  currency={comparison.currency}
                  showPrice={showPrice}
                  ai={aiOf(row.bid.id)}
                  onOpen={() => onOpen(row.bid.id)}
                />
              ))}
            </TableBody>
          </Table>
        </div>
      )}
      <p className="text-sm text-muted">
        Scores are 0-100: each section’s questions on 0-5, weighted, × 20; the total weights the
        sections. {showPrice && 'The price scores lowest qualified price ÷ this price × 5. '}
        Bids that don’t meet every must-have get no total.
      </p>
      {rejected.length > 0 && (
        <div className="flex flex-col gap-2">
          <h3 className="text-sm font-medium text-primary">Rejected bids</h3>
          <ul className="flex flex-col divide-y divide-subtle rounded-lg border">
            {rejected.map((row) => (
              <li
                key={row.bid.id}
                className="flex flex-wrap items-baseline gap-x-3 gap-y-1 px-4 py-2.5 text-sm"
              >
                <button
                  type="button"
                  className="font-medium text-primary underline-offset-4 hover:underline"
                  onClick={() => onOpen(row.bid.id)}
                >
                  {row.bid.bidder}
                </button>
                <span className="text-secondary">{reasons.get(row.bid.id) ?? 'Rejected'}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {view.call.status === 'awarded' && view.call.awarded_bid && (
        <p className="text-sm text-secondary">
          Awarded to{' '}
          <span className="font-medium text-primary">{view.call.awarded_bid.bidder}</span>
          {view.call.award_reason && `: ${view.call.award_reason}`}
        </p>
      )}
    </div>
  )
}

function SectionCell({ cell, label }: { cell: BidSectionScore; label: string }) {
  if (cell.hidden) {
    return (
      <TableCell label={label} className="text-right @max-3xl:text-left">
        <HoverTooltip content="Hidden until you submit your assessment of this section">
          <span
            role="img"
            aria-label="Hidden until you submit"
            className="inline-flex items-center gap-1 text-muted"
          >
            <Lock aria-hidden="true" className="size-3.5" />
          </span>
        </HoverTooltip>
      </TableCell>
    )
  }
  return (
    <TableCell label={label} className="text-right tabular-nums @max-3xl:text-left">
      <span className="inline-flex items-center gap-1.5">
        {cell.disagreement && (
          <HoverTooltip content="Assessors’ scores differ by 2 or more on a question">
            <span role="img" aria-label="Assessors disagree" className="text-warning">
              <TriangleAlert aria-hidden="true" className="size-3.5" />
            </span>
          </HoverTooltip>
        )}
        {formatPoints(cell.score)}
        {cell.score === null && cell.progress.total > 0 && (
          <span className="text-xs text-muted">
            {cell.progress.submitted}/{cell.progress.total}
          </span>
        )}
      </span>
    </TableCell>
  )
}

function ComparisonRow({
  row,
  comparison,
  currency,
  showPrice,
  ai,
  onOpen,
}: {
  row: BidComparisonRow
  comparison: BidComparison
  currency: string
  showPrice: boolean
  ai: { items: BidAiAssessment[]; can_include: boolean } | undefined
  onOpen: () => void
}) {
  const status = BID_STATUS[row.bid.status]
  return (
    <TableRow>
      <TableCell label="Rank" className="tabular-nums">
        {row.rank === null ? (
          <span className="text-muted">—</span>
        ) : (
          <span className={cn('font-semibold', row.rank === 1 && 'text-primary')}>
            {row.rank}
            {row.tied && <span className="font-normal text-muted"> tied</span>}
          </span>
        )}
      </TableCell>
      <TableCell primary>
        <span className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={onOpen}
            className="text-left font-medium text-primary underline-offset-4 hover:underline"
          >
            {row.bid.bidder}
          </button>
          {row.bid.status !== 'qualified' && <Badge variant={status.tone}>{status.label}</Badge>}
          {row.late && <Badge variant="warning">Late</Badge>}
        </span>
      </TableCell>
      {showPrice && (
        <TableCell label="Price" className="text-right tabular-nums @max-3xl:text-left">
          <span className="flex flex-col items-end @max-3xl:items-start">
            <span>{formatPrice(row.price, currency)}</span>
            {row.price_score !== null && (
              <span className="text-xs text-muted">{row.price_score.toFixed(2)} / 5</span>
            )}
          </span>
        </TableCell>
      )}
      {row.sections.map((cell) => (
        <SectionCell
          key={cell.section_id}
          cell={cell}
          label={comparison.sections.find((s) => s.id === cell.section_id)?.title ?? 'Section'}
        />
      ))}
      <TableCell label="Total" className="text-right tabular-nums @max-3xl:text-left">
        {row.total_hidden ? (
          <span role="img" aria-label="Hidden until you submit" className="text-muted">
            <Lock aria-hidden="true" className="inline size-3.5" />
          </span>
        ) : (
          <span className="font-semibold text-primary">{formatPoints(row.total)}</span>
        )}
      </TableCell>
      <TableCell label="AI">
        <AiCell row={row} ai={ai} />
      </TableCell>
    </TableRow>
  )
}

/** The AI's assessment of the bid: counted or not, with the switch for call managers. */
function AiCell({
  row,
  ai,
}: {
  row: BidComparisonRow
  ai: { items: BidAiAssessment[]; can_include: boolean } | undefined
}) {
  const { ideaKey } = useIdeaPage()
  const inclusion = useSetBidAiInclusion(ideaKey, row.bid.id)
  const assessment = ai?.items[0]
  if (!assessment) return <span className="text-sm text-muted">—</span>
  const label = assessment.included ? 'Counted' : 'Not counted'
  return (
    <span className="flex items-center gap-2 text-sm text-secondary">
      <AiBadge />
      {ai.can_include ? (
        <label className="flex items-center gap-2">
          <Switch
            checked={assessment.included}
            pending={inclusion.isPending}
            aria-label={`Count ${assessment.agent.display_name}’s assessment of ${row.bid.bidder} in the totals`}
            onCheckedChange={(include) =>
              inclusion.mutate(
                { assessmentId: assessment.id, include },
                {
                  onSuccess: () =>
                    toast.success(
                      include
                        ? `The AI’s scores for ${row.bid.bidder} now count`
                        : `The AI’s scores for ${row.bid.bidder} are left out`,
                    ),
                },
              )
            }
          />
          <span aria-hidden="true">{label}</span>
        </label>
      ) : (
        label
      )}
    </span>
  )
}
