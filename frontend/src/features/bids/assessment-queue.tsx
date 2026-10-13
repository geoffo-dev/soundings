import { CheckCircle2, CircleDashed, PencilLine } from 'lucide-react'

import { useBids } from '@/api/bids'
import type { BidCall, EvaluatorState } from '@/api/types'
import { Button } from '@/components/ui/button'
import { DueDateLabel } from '@/components/ui/due-date'
import { Skeleton, SkeletonGroup } from '@/components/ui/skeleton'

const STATE: Record<EvaluatorState, { label: string; action: string; Icon: typeof CircleDashed }> =
  {
    invited: { label: 'Not started', action: 'Assess', Icon: CircleDashed },
    draft: { label: 'Draft saved', action: 'Continue', Icon: PencilLine },
    submitted: { label: 'Submitted', action: 'View', Icon: CheckCircle2 },
  }

/**
 * An assessor's queue (contract-phase10 §7): their sections for every bid that isn't
 * rejected, with where they are with each. Each row opens the assessment of that bid and
 * section; scores stay hidden until they submit.
 */
export function AssessmentQueue({
  ideaKey,
  call,
  canAssess,
  onAssess,
}: {
  ideaKey: string
  call: BidCall
  /** The call is being assessed (else the queue says when it opens). */
  canAssess: boolean
  onAssess: (bidId: string, sectionId: string) => void
}) {
  const bids = useBids(ideaKey)
  const rows = (bids.data?.items ?? [])
    .filter((bid) => bid.status !== 'rejected')
    .flatMap((bid) => bid.my_sections.map((section) => ({ bid, section })))
  const done = rows.filter((row) => row.section.state === 'submitted').length

  return (
    <section aria-labelledby="my-assessments-heading" className="flex flex-col gap-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="my-assessments-heading" className="text-lg font-semibold text-primary">
          Your assessments
        </h2>
        <span className="flex items-center gap-3 text-sm text-muted">
          {rows.length > 0 && (
            <span className="tabular-nums">
              {done} of {rows.length} submitted
            </span>
          )}
          {call.assessment_due_at && done < rows.length && call.status === 'assessing' && (
            <DueDateLabel value={call.assessment_due_at} />
          )}
        </span>
      </div>
      {!canAssess && call.status !== 'awarded' && call.status !== 'cancelled' && (
        <p className="text-sm text-muted">
          You can assess once the call is closed to new bids
          {call.status === 'draft' ? ' (it isn’t open yet)' : ''}.
        </p>
      )}
      {bids.isPending ? (
        <SkeletonGroup label="Loading your assessments" className="flex flex-col gap-2">
          <Skeleton className="h-11 w-full rounded-lg" />
          <Skeleton className="h-11 w-full rounded-lg" />
        </SkeletonGroup>
      ) : rows.length === 0 ? (
        <p className="rounded-lg border px-4 py-3 text-sm text-muted">No bids to assess yet.</p>
      ) : (
        <ul
          className="flex flex-col divide-y divide-subtle rounded-lg border"
          aria-label="Your assessments"
        >
          {rows.map(({ bid, section }) => {
            const state = STATE[section.state]
            return (
              <li
                key={`${bid.id}:${section.section.id}`}
                className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-2.5"
              >
                <div className="flex min-w-0 flex-1 flex-col">
                  <span className="truncate text-sm font-medium text-primary">{bid.bidder}</span>
                  <span className="text-xs text-muted">{section.section.title}</span>
                </div>
                <span className="flex items-center gap-1.5 text-sm text-secondary">
                  <state.Icon
                    aria-hidden="true"
                    className={
                      section.state === 'submitted' ? 'size-4 text-success' : 'size-4 text-muted'
                    }
                  />
                  {state.label}
                </span>
                <Button
                  size="sm"
                  variant={section.state === 'submitted' ? 'ghost' : 'outline'}
                  disabled={!canAssess && section.state !== 'submitted'}
                  aria-label={`${state.action}: ${bid.bidder}, ${section.section.title}`}
                  onClick={() => onAssess(bid.id, section.section.id)}
                >
                  {state.action}
                </Button>
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
