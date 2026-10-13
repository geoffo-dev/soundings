import {
  CheckCircle2,
  CircleDashed,
  FileQuestion,
  MoreHorizontal,
  Pencil,
  PencilLine,
  RotateCcw,
  Trash2,
  TriangleAlert,
  XCircle,
} from 'lucide-react'
import { useState } from 'react'

import { useBid, useDeleteBid, useReinstateBid } from '@/api/bids'
import { describeError, isApiError } from '@/api/errors'
import type { BidCall, BidCallView, BidDetail, BidDocument, EvaluatorState } from '@/api/types'
import { Badge } from '@/components/ui/badge'
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
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { EmptyState } from '@/components/ui/empty-state'
import { RelativeTime } from '@/components/ui/relative-time'
import {
  Sheet,
  SheetBody,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import { Skeleton, SkeletonGroup } from '@/components/ui/skeleton'
import { toast } from '@/components/ui/toaster'
import { useIdeaPage } from '@/features/idea/idea-context'
import { formatDateTime } from '@/lib/dates'

import { BidAi } from './bid-ai'
import { BID_STATUS, formatPrice } from './bid-copy'
import { BidDocuments, pricingAudience } from './bid-documents'
import { BidFormDialog } from './bid-form-dialog'
import { DocumentTextDialog } from './document-text'
import { MustHaves, rejectionSuggestion } from './must-haves'
import { RejectDialog } from './reject-dialog'
import { useDocumentUploads } from './use-document-uploads'

type CallWithView = BidCallView & { call: NonNullable<BidCallView['call']> }

const SECTION_STATE: Record<
  EvaluatorState,
  { label: string; action: string; Icon: typeof CircleDashed }
> = {
  invited: { label: 'Not started', action: 'Assess', Icon: CircleDashed },
  draft: { label: 'Draft saved', action: 'Continue', Icon: PencilLine },
  submitted: { label: 'Submitted', action: 'View', Icon: CheckCircle2 },
}

/**
 * One bid, opened from the list (`?tab=bids&bid=<id>`): its details and price (where
 * allowed), the must-have checklist, the documents and, for call managers, the AI's
 * assessment, with Edit, Reject / Reinstate and Delete. Assessors start their sections
 * from here.
 */
export function BidSheet({
  view,
  bidId,
  onOpenChange,
  onAssess,
}: {
  view: CallWithView
  bidId: string | undefined
  onOpenChange: (open: boolean) => void
  onAssess: (bidId: string, sectionId: string) => void
}) {
  const { ideaKey } = useIdeaPage()
  const query = useBid(ideaKey, bidId ?? null)
  const missing = isApiError(query.error) && query.error.status === 404

  return (
    <Sheet open={Boolean(bidId)} onOpenChange={onOpenChange}>
      <SheetContent size="lg" aria-describedby={undefined}>
        {query.data ? (
          <BidDetailView
            key={query.data.id}
            view={view}
            bid={query.data}
            onClose={() => onOpenChange(false)}
            onAssess={onAssess}
          />
        ) : query.isError ? (
          <>
            <SheetHeader>
              <SheetTitle>{missing ? 'Bid not found' : 'Couldn’t load the bid'}</SheetTitle>
            </SheetHeader>
            <SheetBody>
              <EmptyState
                role="alert"
                size="compact"
                icon={<FileQuestion />}
                title={missing ? 'This bid isn’t there any more' : 'We couldn’t load this bid'}
                description={
                  missing
                    ? 'It may have been deleted, or rejected (assessors don’t see rejected bids).'
                    : describeError(query.error).title
                }
                action={
                  missing ? (
                    <Button variant="secondary" onClick={() => onOpenChange(false)}>
                      Back to the bids
                    </Button>
                  ) : (
                    <Button variant="secondary" onClick={() => void query.refetch()}>
                      Try again
                    </Button>
                  )
                }
              />
            </SheetBody>
          </>
        ) : (
          <>
            <SheetHeader>
              <SheetTitle className="sr-only">Loading the bid</SheetTitle>
              <Skeleton className="h-5 w-56" />
              <Skeleton className="h-3.5 w-40" />
            </SheetHeader>
            <SheetBody>
              <SkeletonGroup label="Loading the bid" className="flex flex-col gap-6">
                {[0, 1, 2].map((i) => (
                  <div key={i} className="flex flex-col gap-2">
                    <Skeleton className="h-4 w-28" />
                    <Skeleton className="h-10 w-full" />
                    <Skeleton className="h-10 w-4/5" />
                  </div>
                ))}
              </SkeletonGroup>
            </SheetBody>
          </>
        )}
      </SheetContent>
    </Sheet>
  )
}

function BidDetailView({
  view,
  bid,
  onClose,
  onAssess,
}: {
  view: CallWithView
  bid: BidDetail
  onClose: () => void
  onAssess: (bidId: string, sectionId: string) => void
}) {
  const { ideaKey } = useIdeaPage()
  const { call } = view
  const uploads = useDocumentUploads(ideaKey, bid.id, bid.documents.length)
  const [dialog, setDialog] = useState<'edit' | 'reject' | 'delete' | null>(null)
  const [reading, setReading] = useState<BidDocument | null>(null)
  const reinstate = useReinstateBid(ideaKey)
  const status = BID_STATUS[bid.status]
  const manager = view.permissions.can_view_scores
  const rejected = bid.status === 'rejected'
  const suggestion = rejectionSuggestion(bid)
  const showSuggest = bid.permissions.reject_suggested && bid.permissions.can_reject

  return (
    <>
      <SheetHeader>
        <SheetTitle className="pr-8 break-words">{bid.bidder}</SheetTitle>
        <SheetDescription asChild>
          <div className="flex flex-wrap items-center gap-2 text-sm text-muted">
            <Badge variant={status.tone}>{status.label}</Badge>
            {/* "Arrived": the status chip may already say "Received" (P10-QA-N6). */}
            <span>Arrived {formatDateTime(bid.received_at)}</span>
            {bid.late && <Badge variant="warning">Late</Badge>}
          </div>
        </SheetDescription>
      </SheetHeader>
      <SheetBody className="flex flex-col gap-8">
        {rejected && bid.rejection && (
          <Callout
            tone="danger"
            icon={<XCircle />}
            title="Rejected"
            action={
              bid.permissions.can_reinstate ? (
                <Button
                  size="sm"
                  variant="outline"
                  loading={reinstate.isPending}
                  onClick={() =>
                    reinstate.mutate(bid.id, {
                      onSuccess: () =>
                        toast.success(`Bid from ${bid.bidder} reinstated`, {
                          description: 'Its assessments count again.',
                        }),
                      onError: (error) => toast.error(describeError(error).title),
                    })
                  }
                >
                  <RotateCcw /> Reinstate
                </Button>
              ) : undefined
            }
          >
            <span className="whitespace-pre-wrap">{bid.rejection.reason}</span>
            <span className="mt-1 block text-xs text-muted">
              {bid.rejection.rejected_by?.display_name ?? 'Someone'}{' '}
              <RelativeTime date={bid.rejection.rejected_at} />. Out of the queues, totals and
              ranking; its assessments are kept.
            </span>
          </Callout>
        )}
        {showSuggest && (
          <Callout
            tone="warning"
            icon={<TriangleAlert />}
            title="This bid doesn’t meet every must-have"
            action={
              <Button size="sm" variant="destructive" onClick={() => setDialog('reject')}>
                Reject…
              </Button>
            }
          >
            {suggestion || 'Check the must-haves below.'} It gets no total while that holds.
          </Callout>
        )}

        <Details call={call} bid={bid} manager={manager} />

        {bid.my_sections.length > 0 && !rejected && (
          <section aria-labelledby={`yours-${bid.id}`} className="flex flex-col gap-2">
            <h3 id={`yours-${bid.id}`} className="text-base font-semibold text-primary">
              Your sections
            </h3>
            <ul className="flex flex-col divide-y divide-subtle rounded-lg border">
              {bid.my_sections.map((section) => {
                const state = SECTION_STATE[section.state]
                return (
                  <li
                    key={section.section.id}
                    className="flex flex-wrap items-center gap-3 px-4 py-2.5"
                  >
                    <span className="min-w-0 flex-1 text-sm text-primary">
                      {section.section.title}
                    </span>
                    <span className="flex items-center gap-1.5 text-sm text-secondary">
                      <state.Icon
                        aria-hidden="true"
                        className={
                          section.state === 'submitted'
                            ? 'size-4 text-success'
                            : 'size-4 text-muted'
                        }
                      />
                      {state.label}
                    </span>
                    <Button
                      size="sm"
                      variant={section.state === 'submitted' ? 'ghost' : 'outline'}
                      disabled={!bid.permissions.can_assess && section.state !== 'submitted'}
                      aria-label={`${state.action}: ${section.section.title}`}
                      onClick={() => onAssess(bid.id, section.section.id)}
                    >
                      {state.action}
                    </Button>
                  </li>
                )
              })}
            </ul>
            {!bid.permissions.can_assess && call.status !== 'assessing' && (
              <p className="text-sm text-muted">
                You can assess once the call is closed to new bids.
              </p>
            )}
          </section>
        )}

        <MustHaves ideaKey={ideaKey} call={call} bid={bid} uploads={uploads} onRead={setReading} />
        <BidDocuments
          ideaKey={ideaKey}
          call={call}
          bid={bid}
          uploads={uploads}
          onRead={setReading}
        />
        {bid.permissions.can_view_ai && <BidAi ideaKey={ideaKey} view={view} bid={bid} />}
      </SheetBody>
      {(bid.permissions.can_edit || bid.permissions.can_reject || bid.permissions.can_delete) && (
        <SheetFooter className="justify-between">
          <div className="flex gap-2">
            {bid.permissions.can_edit && (
              <Button variant="outline" onClick={() => setDialog('edit')}>
                <Pencil /> Edit details
              </Button>
            )}
            {bid.permissions.can_reject && !showSuggest && (
              <Button variant="ghost" onClick={() => setDialog('reject')}>
                <XCircle /> Reject…
              </Button>
            )}
          </div>
          {bid.permissions.can_delete && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label={`More for the bid from ${bid.bidder}`}
                >
                  <MoreHorizontal />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem variant="destructive" onSelect={() => setDialog('delete')}>
                  <Trash2 /> Delete the bid…
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          )}
        </SheetFooter>
      )}

      {bid.permissions.can_edit && (
        <BidFormDialog
          key={bid.updated_at}
          ideaKey={ideaKey}
          call={call}
          bid={bid}
          open={dialog === 'edit'}
          onOpenChange={(open) => !open && setDialog(null)}
        />
      )}
      <RejectDialog
        ideaKey={ideaKey}
        bid={bid}
        suggestion={suggestion || undefined}
        open={dialog === 'reject'}
        onOpenChange={(open) => !open && setDialog(null)}
      />
      <DeleteBidDialog
        ideaKey={ideaKey}
        bid={bid}
        open={dialog === 'delete'}
        onOpenChange={(open) => !open && setDialog(null)}
        onDeleted={onClose}
      />
      <DocumentTextDialog
        ideaKey={ideaKey}
        bidId={bid.id}
        document={reading}
        onOpenChange={(open) => !open && setReading(null)}
      />
    </>
  )
}

function Details({ call, bid, manager }: { call: BidCall; bid: BidDetail; manager: boolean }) {
  const hasPrice = call.template.price_question_id !== null
  const rows: { term: string; value: React.ReactNode }[] = []
  if (hasPrice) {
    rows.push({
      term: 'Price',
      value: bid.price_hidden ? (
        <span className="text-muted">Only {pricingAudience(call)} see the price.</span>
      ) : bid.price === null ? (
        <span className="text-muted">Not entered</span>
      ) : (
        <span className="font-medium tabular-nums">{formatPrice(bid.price, call.currency)}</span>
      ),
    })
  }
  if (manager) {
    rows.push({
      term: 'Contact',
      value:
        bid.contact_name || bid.contact_email ? (
          <span className="break-words">
            {[bid.contact_name, bid.contact_email].filter(Boolean).join(' · ')}
          </span>
        ) : (
          <span className="text-muted">None given</span>
        ),
    })
  }
  rows.push({
    term: 'Entered',
    value: (
      <>
        {bid.entered_by?.display_name ?? 'Someone'} <RelativeTime date={bid.created_at} />
      </>
    ),
  })
  return (
    <section aria-label="Details" className="flex flex-col gap-3">
      <dl className="grid grid-cols-[minmax(0,8rem)_minmax(0,1fr)] gap-x-4 gap-y-2 text-sm">
        {rows.map((row) => (
          <div key={row.term} className="contents">
            <dt className="text-muted">{row.term}</dt>
            <dd className="text-primary">{row.value}</dd>
          </div>
        ))}
      </dl>
      {manager && bid.notes && (
        <div className="flex flex-col gap-1">
          <span className="text-sm text-muted">Notes</span>
          <p className="text-sm whitespace-pre-wrap text-secondary">{bid.notes}</p>
        </div>
      )}
    </section>
  )
}

function DeleteBidDialog({
  ideaKey,
  bid,
  open,
  onOpenChange,
  onDeleted,
}: {
  ideaKey: string
  bid: BidDetail
  open: boolean
  onOpenChange: (open: boolean) => void
  onDeleted: () => void
}) {
  const remove = useDeleteBid(ideaKey)
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) remove.reset()
        onOpenChange(next)
      }}
    >
      <DialogContent size="sm">
        <DialogHeader>
          <DialogTitle className="break-words">Delete the bid from {bid.bidder}?</DialogTitle>
          <DialogDescription>
            For a bid entered by mistake. Its documents and their text are deleted too. To turn a
            bid down, reject it instead: that keeps it on record.
          </DialogDescription>
        </DialogHeader>
        {remove.error && (
          <DialogBody>
            <p role="alert" className="text-sm text-danger">
              {describeError(remove.error).title}
            </p>
          </DialogBody>
        )}
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            variant="destructive"
            loading={remove.isPending}
            onClick={() =>
              remove.mutate(bid.id, {
                onSuccess: () => {
                  toast.success(`Bid from ${bid.bidder} deleted`)
                  onOpenChange(false)
                  onDeleted()
                },
              })
            }
          >
            Delete the bid
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
