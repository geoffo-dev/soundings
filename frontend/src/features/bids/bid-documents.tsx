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
import { Checkbox } from '@/components/ui/checkbox'
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
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Label } from '@/components/ui/label'
import { RelativeTime } from '@/components/ui/relative-time'
import { toast } from '@/components/ui/toaster'
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
  const [pricing, setPricing] = useState(false)
  const [dragging, setDragging] = useState(false)
  const [downloading, setDownloading] = useState<BidDocument | null>(null)
  const [confirm, setConfirm] = useState<{
    kind: 'delete' | 'pricing' | 'active'
    document: BidDocument
  } | null>(null)
  const hasPricingQuestion = call.template.sections.some((s) => s.has_price)
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
    if (files.length > 0) uploads.start(files, { pricing: pricing || undefined })
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
            dragging ? 'border-strong bg-subtle' : 'bg-surface',
          )}
        >
          <Upload aria-hidden="true" className="size-5 text-muted" />
          <p className="text-sm text-secondary">
            Drop files here, or{' '}
            <Button
              size="sm"
              variant="outline"
              className="mx-1"
              onClick={() => uploads.pick({ pricing: pricing || undefined })}
            >
              Choose files
            </Button>
          </p>
          <p className="text-xs text-muted">{UPLOAD_TYPES_TEXT}. Files with macros are refused.</p>
        </div>
      )}
      {canUpload && hasPricingQuestion && (
        <div className="flex items-start gap-2">
          <Checkbox
            id={`pricing-${bid.id}`}
            checked={pricing}
            onCheckedChange={(value) => setPricing(value === true)}
            className="mt-0.5"
          />
          <Label
            htmlFor={`pricing-${bid.id}`}
            className="flex flex-col items-start gap-0.5 font-normal"
          >
            <span className="text-sm text-primary">Upload as pricing documents</span>
            <span className="text-xs text-muted">
              Only {pricingAudience(call)} can open them, and the AI never reads them.
            </span>
          </Label>
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
          {item.name}
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

function DocumentRow({
  ideaKey,
  bidId,
  call,
  document,
  mustHave,
  canUpload,
  downloading,
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

  const save = (body: { must_have_id: string | null; pricing: boolean }, success: string) =>
    update.mutate(
      { documentId: document.id, body },
      {
        onSuccess: () => toast.success(success),
        onError: (error) => {
          const { title, description } = describeError(error)
          toast.error(title, { description })
        },
      },
    )

  return (
    <li className="flex flex-wrap items-start gap-x-3 gap-y-2 px-4 py-3">
      <FileText aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-muted" />
      <div className="flex min-w-0 flex-1 basis-56 flex-col gap-1">
        <span className="text-sm font-medium break-all text-primary">{document.filename}</span>
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
        {(mustHave !== undefined || document.pricing || document.active_content) && (
          <span className="flex flex-wrap items-center gap-1.5">
            {mustHave && (
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
              <Button
                size="icon-sm"
                variant="ghost"
                loading={update.isPending}
                aria-label={`More for ${document.filename}`}
              >
                {!update.isPending && <MoreHorizontal />}
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              {documentMustHaves.length > 0 && (
                <DropdownMenuSub>
                  <DropdownMenuSubTrigger>
                    <Link2 /> Answers the must-have
                  </DropdownMenuSubTrigger>
                  <DropdownMenuSubContent>
                    <DropdownMenuRadioGroup
                      value={document.must_have_id ?? 'none'}
                      onValueChange={(value) => {
                        const target = documentMustHaves.find((m) => m.id === value)
                        save(
                          {
                            must_have_id: target ? target.id : null,
                            // A pricing must-have's file is a pricing document.
                            pricing: target?.pricing ? true : document.pricing,
                          },
                          target
                            ? `${document.filename} linked to ${target.text}`
                            : `${document.filename} unlinked`,
                        )
                      }}
                    >
                      <DropdownMenuRadioItem value="none">None</DropdownMenuRadioItem>
                      {documentMustHaves.map((m) => (
                        <DropdownMenuRadioItem key={m.id} value={m.id}>
                          {m.text}
                          {m.pricing && <span className="text-muted"> (pricing)</span>}
                        </DropdownMenuRadioItem>
                      ))}
                    </DropdownMenuRadioGroup>
                  </DropdownMenuSubContent>
                </DropdownMenuSub>
              )}
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
  onClose,
}: {
  ideaKey: string
  bidId: string
  call: BidCall
  confirm: { kind: 'delete' | 'pricing' | 'active'; document: BidDocument } | null
  mustHaveText: string | undefined
  onDownload: (document: BidDocument) => void
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
      <DialogContent size="sm">
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
