import { useState } from 'react'

import { useRejectBid } from '@/api/bids'
import { describeError, isApiError } from '@/api/errors'
import type { Bid } from '@/api/types'
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
import { Textarea } from '@/components/ui/textarea'
import { toast } from '@/components/ui/toaster'

/**
 * Reject a bid in one step with a reason (P2; session only). Reversible ("Reinstate")
 * until the award; the reason is kept, and only call managers read it.
 */
export function RejectDialog({
  ideaKey,
  bid,
  suggestion,
  open,
  onOpenChange,
}: {
  ideaKey: string
  bid: Pick<Bid, 'id' | 'bidder'>
  /** A first reason, e.g. "Missing: Insurance certificate." */
  suggestion?: string
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const reject = useRejectBid(ideaKey)
  const [reason, setReason] = useState(suggestion ?? '')
  const [submitted, setSubmitted] = useState(false)
  const fields = isApiError(reject.error) ? reject.error.fieldErrors : {}
  const error =
    fields.reason ?? (submitted && !reason.trim() ? 'Say why, in a few words.' : undefined)

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (next) {
          setReason(suggestion ?? '')
          setSubmitted(false)
        } else reject.reset()
        onOpenChange(next)
      }}
    >
      <DialogContent size="md">
        <form
          noValidate
          className="flex min-h-0 flex-1 flex-col"
          onSubmit={(event) => {
            event.preventDefault()
            setSubmitted(true)
            if (!reason.trim() || reject.isPending) return
            reject.mutate(
              { bidId: bid.id, reason: reason.trim() },
              {
                onSuccess: () => {
                  toast.success(`Bid from ${bid.bidder} rejected`, {
                    description:
                      'It left the assessors’ queues. Reinstate it from the bid if needed.',
                  })
                  onOpenChange(false)
                },
              },
            )
          }}
        >
          <DialogHeader>
            <DialogTitle>Reject the bid from {bid.bidder}?</DialogTitle>
            <DialogDescription>
              It leaves the assessors’ queues, the totals and the ranking. Its assessments are kept,
              and you can reinstate it until the call is awarded.
            </DialogDescription>
          </DialogHeader>
          <DialogBody className="flex flex-col gap-3">
            {reject.error && Object.keys(fields).length === 0 && (
              <Callout
                tone="danger"
                role="alert"
                title={(() => {
                  const { title, description } = describeError(reject.error)
                  return description ? `${title}. ${description}` : title
                })()}
              />
            )}
            <Field
              label="Reason"
              required
              description="Only the call’s managers read it."
              error={error}
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
            <Button variant="ghost" type="button" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button variant="destructive" type="submit" loading={reject.isPending}>
              Reject the bid
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
