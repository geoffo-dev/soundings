import {
  CircleCheck,
  CircleDashed,
  CircleHelp,
  CircleX,
  FileQuestion,
  Lock,
  SearchCheck,
  SearchX,
  Upload,
} from 'lucide-react'
import { useState } from 'react'

import { useDecideMustHave } from '@/api/bids'
import { describeError } from '@/api/errors'
import type {
  BidAiFindingView,
  BidCall,
  BidDetail,
  BidDocument,
  BidMustHaveState,
  MustHaveResult,
} from '@/api/types'
import { AiBadge } from '@/components/ui/ai-badge'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
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
import { RelativeTime } from '@/components/ui/relative-time'
import { Textarea } from '@/components/ui/textarea'
import { toast } from '@/components/ui/toaster'
import { focusWhenRendered } from '@/lib/focus'
import { visibleText } from '@/lib/visible-text'
import { cn } from '@/lib/utils'

import { AI_FINDING, MUST_HAVE_RESULT } from './bid-copy'
import { pricingAudience } from './bid-documents'
import type { DocumentUploads } from './use-document-uploads'

const RESULT_ICON: Record<MustHaveResult, typeof CircleCheck> = {
  met: CircleCheck,
  not_met: CircleX,
  missing: CircleX,
  unchecked: CircleDashed,
}

/** "Missing: Insurance certificate. Not met: ISO 27001." — a first reason for Reject. */
export function rejectionSuggestion(bid: BidDetail): string {
  const missing = bid.must_have_results.filter((s) => s.result === 'missing')
  const notMet = bid.must_have_results.filter((s) => s.result === 'not_met')
  const aiNotMet = bid.must_have_results.filter(
    (s) =>
      s.result !== 'not_met' &&
      s.result !== 'missing' &&
      s.ai_findings.some((f) => f.finding === 'not_met'),
  )
  return [
    missing.length > 0 && `Missing: ${missing.map((s) => s.must_have.text).join(', ')}.`,
    notMet.length > 0 && `Not met: ${notMet.map((s) => s.must_have.text).join(', ')}.`,
    aiNotMet.length > 0 &&
      `The AI found not met: ${aiNotMet.map((s) => s.must_have.text).join(', ')}.`,
  ]
    .filter(Boolean)
    .join(' ')
}

/**
 * Files that answer no must-have while a required document is missing (UX review M2):
 * `waiting` when one of them may be it, so the reject suggestion waits and the checklist
 * says so. Only files you can see count (a pricing file you can't open isn't yours to link).
 */
export function unlinkedFiles(bid: BidDetail): {
  count: number
  waiting: boolean
  missing: string[]
} {
  const missing = bid.must_have_results
    .filter((s) => s.result === 'missing' && s.must_have.kind === 'document')
    .map((s) => s.must_have.text)
  const count = bid.documents.filter((d) => d.must_have_id === null).length
  return { count, waiting: missing.length > 0 && count > 0, missing }
}

/**
 * The bid's must-have checklist (contract-phase10 §5.3): each with its result (missing
 * flagged), who decided it, the linked files ("present (restricted)" for pricing files you
 * can't open) and the AI's suggestion with its evidence, which never changes the result.
 * Call managers confirm met or not met, upload a missing document, or clear a decision.
 */
export function MustHaves({
  ideaKey,
  call,
  bid,
  uploads,
  onRead,
  onOpenQuote,
}: {
  ideaKey: string
  call: BidCall
  bid: BidDetail
  uploads: DocumentUploads
  onRead: (document: BidDocument) => void
  onOpenQuote?: (documentId: string, quote: string) => void
}) {
  const [notMet, setNotMet] = useState<BidMustHaveState | null>(null)
  if (bid.must_have_results.length === 0) return null
  const documents = new Map(bid.documents.map((d) => [d.id, d]))
  const flagged = bid.must_have_results.filter(
    (s) => s.result === 'missing' || s.result === 'not_met',
  ).length
  const unlinked = unlinkedFiles(bid)
  const canLink = bid.permissions.can_upload

  return (
    <section aria-labelledby={`must-haves-${bid.id}`} className="flex flex-col gap-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 id={`must-haves-${bid.id}`} className="text-base font-semibold text-primary">
          Must-haves
        </h3>
        {flagged > 0 && bid.status !== 'rejected' && (
          <span className="text-sm font-medium text-danger">
            {flagged} {flagged === 1 ? 'isn’t met' : 'aren’t met'}
          </span>
        )}
      </div>
      {unlinked.waiting && bid.status !== 'rejected' && (
        <p className="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-md bg-subtle px-3 py-2 text-sm text-secondary">
          <FileQuestion aria-hidden="true" className="size-4 shrink-0 text-muted" />
          <span className="min-w-0 flex-1">
            {unlinked.count === 1
              ? '1 file doesn’t answer a must-have.'
              : `${unlinked.count} files don’t answer a must-have.`}{' '}
            {canLink
              ? `If one is the ${unlinked.missing.join(' or the ')}, choose it on the file’s row.`
              : `Still missing: ${unlinked.missing.join(', ')}.`}
          </span>
          {canLink && (
            <Button
              size="sm"
              variant="link"
              onClick={() => {
                const first = bid.documents.find((d) => d.must_have_id === null)
                if (!first) return
                document
                  .querySelector<HTMLElement>(`#answers-${CSS.escape(first.id)}`)
                  ?.focus({ preventScroll: false })
              }}
            >
              Show the files
            </Button>
          )}
        </p>
      )}
      <ul
        className="flex flex-col divide-y divide-subtle rounded-lg border"
        aria-label="Must-haves"
      >
        {bid.must_have_results.map((state) => (
          <MustHaveRow
            key={state.must_have.id}
            ideaKey={ideaKey}
            call={call}
            bid={bid}
            state={state}
            documents={documents}
            uploads={uploads}
            onRead={onRead}
            onOpenQuote={onOpenQuote}
            onNotMet={() => setNotMet(state)}
          />
        ))}
      </ul>
      <NotMetDialog
        ideaKey={ideaKey}
        bidId={bid.id}
        state={notMet}
        onOpenChange={(open) => !open && setNotMet(null)}
      />
    </section>
  )
}

function MustHaveRow({
  ideaKey,
  call,
  bid,
  state,
  documents,
  uploads,
  onRead,
  onOpenQuote,
  onNotMet,
}: {
  ideaKey: string
  call: BidCall
  bid: BidDetail
  state: BidMustHaveState
  documents: Map<string, BidDocument>
  uploads: DocumentUploads
  onRead: (document: BidDocument) => void
  onOpenQuote?: (documentId: string, quote: string) => void
  onNotMet: () => void
}) {
  const decide = useDecideMustHave(ideaKey)
  const { must_have: mustHave, result } = state
  const copy = MUST_HAVE_RESULT[result]
  const Icon = RESULT_ICON[result]
  const canDecide = bid.permissions.can_decide_must_haves
  const linked = state.document_ids
    .map((id) => documents.get(id))
    .filter((d): d is BidDocument => Boolean(d))
  const restrictedOnly = linked.length === 0 && state.restricted_document_count > 0
  const decided = !state.automatic && state.decided_by !== null

  const set = (next: 'met' | null) =>
    decide.mutate(
      { bidId: bid.id, mustHaveId: mustHave.id, body: { result: next, note: '' } },
      {
        onSuccess: () => {
          toast.success(next === 'met' ? `${mustHave.text}: met` : `${mustHave.text}: cleared`)
          // The button used is gone (Met → Clear): to the row's next control (m1).
          focusMustHaveRow(mustHave.id)
        },
        onError: (error) => {
          const { title, description } = describeError(error)
          toast.error(title, { description })
        },
      },
    )

  return (
    <li
      className="flex flex-col gap-2 px-4 py-3 outline-none"
      data-must-have={mustHave.id}
      tabIndex={-1}
    >
      <div className="flex flex-wrap items-start gap-x-3 gap-y-2">
        <Icon
          aria-hidden="true"
          className={cn(
            'mt-0.5 size-4 shrink-0',
            result === 'met'
              ? 'text-success'
              : result === 'unchecked'
                ? 'text-warning'
                : 'text-danger',
          )}
        />
        <div className="flex min-w-0 flex-1 basis-48 flex-col gap-0.5">
          <span className="text-sm text-primary">{mustHave.text}</span>
          <span className="text-xs text-muted">
            {mustHave.kind === 'document' ? 'A document' : 'A confirmation'}
            {mustHave.pricing && ' · pricing'}
            {decided && state.decided_by && (
              <>
                {' '}
                ·{' '}
                {mustHave.kind === 'confirmation' && result === 'met'
                  ? 'confirmed'
                  : `marked ${copy.label.toLowerCase()}`}{' '}
                by {state.decided_by.display_name}{' '}
                {state.decided_at && <RelativeTime date={state.decided_at} />}
              </>
            )}
            {state.automatic && result === 'met' && ' · a file is linked'}
          </span>
        </div>
        <Badge variant={copy.tone} className="shrink-0">
          {restrictedOnly && result === 'met' ? 'Present (restricted)' : copy.label}
        </Badge>
      </div>

      {state.note && (
        <p className="ml-7 text-sm whitespace-pre-wrap text-secondary">{state.note}</p>
      )}

      {(linked.length > 0 || state.restricted_document_count > 0) && (
        <ul className="ml-7 flex flex-col gap-1 text-sm">
          {linked.map((document) => (
            <li key={document.id} className="flex flex-wrap items-center gap-x-2">
              <span className="min-w-0 break-all text-secondary">
                <bdi>{document.filename}</bdi>
              </span>
              {document.extraction.state === 'done' && (
                <Button
                  variant="link"
                  size="sm"
                  onClick={() => onRead(document)}
                  aria-label={`Read the text of ${document.filename}`}
                >
                  Read
                </Button>
              )}
            </li>
          ))}
          {state.restricted_document_count > 0 && (
            <li className="flex items-center gap-1.5 text-muted">
              <Lock aria-hidden="true" className="size-3.5 shrink-0" />
              Present (restricted): only {pricingAudience(call)} can open{' '}
              {state.restricted_document_count === 1 ? 'it' : 'them'}
            </li>
          )}
        </ul>
      )}

      {state.ai_findings.map((finding) => (
        <AiFinding
          key={finding.ai_assessment_id}
          finding={finding}
          documents={documents}
          onOpenQuote={onOpenQuote}
        />
      ))}

      {canDecide && (
        <div className="ml-7 flex flex-wrap items-center gap-2">
          {mustHave.kind === 'document' && result === 'missing' && (
            <Button
              size="sm"
              variant="outline"
              onClick={() =>
                uploads.pick({
                  mustHaveId: mustHave.id,
                  pricing: mustHave.pricing || undefined,
                  label: mustHave.text,
                })
              }
            >
              <Upload /> Upload
            </Button>
          )}
          {mustHave.kind === 'confirmation' && result !== 'met' && (
            <Button
              size="sm"
              variant="outline"
              loading={decide.isPending}
              onClick={() => set('met')}
            >
              <CircleCheck /> Met
            </Button>
          )}
          {result !== 'not_met' && (
            <Button size="sm" variant="ghost" onClick={onNotMet}>
              <CircleX /> Not met…
            </Button>
          )}
          {decided && (
            <Button size="sm" variant="ghost" loading={decide.isPending} onClick={() => set(null)}>
              Clear
            </Button>
          )}
          {mustHave.kind === 'document' && result === 'missing' && mustHave.pricing && (
            <span className="text-xs text-muted">
              Only {pricingAudience(call)} can open this file.
            </span>
          )}
        </div>
      )}
    </li>
  )
}

/**
 * A must-have's row after a change: its first button, else the row itself. Forced: the
 * sheet's focus trap moves focus to the sheet when the button used goes, which isn't
 * "free" focus but is lost all the same (UX review m1).
 */
function focusMustHaveRow(id: string) {
  focusWhenRendered(
    () => {
      const row = document.querySelector<HTMLElement>(`[data-must-have="${CSS.escape(id)}"]`)
      return row?.querySelector<HTMLElement>('button:not([disabled])') ?? row
    },
    { force: true },
  )
}

const FINDING_ICON = { met: CircleCheck, not_met: CircleX, unclear: CircleHelp }

/** The AI's pre-check of a must-have: a suggestion with its quotes, checked by the server. */
function AiFinding({
  finding,
  documents,
  onOpenQuote,
}: {
  finding: BidAiFindingView
  documents: Map<string, BidDocument>
  onOpenQuote?: (documentId: string, quote: string) => void
}) {
  const copy = AI_FINDING[finding.finding]
  const Icon = FINDING_ICON[finding.finding]
  return (
    <div className="ml-7 flex flex-col gap-2 rounded-md bg-subtle px-3 py-2.5">
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
        <AiBadge />
        <span className="flex items-center gap-1 font-medium text-secondary">
          <Icon aria-hidden="true" className="size-3.5" />
          {copy.label}
        </span>
        <span>
          {finding.agent.display_name} <RelativeTime date={finding.submitted_at} />
        </span>
        <span>A suggestion to check</span>
      </div>
      {finding.rationale && (
        <p className="text-sm whitespace-pre-wrap text-secondary">
          {visibleText(finding.rationale)}
        </p>
      )}
      <Evidence evidence={finding.evidence} documents={documents} onOpenQuote={onOpenQuote} />
    </div>
  )
}

/** Quotes the AI gave, each marked "Found in the document" or not (presence only). */
export function Evidence({
  evidence,
  documents,
  onOpenQuote,
}: {
  evidence: BidAiFindingView['evidence']
  documents: Map<string, Pick<BidDocument, 'filename'>>
  /** The file name opens its text at the quote (m13). */
  onOpenQuote?: (documentId: string, quote: string) => void
}) {
  if (evidence.length === 0) return null
  return (
    <ul className="flex flex-col gap-2">
      {evidence.map((item, index) => (
        <li
          key={`${item.document_id}:${index}`}
          className="flex flex-col gap-1 outline-none"
          data-quote-found={item.found ? undefined : 'false'}
          tabIndex={item.found ? undefined : -1}
        >
          <blockquote className="border-l-2 border-strong pl-3 text-sm break-words text-primary">
            “{visibleText(item.quote)}”
          </blockquote>
          <span
            className={cn(
              'flex flex-wrap items-center gap-1 pl-3 text-xs',
              item.found ? 'text-muted' : 'font-medium text-warning',
            )}
          >
            {item.found ? (
              <SearchCheck aria-hidden="true" className="size-3.5" />
            ) : (
              <SearchX aria-hidden="true" className="size-3.5" />
            )}
            {item.found ? 'Found in the document' : 'Not found in the document'}
            {documents.get(item.document_id) &&
              (onOpenQuote ? (
                <Button
                  variant="link"
                  size="sm"
                  className="h-auto p-0 text-xs break-all"
                  aria-label={`Show the quote in ${documents.get(item.document_id)?.filename ?? 'the document'}`}
                  onClick={() => onOpenQuote(item.document_id, item.quote)}
                >
                  <bdi>{documents.get(item.document_id)?.filename}</bdi>
                </Button>
              ) : (
                <span className="break-all text-muted">
                  (<bdi>{documents.get(item.document_id)?.filename}</bdi>)
                </span>
              ))}
          </span>
        </li>
      ))}
    </ul>
  )
}

function NotMetDialog({
  ideaKey,
  bidId,
  state,
  onOpenChange,
}: {
  ideaKey: string
  bidId: string
  state: BidMustHaveState | null
  onOpenChange: (open: boolean) => void
}) {
  const decide = useDecideMustHave(ideaKey)
  const [note, setNote] = useState('')
  const [shown, setShown] = useState<string | null>(null)
  const id = state?.must_have.id ?? null
  if (id !== shown) {
    setShown(id)
    setNote('')
    decide.reset()
  }
  return (
    <Dialog open={state !== null} onOpenChange={onOpenChange}>
      <DialogContent size="md">
        <form
          noValidate
          className="flex min-h-0 flex-1 flex-col"
          onSubmit={(event) => {
            event.preventDefault()
            if (!state || decide.isPending) return
            decide.mutate(
              {
                bidId,
                mustHaveId: state.must_have.id,
                body: { result: 'not_met', note: note.trim() },
              },
              {
                onSuccess: () => {
                  toast.success(`${state.must_have.text}: not met`, {
                    description: 'The bid now gets no total. Reject it, or clear this later.',
                  })
                  onOpenChange(false)
                  // "Not met…" is gone from the row ("Clear" took its place).
                  focusMustHaveRow(state.must_have.id)
                },
              },
            )
          }}
        >
          <DialogHeader>
            <DialogTitle className="break-words">Not met: {state?.must_have.text}</DialogTitle>
            <DialogDescription>
              A bid that doesn’t meet every must-have gets no total and can’t be awarded.
            </DialogDescription>
          </DialogHeader>
          <DialogBody className="flex flex-col gap-3">
            {decide.error && (
              <p role="alert" className="text-sm text-danger">
                {describeError(decide.error).title}
              </p>
            )}
            <Field label="Note" description="Optional. What isn’t right, in a few words.">
              <Textarea
                value={note}
                maxLength={500}
                minRows={2}
                onChange={(event) => setNote(event.target.value)}
              />
            </Field>
          </DialogBody>
          <DialogFooter>
            <Button variant="ghost" type="button" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button variant="destructive" type="submit" loading={decide.isPending}>
              Not met
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
