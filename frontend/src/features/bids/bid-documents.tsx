import {
  Download,
  FileText,
  Link2,
  Lock,
  MoreHorizontal,
  RotateCw,
  ShieldAlert,
  Tag,
  Trash2,
  Upload,
  X,
} from 'lucide-react'
import { useState, type DragEvent } from 'react'

import { downloadBidDocument, useDeleteBidDocument, useUpdateBidDocument } from '@/api/bids'
import { describeError } from '@/api/errors'
import type { BidCall, BidDetail, BidDocument } from '@/api/types'
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
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { RelativeTime } from '@/components/ui/relative-time'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { toast } from '@/components/ui/toaster'
import { focusWhenRendered } from '@/lib/focus'
import { cn } from '@/lib/utils'

import { DOCUMENT_TYPE_LABEL, extractionText, formatSize, UPLOAD_TYPES_TEXT } from './bid-copy'
import type { DocumentUploads, UploadItem } from './use-document-uploads'

/** "Only the call's managers and the Commercial assessors can open it." */
export function pricingAudience(call: BidCall): string {
  const section = call.template.sections.find((s) => s.has_price)
  return section ? `the call’s managers and the ${section.title} assessors` : 'the call’s managers'
}

/**
 * A bid's documents (contract-phase10 §6): upload by dropping files or choosing them,
 * each with its progress and, if refused, why in plain words; then the list with the
 * text Soundings read, the download (a warning first when the file has active content),
 * the must-have it answers, the pricing mark and Delete. Files are never shown inline.
 */
export function BidDocuments({
  ideaKey,
  call,
  bid,
  uploads,
  onRead,
}: {
  ideaKey: string
  call: BidCall
  bid: BidDetail
  uploads: DocumentUploads
  onRead: (document: BidDocument) => void
}) {
  const canUpload = bid.permissions.can_upload
  const [dragging, setDragging] = useState(false)
  const [downloading, setDownloading] = useState<BidDocument | null>(null)
  const [confirm, setConfirm] = useState<{
    kind: 'delete' | 'pricing' | 'active'
    document: BidDocument
  } | null>(null)
  const mustHaves = new Map(call.template.must_haves.map((m) => [m.id, m]))

  const startDownload = (document: BidDocument) => {
    setDownloading(document)
    downloadBidDocument(ideaKey, bid.id, document)
      .catch((error: unknown) => {
        const { title, description } = describeError(error)
        toast.error(`${document.filename} wasn’t downloaded: ${title}`, { description })
      })
      .finally(() => setDownloading(null))
  }

  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault()
    setDragging(false)
    const files = Array.from(event.dataTransfer.files)
    // Each file's must-have is guessed from its name; pricing follows it (M2, M3).
    if (files.length > 0) uploads.start(files)
  }

  return (
    <section aria-labelledby={`documents-${bid.id}`} className="flex flex-col gap-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 id={`documents-${bid.id}`} className="text-base font-semibold text-primary">
          Documents
        </h3>
        <span className="text-sm text-muted tabular-nums">
          {bid.documents.length} {bid.documents.length === 1 ? 'file' : 'files'}
        </span>
      </div>

      {canUpload && (
        <div
          onDragEnter={(event) => {
            event.preventDefault()
            setDragging(true)
          }}
          onDragOver={(event) => {
            event.preventDefault()
            event.dataTransfer.dropEffect = 'copy'
          }}
          onDragLeave={(event) => {
            if (!event.currentTarget.contains(event.relatedTarget as Node | null))
              setDragging(false)
          }}
          onDrop={onDrop}
          data-dragging={dragging || undefined}
          className={cn(
            'flex flex-col items-center gap-2 rounded-lg border border-dashed px-4 py-5 text-center transition-colors',
            dragging ? 'border-focus bg-accent-subtle ring-3 ring-focus/20' : 'bg-surface',
          )}
        >
          <Upload aria-hidden="true" className="size-5 text-muted" />
          <p className="text-sm text-secondary">
            Drop files here, or{' '}
            <Button size="sm" variant="outline" className="mx-1" onClick={() => uploads.pick()}>
              Choose files
            </Button>
          </p>
          <p className="text-xs text-muted">{UPLOAD_TYPES_TEXT}. Files with macros are refused.</p>
          {call.template.must_haves.some((m) => m.kind === 'document') && (
            <p className="text-xs text-muted">
              Each file is matched to the must-have its name points to; change it on its row.
            </p>
          )}
        </div>
      )}
      {uploads.input}
      <p className="sr-only" role="status" aria-live="polite">
        {uploads.announcement}
      </p>

      {uploads.items.length > 0 && (
        <ul className="flex flex-col gap-2" aria-label="Uploads">
          {uploads.items.map((item) => (
            <UploadRow key={item.key} item={item} uploads={uploads} />
          ))}
        </ul>
      )}

      {bid.documents.length === 0 && bid.restricted_document_count === 0 ? (
        <p className="rounded-lg border px-4 py-3 text-sm text-muted">
          {canUpload
            ? 'No documents yet. Upload what the bidder sent: the AI and the assessors read their text.'
            : 'No documents yet.'}
        </p>
      ) : (
        bid.documents.length > 0 && (
          <ul
            className="flex flex-col divide-y divide-subtle rounded-lg border"
            aria-label="Documents"
          >
            {bid.documents.map((document) => (
              <DocumentRow
                key={document.id}
                document={document}
                mustHave={document.must_have_id ? mustHaves.get(document.must_have_id) : undefined}
                canUpload={canUpload}
                call={call}
                downloading={downloading?.id === document.id}
                onRead={() => onRead(document)}
                onDownload={() =>
                  document.active_content
                    ? setConfirm({ kind: 'active', document })
                    : startDownload(document)
                }
                onDelete={() => setConfirm({ kind: 'delete', document })}
                onMarkPricing={() => setConfirm({ kind: 'pricing', document })}
                ideaKey={ideaKey}
                bidId={bid.id}
                uploads={uploads}
              />
            ))}
          </ul>
        )
      )}
      {bid.restricted_document_count > 0 && (
        <p className="flex items-start gap-2 text-sm text-muted">
          <Lock aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
          {bid.restricted_document_count === 1
            ? 'One pricing document is present (restricted): '
            : `${bid.restricted_document_count} pricing documents are present (restricted): `}
          only {pricingAudience(call)} can open them.
        </p>
      )}

      <ConfirmDocumentDialog
        ideaKey={ideaKey}
        bidId={bid.id}
        call={call}
        confirm={confirm}
        mustHaveText={
          confirm?.document.must_have_id
            ? mustHaves.get(confirm.document.must_have_id)?.text
            : undefined
        }
        onDownload={startDownload}
        onDeleted={(id) => {
          const at = bid.documents.findIndex((d) => d.id === id)
          const next = bid.documents[at + 1] ?? bid.documents[at - 1]
          focusWhenRendered(
            () =>
              (next &&
                document.querySelector<HTMLElement>(
                  `[data-document="${CSS.escape(next.id)}"] button[aria-label^="Download"]`,
                )) ??
              document.getElementById(`choose-files-${bid.id}`),
            { force: true },
          )
        }}
        onClose={() => setConfirm(null)}
      />
    </section>
  )
}

function UploadRow({ item, uploads }: { item: UploadItem; uploads: DocumentUploads }) {
  const percent = Math.round(item.progress * 100)
  return (
    <li
      className={cn(
        'flex flex-col gap-1.5 rounded-lg border px-3 py-2.5',
        item.state === 'error' && 'border-danger',
      )}
    >
      <div className="flex items-center gap-2">
        <FileText aria-hidden="true" className="size-4 shrink-0 text-muted" />
        <span className="min-w-0 flex-1 text-sm font-medium break-all text-primary">
          <bdi>{item.name}</bdi>
        </span>
        <span className="shrink-0 text-xs text-muted tabular-nums">{formatSize(item.size)}</span>
        {item.state === 'error' ? (
          <>
            {item.retryable && (
              <Button
                size="sm"
                variant="ghost"
                onClick={() => uploads.retry(item.key)}
                aria-label={`Try ${item.name} again`}
              >
                <RotateCw /> Try again
              </Button>
            )}
            <Button
              size="icon-sm"
              variant="ghost"
              onClick={() => uploads.dismiss(item.key)}
              aria-label={`Dismiss ${item.name}`}
            >
              <X />
            </Button>
          </>
        ) : (
          <Button
            size="icon-sm"
            variant="ghost"
            onClick={() => uploads.cancel(item.key)}
            aria-label={`Cancel the upload of ${item.name}`}
          >
            <X />
          </Button>
        )}
      </div>
      {item.state === 'error' ? (
        <p className="text-sm text-danger">
          {item.error?.title}
          {item.error?.description && (
            <span className="text-secondary"> {item.error.description}</span>
          )}
        </p>
      ) : (
        <div className="flex items-center gap-3">
          <div
            role="progressbar"
            aria-label={`Uploading ${item.name}`}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={item.state === 'queued' ? 0 : percent}
            aria-valuetext={item.state === 'queued' ? 'Waiting' : `${percent}%`}
            className="h-1.5 flex-1 overflow-hidden rounded-full bg-subtle"
          >
            <div
              className="h-full rounded-full bg-accent transition-[width] duration-150"
              style={{ width: `${item.state === 'queued' ? 0 : percent}%` }}
            />
          </div>
          <span className="w-16 shrink-0 text-right text-xs text-muted tabular-nums">
            {item.state === 'queued' ? 'Waiting' : percent >= 100 ? 'Checking' : `${percent}%`}
          </span>
        </div>
      )}
    </li>
  )
}

const NO_MUST_HAVE = 'none'

/** A document's row after a change on it: its "More" button (the question's buttons go). */
function focusDocumentRow(id: string) {
  focusWhenRendered(
    () =>
      document.querySelector<HTMLElement>(
        `[data-document="${CSS.escape(id)}"] button[aria-label^="More for"]`,
      ),
    // The sheet's focus trap took focus to the sheet when the question went (m1).
    { force: true },
  )
}

function DocumentRow({
  ideaKey,
  bidId,
  call,
  document,
  mustHave,
  canUpload,
  downloading,
  uploads,
  onRead,
  onDownload,
  onDelete,
  onMarkPricing,
}: {
  ideaKey: string
  bidId: string
  call: BidCall
  document: BidDocument
  mustHave: BidCall['template']['must_haves'][number] | undefined
  canUpload: boolean
  downloading: boolean
  uploads: DocumentUploads
  onRead: () => void
  onDownload: () => void
  onDelete: () => void
  onMarkPricing: () => void
}) {
  const update = useUpdateBidDocument(ideaKey, bidId)
  const documentMustHaves = call.template.must_haves.filter((m) => m.kind === 'document')
  const linkedToPricing = mustHave?.pricing === true
  const done = document.extraction.state === 'done'
  const failed = document.extraction.state === 'failed'
  // Uploaded here as pricing because nothing said otherwise (M3): ask, on the row.
  const asking = uploads.askPricing.has(document.id) && document.pricing && !linkedToPricing
  const guessed = uploads.guessed.has(document.id) && mustHave !== undefined
  const selectId = `answers-${document.id}`

  const save = (body: { must_have_id: string | null; pricing: boolean }, success: string) =>
    update.mutate(
      { documentId: document.id, body },
      {
        onSuccess: () => {
          uploads.answered(document.id)
          toast.success(success)
          focusDocumentRow(document.id)
        },
        onError: (error) => {
          const { title, description } = describeError(error)
          toast.error(title, { description })
        },
      },
    )

  const link = (value: string) => {
    const target = documentMustHaves.find((m) => m.id === value)
    if ((target?.id ?? null) === document.must_have_id) return
    save(
      {
        must_have_id: target ? target.id : null,
        // A pricing must-have's file is a pricing document; a file uploaded as pricing only
        // by default takes the mark of what it answers.
        pricing: target?.pricing ? true : asking && target ? false : document.pricing,
      },
      target
        ? `${document.filename} answers ${target.text}`
        : `${document.filename} answers no must-have`,
    )
  }

  return (
    <li
      className="flex flex-wrap items-start gap-x-3 gap-y-2 px-4 py-3"
      data-document={document.id}
    >
      <FileText aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-muted" />
      <div className="flex min-w-0 flex-1 basis-56 flex-col gap-1">
        <span className="text-sm font-medium break-all text-primary">
          <bdi>{document.filename}</bdi>
        </span>
        <span className="text-xs text-muted">
          {DOCUMENT_TYPE_LABEL[document.type]} · {formatSize(document.size_bytes)}
          {document.uploaded_by && <> · {document.uploaded_by.display_name}</>}{' '}
          <RelativeTime date={document.uploaded_at} />
        </span>
        <span
          className={cn('text-xs', failed ? 'text-warning' : 'text-muted')}
          aria-live={document.extraction.state === 'pending' ? 'polite' : undefined}
        >
          {extractionText(document.extraction, document.type)}
        </span>
        {canUpload && documentMustHaves.length > 0 && (
          <div className="mt-1 flex flex-wrap items-center gap-2">
            <label htmlFor={selectId} className="text-xs text-muted">
              Answers
            </label>
            <Select
              value={document.must_have_id ?? NO_MUST_HAVE}
              onValueChange={link}
              disabled={update.isPending}
            >
              <SelectTrigger
                id={selectId}
                className="h-8 w-auto max-w-full min-w-40 text-sm"
                aria-label={`Must-have that ${document.filename} answers`}
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={NO_MUST_HAVE}>No must-have</SelectItem>
                {documentMustHaves.map((m) => (
                  <SelectItem key={m.id} value={m.id}>
                    {m.text}
                    {m.pricing ? ' (pricing)' : ''}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {guessed && <span className="text-xs text-muted">Matched from its name</span>}
          </div>
        )}
        {((!canUpload && mustHave !== undefined) ||
          document.pricing ||
          document.active_content) && (
          <span className="flex flex-wrap items-center gap-1.5">
            {!canUpload && mustHave && (
              <Badge variant="neutral">
                <Link2 aria-hidden="true" /> {mustHave.text}
              </Badge>
            )}
            {document.pricing && (
              <Badge variant="neutral">
                <Lock aria-hidden="true" /> Pricing
              </Badge>
            )}
            {document.active_content && (
              <Badge variant="warning">
                <ShieldAlert aria-hidden="true" /> Active content
              </Badge>
            )}
          </span>
        )}
        {asking && canUpload && (
          <div
            role="group"
            aria-label={`Is ${document.filename} a pricing document?`}
            className="mt-1 flex flex-col gap-2 rounded-md bg-subtle px-3 py-2.5"
          >
            <p className="text-sm text-secondary">
              <span className="font-medium text-primary">Is it a pricing document?</span> Until you
              say it isn’t, only {pricingAudience(call)} can open it and the AI doesn’t read it.
            </p>
            <div className="flex flex-wrap gap-2">
              <Button
                size="sm"
                variant="outline"
                loading={update.isPending}
                onClick={() =>
                  save(
                    { must_have_id: document.must_have_id, pricing: false },
                    `${document.filename} isn’t a pricing document: every assessor can read it`,
                  )
                }
              >
                Not pricing
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  uploads.answered(document.id)
                  focusDocumentRow(document.id)
                }}
              >
                Yes, keep it restricted
              </Button>
            </div>
          </div>
        )}
      </div>
      <div className="ml-auto flex shrink-0 items-center gap-1">
        {done && (
          <Button
            size="sm"
            variant="ghost"
            onClick={onRead}
            aria-label={`Read the text of ${document.filename}`}
          >
            Read
          </Button>
        )}
        <Button
          size="icon-sm"
          variant="ghost"
          loading={downloading}
          onClick={onDownload}
          aria-label={`Download ${document.filename}`}
        >
          {!downloading && <Download />}
        </Button>
        {canUpload && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button size="icon-sm" variant="ghost" aria-label={`More for ${document.filename}`}>
                <MoreHorizontal />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              {document.pricing ? (
                <DropdownMenuItem
                  disabled={linkedToPricing}
                  onSelect={() =>
                    save(
                      { must_have_id: document.must_have_id, pricing: false },
                      `${document.filename} is no longer a pricing document`,
                    )
                  }
                >
                  <Tag />{' '}
                  {linkedToPricing ? 'Pricing (its must-have is)' : 'Not a pricing document'}
                </DropdownMenuItem>
              ) : (
                <DropdownMenuItem onSelect={onMarkPricing}>
                  <Lock /> Mark as pricing…
                </DropdownMenuItem>
              )}
              <DropdownMenuSeparator />
              <DropdownMenuItem variant="destructive" onSelect={onDelete}>
                <Trash2 /> Delete…
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        )}
      </div>
    </li>
  )
}

function ConfirmDocumentDialog({
  ideaKey,
  bidId,
  call,
  confirm,
  mustHaveText,
  onDownload,
  onDeleted,
  onClose,
}: {
  ideaKey: string
  bidId: string
  call: BidCall
  confirm: { kind: 'delete' | 'pricing' | 'active'; document: BidDocument } | null
  mustHaveText: string | undefined
  onDownload: (document: BidDocument) => void
  /** The file is gone: focus goes to its neighbour (m1). */
  onDeleted: (documentId: string) => void
  onClose: () => void
}) {
  const remove = useDeleteBidDocument(ideaKey, bidId)
  const update = useUpdateBidDocument(ideaKey, bidId)
  const document = confirm?.document
  const pending = remove.isPending || update.isPending
  const error = remove.error ?? update.error

  const copy = !confirm
    ? null
    : confirm.kind === 'delete'
      ? {
          title: `Delete ${confirm.document.filename}?`,
          description: mustHaveText
            ? `The file and its text are deleted. “${mustHaveText}” is missing again unless another file answers it.`
            : 'The file and its text are deleted.',
          action: 'Delete the file',
          destructive: true,
        }
      : confirm.kind === 'pricing'
        ? {
            title: `Mark ${confirm.document.filename} as pricing?`,
            description: `Only ${pricingAudience(call)} can then open it, and the AI no longer reads it. Any AI assessment of this bid is removed (the AI may have read the file): ask the AI again afterwards.`,
            action: 'Mark as pricing',
            destructive: false,
          }
        : {
            title: 'This file has content that can run when it’s opened',
            description:
              confirm.document.type === 'pdf'
                ? 'Soundings found scripts, launch actions or attached files in this PDF. Open it only in a viewer you trust, with scripts off, or read its text here instead.'
                : 'Soundings found links to outside files or fields that fetch data in this file. Open it only in an app you trust, without updating links, or read its text here instead.',
            action: 'Download anyway',
            destructive: false,
          }

  return (
    <Dialog
      open={confirm !== null}
      onOpenChange={(open) => {
        if (!open) {
          remove.reset()
          update.reset()
          onClose()
        }
      }}
    >
      <DialogContent size="sm" role="alertdialog">
        <DialogHeader>
          <DialogTitle className="break-words">{copy?.title}</DialogTitle>
          <DialogDescription>{copy?.description}</DialogDescription>
        </DialogHeader>
        {error && (
          <DialogBody>
            <p role="alert" className="text-sm text-danger">
              {describeError(error).title}
            </p>
          </DialogBody>
        )}
        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant={copy?.destructive ? 'destructive' : 'primary'}
            loading={pending}
            onClick={() => {
              if (!confirm || !document) return
              if (confirm.kind === 'active') {
                onClose()
                onDownload(document)
              } else if (confirm.kind === 'delete') {
                remove.mutate(document.id, {
                  onSuccess: () => {
                    toast.success(`${document.filename} deleted`)
                    onClose()
                    onDeleted(document.id)
                  },
                })
              } else {
                update.mutate(
                  {
                    documentId: document.id,
                    body: { must_have_id: document.must_have_id, pricing: true },
                  },
                  {
                    onSuccess: () => {
                      toast.success(`${document.filename} is a pricing document`)
                      onClose()
                    },
                  },
                )
              }
            }}
          >
            {copy?.action}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
