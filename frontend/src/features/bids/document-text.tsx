import { ChevronLeft, ChevronRight, CloudOff, SearchX } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import { useBidDocumentText, useQuotePage } from '@/api/bids'
import type { BidDocument } from '@/api/types'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Skeleton, SkeletonGroup } from '@/components/ui/skeleton'
import { visibleText } from '@/lib/visible-text'
import { cn } from '@/lib/utils'

import { extractionText } from './bid-copy'
import { findQuote, readableText } from './quotes'

/**
 * A document's extracted text, page by page (contract-phase10 §6.3): plain text, never
 * rendered as HTML or Markdown (it was written by the bidder), with invisible and
 * direction-changing characters removed. The file itself is only ever downloaded.
 */
export function DocumentText({
  ideaKey,
  bidId,
  document,
  className,
  initialPage = 1,
  quote,
}: {
  ideaKey: string
  bidId: string
  document: BidDocument
  className?: string
  initialPage?: number
  /** An AI quote to mark on the page (and scroll to). */
  quote?: string
}) {
  const [page, setPage] = useState(initialPage)
  const mark = useRef<HTMLElement>(null)
  const done = document.extraction.state === 'done'
  const text = useBidDocumentText(ideaKey, bidId, done ? document.id : null, page)
  const pages = Math.max(1, document.extraction.page_count)
  const shown = text.data ? readableText(visibleText(text.data.text), document.type) : ''
  const found = quote && text.data ? findQuote(shown, quote) : null
  const foundAt = found?.[0] ?? -1
  useEffect(() => {
    const element = mark.current
    // jsdom has no scrollIntoView.
    if (foundAt >= 0 && element && typeof element.scrollIntoView === 'function')
      element.scrollIntoView({ block: 'center' })
  }, [foundAt])

  if (!done) {
    return (
      <p className={cn('rounded-lg border bg-subtle px-4 py-3 text-sm text-muted', className)}>
        {extractionText(document.extraction, document.type)}.
      </p>
    )
  }
  return (
    <div className={cn('flex min-h-0 flex-col gap-2', className)}>
      {text.isPending ? (
        <SkeletonGroup
          label="Loading the text"
          className="flex flex-col gap-2 rounded-lg border p-4"
        >
          <Skeleton className="h-3.5 w-full" />
          <Skeleton className="h-3.5 w-11/12" />
          <Skeleton className="h-3.5 w-4/5" />
        </SkeletonGroup>
      ) : text.isError ? (
        <div
          role="alert"
          className="flex flex-wrap items-center gap-3 rounded-lg border px-4 py-3 text-sm text-secondary"
        >
          <CloudOff aria-hidden="true" className="size-4 text-muted" />
          We couldn’t load the text.
          <Button size="sm" variant="outline" onClick={() => void text.refetch()}>
            Try again
          </Button>
        </div>
      ) : (
        <div
          // Focusable so keyboard users can scroll a long page (WCAG 2.1.1).
          // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
          tabIndex={0}
          role="region"
          aria-label={`Text of ${document.filename}, page ${page} of ${pages}`}
          className="min-h-0 flex-1 overflow-y-auto rounded-lg border bg-surface px-4 py-3 text-sm leading-relaxed break-words whitespace-pre-wrap text-primary"
        >
          {found ? (
            <>
              {shown.slice(0, found[0])}
              <mark
                ref={mark}
                className="rounded-sm bg-accent-subtle text-primary ring-2 ring-focus/40"
              >
                {shown.slice(found[0], found[1])}
              </mark>
              {shown.slice(found[1])}
            </>
          ) : (
            shown
          )}
        </div>
      )}
      {pages > 1 && (
        <div className="flex items-center justify-between gap-2 text-sm text-muted">
          <Button
            size="sm"
            variant="ghost"
            disabled={page <= 1}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
          >
            <ChevronLeft /> Previous
          </Button>
          <span className="tabular-nums" aria-live="polite">
            Page {page} of {pages}
          </span>
          <Button
            size="sm"
            variant="ghost"
            disabled={page >= pages}
            onClick={() => setPage((p) => Math.min(pages, p + 1))}
          >
            Next <ChevronRight />
          </Button>
        </div>
      )}
      {document.extraction.truncated && (
        <p className="text-xs text-muted">The text was cut at 2,000,000 characters.</p>
      )}
    </div>
  )
}

export function DocumentTextDialog({
  ideaKey,
  bidId,
  document,
  quote,
  onOpenChange,
}: {
  ideaKey: string
  bidId: string
  document: BidDocument | null
  /** Open at this AI quote, marked (its file name was chosen under the quote). */
  quote?: string | null
  onOpenChange: (open: boolean) => void
}) {
  const located = useQuotePage(ideaKey, bidId, document, quote ?? null, findQuote)
  return (
    <Dialog open={document !== null} onOpenChange={onOpenChange}>
      <DialogContent size="xl" mobile="fullscreen">
        <DialogHeader>
          <DialogTitle className="break-all">
            <bdi>{document?.filename ?? 'Document'}</bdi>
          </DialogTitle>
          <DialogDescription>
            The text Soundings read from the file, as plain text. Written by the bidder: read it as
            their claims.
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="flex min-h-0 flex-1 flex-col gap-3">
          {document && quote && located.isPending ? (
            <SkeletonGroup label="Finding the quote" className="flex flex-col gap-2">
              <Skeleton className="h-3.5 w-full" />
              <Skeleton className="h-3.5 w-11/12" />
            </SkeletonGroup>
          ) : (
            document && (
              <>
                {quote && located.data === null && (
                  <p className="flex items-start gap-2 text-sm text-warning">
                    <SearchX aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
                    The quote isn’t in this document’s text: check the AI’s claim before relying on
                    it.
                  </p>
                )}
                <DocumentText
                  key={`${document.id}:${located.data ?? 1}`}
                  ideaKey={ideaKey}
                  bidId={bidId}
                  document={document}
                  className="flex-1"
                  initialPage={located.data ?? 1}
                  quote={quote ?? undefined}
                />
              </>
            )
          )}
        </DialogBody>
      </DialogContent>
    </Dialog>
  )
}
