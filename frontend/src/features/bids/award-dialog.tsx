import { useState } from 'react'

import { useAwardBidCall, useBidComparison } from '@/api/bids'
import { describeError } from '@/api/errors'
import type { BidCallView } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Callout } from '@/components/ui/callout'
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Field } from '@/components/ui/field'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { Skeleton } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'
import { toast } from '@/components/ui/toaster'
import { useIdeaPage } from '@/features/idea/idea-context'

import { formatPoints, formatPrice } from './bid-copy'

type CallWithView = BidCallView & { call: NonNullable<BidCallView['call']> }

/**
 * Award the call to one qualified bid (contract-phase10 §3.3, session only). Outstanding
 * assessments don't block it, but the dialog says how many there are; ties are never
 * broken for you. The other bids become unsuccessful and the call read-only.
 */
export function AwardDialog({
  view,
  open,
  onOpenChange,
  onAwarded,
}: {
  view: CallWithView
  open: boolean
  onOpenChange: (open: boolean) => void
  /** After the award (the Award button is gone: focus goes to the header's next step). */
  onAwarded?: () => void
}) {
  const { ideaKey } = useIdeaPage()
  const comparison = useBidComparison(ideaKey, { enabled: open })
  const award = useAwardBidCall(ideaKey)
  const [choice, setChoice] = useState<string>('')
  const [reason, setReason] = useState('')
  const rows = (comparison.data?.rows ?? []).filter((row) => row.bid.status === 'qualified')
  const outstanding = comparison.data
    ? Math.max(0, comparison.data.progress.total - comparison.data.progress.submitted)
    : 0
  const chosen = rows.find((row) => row.bid.id === choice)

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) {
          award.reset()
          setChoice('')
          setReason('')
        }
        onOpenChange(next)
      }}
    >
      <DialogContent size="lg" mobile="fullscreen">
        <DialogHeader>
          <DialogTitle>Award the call</DialogTitle>
          <DialogDescription>
            Choose the winning bid. The others become unsuccessful and the call becomes read-only.
            Only bids that meet every must-have can be awarded.
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="flex flex-col gap-4">
          {award.error && (
            <Callout
              tone="danger"
              role="alert"
              title={(() => {
                const { title, description } = describeError(award.error)
                return description ? `${title}. ${description}` : title
              })()}
            />
          )}
          {outstanding > 0 && (
            <Callout
              tone="warning"
              title={`${outstanding} ${outstanding === 1 ? 'assessment is' : 'assessments are'} outstanding`}
            >
              You can still award now; their scores won’t count.
            </Callout>
          )}
          {comparison.data?.ranking_hidden && (
            <Callout tone="info" title="You still owe assessments, so there is no ranking for you">
              The totals of bids you haven’t assessed are hidden until you submit.
            </Callout>
          )}
          {comparison.isPending ? (
            <div className="flex flex-col gap-2" role="status" aria-label="Loading the bids">
              <Skeleton className="h-12 w-full" />
              <Skeleton className="h-12 w-full" />
            </div>
          ) : rows.length === 0 ? (
            <p className="text-sm text-muted">
              No bid meets every must-have yet, so none can be awarded.
            </p>
          ) : (
            <Field label="Winning bid">
              <RadioGroup value={choice} onValueChange={setChoice} className="flex flex-col gap-2">
                {rows.map((row) => (
                  <label
                    key={row.bid.id}
                    htmlFor={`award-${row.bid.id}`}
                    className="flex cursor-pointer items-center gap-3 rounded-lg border px-3 py-2.5 transition-colors hover:bg-subtle has-[[data-state=checked]]:border-accent-control has-[[data-state=checked]]:bg-subtle"
                  >
                    <RadioGroupItem
                      id={`award-${row.bid.id}`}
                      value={row.bid.id}
                      aria-label={row.bid.bidder}
                    />
                    <span className="flex min-w-0 flex-1 flex-col">
                      <span className="truncate text-sm font-medium text-primary">
                        {row.bid.bidder}
                      </span>
                      <span className="text-xs text-muted">
                        {[
                          row.rank !== null ? `Rank ${row.rank}${row.tied ? ' (tied)' : ''}` : null,
                          row.total_hidden
                            ? 'Total hidden until you submit'
                            : `Total ${formatPoints(row.total)}`,
                          row.price !== null ? formatPrice(row.price, view.call.currency) : null,
                        ]
                          .filter(Boolean)
                          .join(' · ')}
                      </span>
                    </span>
                  </label>
                ))}
              </RadioGroup>
            </Field>
          )}
          <Field
            label="Reason"
            description="Optional. Kept with the award for the call’s managers and in the report."
          >
            <Textarea
              value={reason}
              maxLength={510}
              minRows={2}
              onChange={(event) => setReason(event.target.value)}
            />
          </Field>
        </DialogBody>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            variant="primary"
            disabled={!chosen}
            loading={award.isPending}
            onClick={() => {
              if (!chosen) return
              award.mutate(
                { bid_id: chosen.bid.id, reason: reason.trim() },
                {
                  onSuccess: () => {
                    toast.success(`Awarded to ${chosen.bid.bidder}`)
                    onOpenChange(false)
                    onAwarded?.()
                  },
                },
              )
            }}
          >
            {chosen ? `Award to ${chosen.bid.bidder}` : 'Award'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
