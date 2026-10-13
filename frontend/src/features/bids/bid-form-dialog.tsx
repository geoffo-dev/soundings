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
  const fields = isApiError(mutation.error) ? mutation.error.fieldErrors : {}

  const bidderError =
    fields.bidder ?? (submitted && !bidder.trim() ? 'Enter who sent the bid.' : undefined)
  const priceValue = price.trim() ? normalisePrice(price) : null
  const priceError =
    fields.price ??
    (submitted && hasPrice && price.trim() && !priceValue
      ? 'A price above 0, like 120000 or 120000.50.'
      : undefined)
  const emailError =
    fields.contact_email ??
    (submitted && contactEmail.trim() && !/^[^@\s]+@[^@\s]+$/.test(contactEmail.trim())
      ? 'An email address, like name@example.com.'
      : undefined)

  const save = () => {
    setSubmitted(true)
    if (!bidder.trim() || priceError || emailError || mutation.isPending) return
    if (hasPrice && price.trim() && !priceValue) return
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
        },
      )
    } else {
      create.mutate(
        { ...body, received_at: fromLocalInput(received) },
        {
          onSuccess: (created) => {
            toast.success(`${created.bidder}’s bid entered`, {
              description: 'Upload its documents next.',
            })
            onOpenChange(false)
            onCreated?.(created)
          },
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
            <DialogTitle>{bid ? `Edit ${bid.bidder}’s bid` : 'Enter a bid'}</DialogTitle>
            <DialogDescription>
              As it came in. Contact details are kept for the call’s managers and never emailed by
              Soundings.
            </DialogDescription>
          </DialogHeader>
          <DialogBody className="flex flex-col gap-4">
            {mutation.error && Object.keys(fields).length === 0 && (
              <Callout
                tone="danger"
                role="alert"
                title={(() => {
                  const { title, description } = describeError(mutation.error)
                  return description ? `${title}. ${description}` : title
                })()}
              />
            )}
            <Field
              label="Bidder"
              required
              description="The organisation that sent it."
              error={bidderError}
            >
              <Input
                value={bidder}
                maxLength={130}
                autoComplete="off"
                placeholder="e.g. Northwind Fulfilment Ltd"
                onChange={(event) => setBidder(event.target.value)}
              />
            </Field>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Contact name" error={fields.contact_name}>
                <Input
                  value={contactName}
                  maxLength={130}
                  autoComplete="off"
                  onChange={(event) => setContactName(event.target.value)}
                />
              </Field>
              <Field label="Contact email" error={emailError}>
                <Input
                  type="email"
                  value={contactEmail}
                  maxLength={260}
                  autoComplete="off"
                  onChange={(event) => setContactEmail(event.target.value)}
                />
              </Field>
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field
                label="Received"
                description={
                  bid ? 'Correct it only if it was entered wrongly.' : 'Leave empty for now.'
                }
                error={fields.received_at}
              >
                <Input
                  type="datetime-local"
                  value={received}
                  onChange={(event) => setReceived(event.target.value)}
                />
              </Field>
              {hasPrice && (
                <Field
                  label={`Price (${call.currency})`}
                  description="The total from the pricing schedule. Scored automatically."
                  error={priceError}
                >
                  <Input
                    value={price}
                    inputMode="decimal"
                    autoComplete="off"
                    className="tabular-nums"
                    placeholder="120000.00"
                    onChange={(event) => setPrice(event.target.value)}
                  />
                </Field>
              )}
            </div>
            <Field label="Notes" description="For the call’s managers only." error={fields.notes}>
              <Textarea
                value={notes}
                maxLength={2010}
                minRows={2}
                onChange={(event) => setNotes(event.target.value)}
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
