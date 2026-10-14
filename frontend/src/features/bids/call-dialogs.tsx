import { useState } from 'react'

import { useCancelBidCall, useCreateBidCall, useDeleteBidCall, useUpdateBidCall } from '@/api/bids'
import { describeError, isApiError } from '@/api/errors'
import type { AiAgentRef, BidCall } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Callout } from '@/components/ui/callout'
import { DatePicker } from '@/components/ui/date-picker'
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
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { toast } from '@/components/ui/toaster'
import { focusWhenRendered } from '@/lib/focus'
import { latestDueInput } from '@/features/idea/due-date'

import { useCallZone } from './call-dates'

const NO_AGENT = 'none'

function problemText(error: unknown): string | null {
  if (!error) return null
  const { title, description } = describeError(error)
  return description ? `${title}. ${description}` : title
}

/** "Start a call for bids": a draft with a copy of the project's bid template. */
export function CreateCallDialog({
  ideaKey,
  ideaTitle,
  open,
  onOpenChange,
}: {
  ideaKey: string
  ideaTitle: string
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const create = useCreateBidCall(ideaKey)
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [currency, setCurrency] = useState('GBP')
  const [submitted, setSubmitted] = useState(false)
  const fields = isApiError(create.error) ? create.error.fieldErrors : {}
  const titleError =
    fields.title ?? (submitted && !title.trim() ? 'Give the call a title.' : undefined)
  const currencyError =
    fields.currency ??
    (submitted && !/^[A-Z]{3}$/.test(currency.trim())
      ? 'Three capital letters, e.g. GBP.'
      : undefined)

  const reset = () => {
    setTitle('')
    setDescription('')
    setCurrency('GBP')
    setSubmitted(false)
    create.reset()
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) reset()
        onOpenChange(next)
      }}
    >
      <DialogContent size="lg" mobile="fullscreen">
        <form
          noValidate
          className="flex min-h-0 flex-1 flex-col"
          onSubmit={(event) => {
            event.preventDefault()
            setSubmitted(true)
            if (!title.trim() || !/^[A-Z]{3}$/.test(currency.trim()) || create.isPending) return
            create.mutate(
              { title: title.trim(), description: description.trim(), currency: currency.trim() },
              {
                onSuccess: () => {
                  toast.success('Call for bids started', {
                    description:
                      'It’s a draft: check the evaluation template, then open it to bids.',
                  })
                  reset()
                  onOpenChange(false)
                  // The "Start" button went with the empty state: to the call's next step.
                  focusWhenRendered(
                    () =>
                      document.getElementById('bid-call-primary') ??
                      document.getElementById('bid-call-title'),
                    { force: true },
                  )
                },
              },
            )
          }}
        >
          <DialogHeader>
            <DialogTitle>Start a call for bids</DialogTitle>
            <DialogDescription>
              For “{ideaTitle}”. It starts as a draft with a copy of the project’s bid evaluation
              template, which you can change for this call.
            </DialogDescription>
          </DialogHeader>
          <DialogBody className="flex flex-col gap-4">
            {create.error && Object.keys(fields).length === 0 && (
              <Callout tone="danger" title={problemText(create.error)} role="alert" />
            )}
            <Field label="Title" required error={titleError}>
              <Input
                value={title}
                maxLength={130}
                placeholder="e.g. Fulfilment partner for subscription boxes"
                autoComplete="off"
                onChange={(event) => setTitle(event.target.value)}
              />
            </Field>
            <Field
              label="What is being bought"
              description="Plain text, shown to the call’s assessors."
              error={fields.description}
            >
              <Textarea
                value={description}
                maxLength={2010}
                minRows={3}
                onChange={(event) => setDescription(event.target.value)}
              />
            </Field>
            <Field
              label="Currency"
              description="A label for prices (no conversion)."
              error={currencyError}
              className="max-w-40"
            >
              <Input
                value={currency}
                maxLength={3}
                autoComplete="off"
                className="uppercase"
                onChange={(event) => setCurrency(event.target.value.toUpperCase())}
              />
            </Field>
          </DialogBody>
          <DialogFooter>
            <Button variant="ghost" type="button" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button variant="primary" type="submit" loading={create.isPending}>
              Start the call
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

/**
 * The call's settings: title, description, currency, the deadline for bids (a day,
 * "by the end of it"; frozen once the call is closed to new bids) and the AI assessor.
 */
export function CallSettingsDialog({
  ideaKey,
  call,
  agents,
  open,
  onOpenChange,
  reason,
  onSaved,
}: {
  ideaKey: string
  call: BidCall
  agents: readonly AiAgentRef[]
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Why it opened ("Set a deadline to open the call"). */
  reason?: string
  /** Runs after a save (opened by "Open the call": then it opens the call, "Save and open"). */
  onSaved?: () => void
}) {
  const update = useUpdateBidCall(ideaKey)
  const zone = useCallZone()
  const [title, setTitle] = useState(call.title)
  const [description, setDescription] = useState(call.description)
  const [currency, setCurrency] = useState(call.currency)
  const [deadline, setDeadline] = useState(zone.toInput(call.deadline_at))
  const [assessor, setAssessor] = useState(call.ai_assessor?.id ?? NO_AGENT)
  const [submitted, setSubmitted] = useState(false)
  const fields = isApiError(update.error) ? update.error.fieldErrors : {}
  const frozen = call.status === 'assessing'
  const choices = [
    ...agents,
    ...(call.ai_assessor && !agents.some((a) => a.id === call.ai_assessor?.id)
      ? [call.ai_assessor]
      : []),
  ]
  const titleError =
    fields.title ?? (submitted && !title.trim() ? 'Give the call a title.' : undefined)

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) update.reset()
        onOpenChange(next)
      }}
    >
      <DialogContent size="lg" mobile="fullscreen">
        <form
          noValidate
          className="flex min-h-0 flex-1 flex-col"
          onSubmit={(event) => {
            event.preventDefault()
            setSubmitted(true)
            if (!title.trim() || (onSaved && !deadline) || update.isPending) return
            update.mutate(
              {
                title: title.trim(),
                description: description.trim(),
                currency: currency.trim(),
                // Unchanged: the stored moment as it is (a frozen deadline must not move).
                deadline_at:
                  deadline === zone.toInput(call.deadline_at)
                    ? call.deadline_at
                    : zone.fromInput(deadline),
                ai_assessor_id: assessor === NO_AGENT ? null : assessor,
              },
              {
                onSuccess: () => {
                  onOpenChange(false)
                  if (onSaved) onSaved()
                  else toast.success('Call saved')
                },
              },
            )
          }}
        >
          <DialogHeader>
            <DialogTitle>Call details</DialogTitle>
            <DialogDescription>{reason ?? 'Changes apply at once.'}</DialogDescription>
          </DialogHeader>
          <DialogBody className="flex flex-col gap-4">
            {update.error && Object.keys(fields).length === 0 && (
              <Callout tone="danger" title={problemText(update.error)} role="alert" />
            )}
            <Field label="Title" required error={titleError}>
              <Input
                value={title}
                maxLength={130}
                autoComplete="off"
                onChange={(event) => setTitle(event.target.value)}
              />
            </Field>
            <Field label="What is being bought" error={fields.description}>
              <Textarea
                value={description}
                maxLength={2010}
                minRows={3}
                onChange={(event) => setDescription(event.target.value)}
              />
            </Field>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field
                label="Deadline for bids"
                description={
                  frozen
                    ? 'Fixed once the call is closed to new bids.'
                    : `Bids received after the end of this day${zone.differs ? ` (${zone.timeZone} time)` : ''} are marked late, not refused.`
                }
                error={
                  fields.deadline_at ??
                  (submitted && onSaved && !deadline ? 'Pick the last day for bids.' : undefined)
                }
              >
                <DatePicker
                  value={deadline}
                  onValueChange={setDeadline}
                  min={zone.pickerMin(deadline)}
                  max={latestDueInput()}
                  disabled={frozen}
                />
              </Field>
              <Field label="Currency" description="A label for prices." error={fields.currency}>
                <Input
                  value={currency}
                  maxLength={3}
                  autoComplete="off"
                  className="uppercase"
                  onChange={(event) => setCurrency(event.target.value.toUpperCase())}
                />
              </Field>
            </div>
            <Field
              label="AI assessor"
              description={
                choices.length === 0
                  ? 'No AI agent assesses bids in this project. A platform admin can register one.'
                  : 'Pre-checks each bid once its documents are read: one automatic assessment per bid, left out of the totals until you include it.'
              }
              error={fields.ai_assessor_id}
            >
              <Select value={assessor} onValueChange={setAssessor} disabled={choices.length === 0}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={NO_AGENT}>None</SelectItem>
                  {choices.map((agent) => (
                    <SelectItem key={agent.id} value={agent.id}>
                      {agent.display_name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>
          </DialogBody>
          <DialogFooter>
            <Button variant="ghost" type="button" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button variant="primary" type="submit" loading={update.isPending}>
              {onSaved ? 'Save and open' : 'Save'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

/** Cancel the call: it becomes read-only; an optional reason for the call managers. */
export function CancelCallDialog({
  ideaKey,
  open,
  onOpenChange,
}: {
  ideaKey: string
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const cancel = useCancelBidCall(ideaKey)
  const [reason, setReason] = useState('')
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="sm" role="alertdialog">
        <DialogHeader>
          <DialogTitle>Cancel the call for bids?</DialogTitle>
          <DialogDescription>
            It becomes read-only: no more bids, assessments or award. Its bids and documents stay
            until the call is deleted.
          </DialogDescription>
        </DialogHeader>
        <DialogBody>
          <Field label="Reason" description="Optional. Only call managers see it.">
            <Textarea
              value={reason}
              maxLength={510}
              minRows={2}
              onChange={(event) => setReason(event.target.value)}
            />
          </Field>
        </DialogBody>
        <DialogFooter className="pt-5">
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Keep it
          </Button>
          <Button
            variant="destructive"
            loading={cancel.isPending}
            onClick={() =>
              cancel.mutate(reason.trim(), {
                onSuccess: () => {
                  toast.success('Call cancelled')
                  onOpenChange(false)
                },
              })
            }
          >
            Cancel the call
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/** Delete the call with every bid and document in it (no undo). */
export function DeleteCallDialog({
  ideaKey,
  call,
  open,
  onOpenChange,
}: {
  ideaKey: string
  call: Pick<BidCall, 'title' | 'bid_count' | 'status'>
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const remove = useDeleteBidCall(ideaKey)
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="sm" role="alertdialog">
        <DialogHeader>
          <DialogTitle>Delete “{call.title}”?</DialogTitle>
          <DialogDescription>
            {call.bid_count > 0
              ? `Its ${call.bid_count} ${call.bid_count === 1 ? 'bid' : 'bids'}, their documents and every assessment go with it. This can’t be undone.`
              : 'This can’t be undone.'}
          </DialogDescription>
        </DialogHeader>
        <DialogFooter className="pt-5">
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Keep it
          </Button>
          <Button
            variant="destructive"
            loading={remove.isPending}
            onClick={() =>
              remove.mutate(undefined, {
                onSuccess: () => {
                  toast.success('Call for bids deleted')
                  onOpenChange(false)
                },
              })
            }
          >
            Delete the call
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/** Opening, closing to new bids and reopening ask first: each changes who can do what. */
export function MoveCallDialog({
  move,
  open,
  onOpenChange,
  onConfirm,
  pending,
}: {
  move: 'open' | 'assessing' | 'reopen'
  open: boolean
  onOpenChange: (open: boolean) => void
  onConfirm: () => void
  pending: boolean
}) {
  const copy = {
    open: {
      title: 'Open the call to bids?',
      description:
        'You can then enter the bids that come in. Bids received after the deadline are marked late.',
      action: 'Open the call',
    },
    assessing: {
      title: 'Close the call to new bids?',
      description:
        'No more bids can be entered and the deadline is fixed. The assessors can start scoring their sections.',
      action: 'Close to new bids',
    },
    reopen: {
      title: 'Reopen the call to new bids?',
      description:
        'Assessors stop until you close it again. Nobody has submitted an assessment yet.',
      action: 'Reopen the call',
    },
  }[move]
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="sm" role="alertdialog">
        <DialogHeader>
          <DialogTitle>{copy.title}</DialogTitle>
          <DialogDescription>{copy.description}</DialogDescription>
        </DialogHeader>
        <DialogFooter className="pt-5">
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Not now
          </Button>
          <Button variant="primary" loading={pending} onClick={onConfirm}>
            {copy.action}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
