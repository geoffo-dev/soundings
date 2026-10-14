import { useState } from 'react'

import { useCreateBid, useUpdateBid } from '@/api/bids'
import { describeError, isApiError } from '@/api/errors'
import type { Bid, BidCall } from '@/api/types'
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
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { toast } from '@/components/ui/toaster'

const pad = (n: number) => String(n).padStart(2, '0')

/** An ISO moment as the value of a `datetime-local` input (local time, minutes). */
export function toLocalInput(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/** A `datetime-local` value as an ISO moment with an offset (UTC); null when empty or invalid. */
export function fromLocalInput(value: string): string | null {
  if (!value) return null
  const d = new Date(value)
  return Number.isNaN(d.getTime()) ? null : d.toISOString()
}

const PRICE = /^\d{1,12}(\.\d{1,2})?$/

/** "120,000" or "120000.5" → "120000.50"; null when it isn't a price. */
export function normalisePrice(value: string): string | null {
  const plain = value.replace(/[,\s£$€]/g, '')
  if (!PRICE.test(plain) || Number(plain) <= 0) return null
  return Number(plain).toFixed(2)
}

export interface BidFormProblems {
  bidder?: string
  contact_name?: string
  contact_email?: string
  price?: string
  notes?: string
}

const EMAIL = /^[^@\s]+@[^@\s]+$/
// One line, no control characters (the API's SingleLine).
// eslint-disable-next-line no-control-regex
const NOT_ONE_LINE = /[\u0000-\u001f\u007f-\u009f\u2028\u2029]/

/** What the form can say before sending, from the current values (never stale). */
export function bidFormProblems(values: {
  bidder: string
  contactName: string
  contactEmail: string
  price: string
  notes: string
  hasPrice: boolean
}): BidFormProblems {
  const bidder = values.bidder.trim()
  const email = values.contactEmail.trim()
  const out: BidFormProblems = {}
  if (!bidder) out.bidder = 'Enter who sent the bid.'
  else if (bidder.length > 120) out.bidder = 'At most 120 characters.'
  else if (NOT_ONE_LINE.test(bidder)) out.bidder = 'One line of plain text.'
  if (values.contactName.trim().length > 120) out.contact_name = 'At most 120 characters.'
  else if (NOT_ONE_LINE.test(values.contactName)) out.contact_name = 'One line of plain text.'
  if (email && (!EMAIL.test(email) || email.length > 254))
    out.contact_email = 'An email address, like name@example.com.'
  if (values.hasPrice && values.price.trim() && !normalisePrice(values.price))
    out.price = 'A price above 0, like 120000 or 120000.50.'
  if (values.notes.trim().length > 2000) out.notes = 'At most 2,000 characters.'
  return out
}

/** The server's words for a field are a validator's ("String should match…"): ours instead. */
const FIELD_WORDS: Record<string, string> = {
  bidder: 'The bidder’s name: one line, at most 120 characters.',
  contact_name: 'A name: one line, at most 120 characters.',
  contact_email: 'An email address, like name@example.com.',
  received_at: 'A date and time in the past year, not in the future.',
  price: 'A price above 0, like 120000 or 120000.50.',
  notes: 'At most 2,000 characters of plain text.',
}

export function plainFieldErrors(fields: Record<string, string>): Record<string, string> {
  const out: Record<string, string> = {}
  for (const field of Object.keys(fields)) {
    const words = FIELD_WORDS[field]
    if (words) out[field] = words
  }
  return out
}

/**
 * Enter a bid as it came in (the team enters bids: P1), or edit one. Contact details are
 * stored as given and never emailed by Soundings. The price is asked only when the call's
 * template has a price question; it is scored automatically.
 */
export function BidFormDialog({
  ideaKey,
  call,
  bid,
  open,
  onOpenChange,
  onCreated,
}: {
  ideaKey: string
  call: BidCall
  /** Editing this bid; entering a new one when absent. */
  bid?: Bid
  open: boolean
  onOpenChange: (open: boolean) => void
  onCreated?: (bid: Bid) => void
}) {
  const create = useCreateBid(ideaKey)
  const update = useUpdateBid(ideaKey)
  const mutation = bid ? update : create
  const hasPrice = call.template.price_question_id !== null
  const [bidder, setBidder] = useState(bid?.bidder ?? '')
  const [contactName, setContactName] = useState(bid?.contact_name ?? '')
  const [contactEmail, setContactEmail] = useState(bid?.contact_email ?? '')
  const [received, setReceived] = useState(bid ? toLocalInput(bid.received_at) : '')
  const [price, setPrice] = useState(bid?.price ?? '')
  const [notes, setNotes] = useState(bid?.notes ?? '')
  const [submitted, setSubmitted] = useState(false)
  // The server's field errors in plain words; a field's own goes once it is changed, so a
  // corrected form can always be sent again (UX review M1).
  const [serverFields, setServerFields] = useState<Record<string, string>>({})
  const problems = bidFormProblems({ bidder, contactName, contactEmail, price, notes, hasPrice })
  const shown = (field: keyof BidFormProblems): string | undefined =>
    serverFields[field] ?? (submitted ? problems[field] : undefined)
  const edit = (field: string, set: (value: string) => void) => (value: string) => {
    set(value)
    if (mutation.error) mutation.reset()
    if (field in serverFields) {
      setServerFields((current) =>
        Object.fromEntries(Object.entries(current).filter(([key]) => key !== field)),
      )
    }
  }
  const onError = (error: unknown) => {
    if (isApiError(error)) setServerFields(plainFieldErrors(error.fieldErrors))
  }
  const general = mutation.error && Object.keys(serverFields).length === 0 ? mutation.error : null

  const save = () => {
    setSubmitted(true)
    if (mutation.isPending || Object.values(problems).some(Boolean)) return
    const priceValue = hasPrice && price.trim() ? normalisePrice(price) : null
    const body = {
      bidder: bidder.trim(),
      contact_name: contactName.trim(),
      contact_email: contactEmail.trim() || null,
      price: hasPrice ? priceValue : null,
      notes: notes.trim(),
    }
    if (bid) {
      // The stored moment is sent back unchanged unless corrected (it decides "late").
      const changed = received !== toLocalInput(bid.received_at)
      update.mutate(
        {
          bidId: bid.id,
          body: {
            ...body,
            received_at: changed ? (fromLocalInput(received) ?? bid.received_at) : bid.received_at,
          },
        },
        {
          onSuccess: () => {
            toast.success('Bid saved')
            onOpenChange(false)
          },
          onError,
        },
      )
    } else {
      create.mutate(
        { ...body, received_at: fromLocalInput(received) },
        {
          onSuccess: (created) => {
            toast.success(`Bid from ${created.bidder} entered`, {
              description: 'Upload its documents next.',
            })
            onOpenChange(false)
            onCreated?.(created)
          },
          onError,
        },
      )
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) {
          mutation.reset()
          setSubmitted(false)
          setServerFields({})
          if (!bid) {
            setBidder('')
            setContactName('')
            setContactEmail('')
            setReceived('')
            setPrice('')
            setNotes('')
          }
        }
        onOpenChange(next)
      }}
    >
      <DialogContent size="lg" mobile="fullscreen">
        <form
          noValidate
          className="flex min-h-0 flex-1 flex-col"
          onSubmit={(event) => {
            event.preventDefault()
            save()
          }}
        >
          <DialogHeader>
            <DialogTitle>{bid ? `Edit the bid from ${bid.bidder}` : 'Enter a bid'}</DialogTitle>
            <DialogDescription>
              As it came in. Contact details are kept for the call’s managers and never emailed by
              Soundings.
            </DialogDescription>
          </DialogHeader>
          <DialogBody className="flex flex-col gap-4">
            {general && (
              <Callout
                tone="danger"
                role="alert"
                title={(() => {
                  const { title, description } = describeError(general)
                  return description ? `${title}. ${description}` : title
                })()}
              />
            )}
            <Field
              label="Bidder"
              required
              description="The organisation that sent it."
              error={shown('bidder')}
            >
              <Input
                value={bidder}
                maxLength={130}
                autoComplete="off"
                placeholder="e.g. Northwind Fulfilment Ltd"
                onChange={(event) => edit('bidder', setBidder)(event.target.value)}
              />
            </Field>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Contact name" error={shown('contact_name')}>
                <Input
                  value={contactName}
                  maxLength={130}
                  autoComplete="off"
                  onChange={(event) => edit('contact_name', setContactName)(event.target.value)}
                />
              </Field>
              <Field label="Contact email" error={shown('contact_email')}>
                <Input
                  type="email"
                  value={contactEmail}
                  maxLength={260}
                  autoComplete="off"
                  onChange={(event) => edit('contact_email', setContactEmail)(event.target.value)}
                />
              </Field>
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field
                label="Received"
                description={
                  bid ? 'Correct it only if it was entered wrongly.' : 'Empty means now.'
                }
                error={serverFields.received_at}
              >
                <Input
                  type="datetime-local"
                  value={received}
                  onChange={(event) => edit('received_at', setReceived)(event.target.value)}
                />
              </Field>
              {hasPrice && (
                <Field
                  label={`Price (${call.currency})`}
                  description="The total from the pricing schedule. Scored automatically."
                  error={shown('price')}
                >
                  <Input
                    value={price}
                    inputMode="decimal"
                    autoComplete="off"
                    className="tabular-nums"
                    placeholder="120000.00"
                    onChange={(event) => edit('price', setPrice)(event.target.value)}
                  />
                </Field>
              )}
            </div>
            <Field label="Notes" description="For the call’s managers only." error={shown('notes')}>
              <Textarea
                value={notes}
                maxLength={2010}
                minRows={2}
                onChange={(event) => edit('notes', setNotes)(event.target.value)}
              />
            </Field>
          </DialogBody>
          <DialogFooter>
            <Button variant="ghost" type="button" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button variant="primary" type="submit" loading={mutation.isPending}>
              {bid ? 'Save' : 'Enter the bid'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
