import { ChevronLeft, ChevronRight, CloudOff } from 'lucide-react'
import { useState } from 'react'

import { useBidDocumentText } from '@/api/bids'
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
}: {
  ideaKey: string
  bidId: string
  document: BidDocument
  className?: string
}) {
  const [page, setPage] = useState(1)
  const done = document.extraction.state === 'done'
  const text = useBidDocumentText(ideaKey, bidId, done ? document.id : null, page)
  const pages = Math.max(1, document.extraction.page_count)

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
          {visibleText(text.data.text)}
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
  onOpenChange,
}: {
  ideaKey: string
  bidId: string
  document: BidDocument | null
  onOpenChange: (open: boolean) => void
}) {
  return (
    <Dialog open={document !== null} onOpenChange={onOpenChange}>
      <DialogContent size="xl" mobile="fullscreen">
        <DialogHeader>
          <DialogTitle className="break-all">{document?.filename ?? 'Document'}</DialogTitle>
          <DialogDescription>
            The text Soundings read from the file, as plain text. Written by the bidder: read it as
            their claims.
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="flex min-h-0 flex-1 flex-col">
          {document && (
            <DocumentText ideaKey={ideaKey} bidId={bidId} document={document} className="flex-1" />
          )}
        </DialogBody>
      </DialogContent>
    </Dialog>
  )
}
