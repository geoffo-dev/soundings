import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useRef, useState } from 'react'

import {
  BID_DOCUMENT_ACCEPT,
  BID_DOCUMENT_MAX_BYTES,
  BID_DOCUMENTS_PER_BID_MAX,
  documentUploaded,
  uploadBidDocument,
} from '@/api/bids'
import { describeError, hasErrorCode, isApiError } from '@/api/errors'
import type { BidCall, BidDetail } from '@/api/types'

import { uploadProblem } from './bid-copy'
import { cleanFilename, guessMustHave } from './upload-names'

export interface UploadTarget {
  /** Upload into this document must-have (it is met once the file is linked). */
  mustHaveId?: string | null
  /** Mark the files pricing (default: the must-have's mark, else not). */
  pricing?: boolean
  /** The must-have's text, for the messages ("for Insurance certificate"). */
  label?: string
  /** The must-have was guessed from the file's name (its row says so, and can change it). */
  guessed?: boolean
  /**
   * Sent as a pricing document because nothing says it isn't (the call has a price
   * question and the file answers no must-have): its row asks (UX review M3).
   */
  askPricing?: boolean
}

export interface UploadItem {
  key: string
  /** The name sent (control and direction characters and folders removed). */
  name: string
  size: number
  /** 0-1 while the bytes go up. */
  progress: number
  state: 'queued' | 'uploading' | 'error'
  target: UploadTarget
  error?: { title: string; description?: string }
  /** The same file can be tried again (the connection, a busy server, a timeout). */
  retryable?: boolean
}

/** Refusals that sending the same file again won't fix. */
const FINAL_CODES = [
  'unsupported_document_type',
  'macro_document',
  'duplicate_document',
  'content_too_large',
  'too_many_documents',
  'call_storage_full',
  'project_storage_full',
  'invalid_must_have',
  'bid_call_finished',
  'not_found',
  'forbidden',
  'validation_error',
]

/** A refusal in plain words: a name the API can't take is the person's to fix (m5). */
function uploadWords(error: unknown): { title: string; description?: string } {
  if (
    isApiError(error) &&
    error.status === 422 &&
    (error.problem?.errors ?? []).some((entry) =>
      entry.loc.some((part) => typeof part === 'string' && /^(x-)?filename$/i.test(part)),
    )
  ) {
    return {
      title: 'That file name can’t be used',
      description: 'Rename the file (letters, numbers, spaces and dashes) and try again.',
    }
  }
  return describeError(error)
}

/**
 * A bid's uploads (contract-phase10 §6.1): one file at a time (the API takes two at once
 * per process), each with its progress, and its refusal in plain words beside the file.
 * Sizes are checked before sending; the type is the server's to decide (from the bytes).
 * A finished upload leaves the list: the document appears with the bid's others.
 *
 * Files dropped or chosen for the bid as a whole (UX review M2, M3) link to the document
 * must-have their name points to; one that answers none, in a call with a price question,
 * goes up as a pricing document (nobody but the price's audience and no AI reads it) and
 * its row asks whether it is one: pricing is never exposed by default.
 */
export function useDocumentUploads(ideaKey: string, bid: BidDetail, call: BidCall) {
  const bidId = bid.id
  const documentCount = bid.documents.length
  const queryClient = useQueryClient()
  const [items, setItems] = useState<UploadItem[]>([])
  const [announcement, setAnnouncement] = useState('')
  /** Documents uploaded here as pricing by default, whose rows ask (until answered). */
  const [askPricing, setAskPricing] = useState<ReadonlySet<string>>(new Set())
  /** Documents uploaded here with a guessed must-have (their rows say so). */
  const [guessed, setGuessed] = useState<ReadonlySet<string>>(new Set())
  const queue = useRef<Promise<void>>(Promise.resolve())
  const counter = useRef(0)
  const files = useRef(new Map<string, File>())
  const controllers = useRef(new Map<string, AbortController>())
  const inputRef = useRef<HTMLInputElement>(null)
  const pickTarget = useRef<UploadTarget | null>(null)

  const patch = useCallback((key: string, change: Partial<UploadItem>) => {
    setItems((list) => list.map((item) => (item.key === key ? { ...item, ...change } : item)))
  }, [])
  const drop = useCallback((key: string) => {
    files.current.delete(key)
    controllers.current.delete(key)
    setItems((list) => list.filter((item) => item.key !== key))
  }, [])

  const send = useCallback(
    async (key: string, file: File, target: UploadTarget) => {
      const controller = new AbortController()
      controllers.current.set(key, controller)
      patch(key, { state: 'uploading', progress: 0, error: undefined })
      try {
        const name = cleanFilename(file.name)
        const document = await uploadBidDocument(
          {
            idea: ideaKey,
            bidId,
            file,
            filename: name,
            mustHaveId: target.mustHaveId ?? null,
            pricing: target.pricing,
          },
          { onProgress: (progress) => patch(key, { progress }), signal: controller.signal },
        )
        drop(key)
        if (target.askPricing) setAskPricing((ids) => new Set(ids).add(document.id))
        if (target.guessed) setGuessed((ids) => new Set(ids).add(document.id))
        documentUploaded(queryClient, ideaKey, bidId)
        setAnnouncement(
          `${name} uploaded${target.label ? ` for ${target.label}` : ''}.${
            target.askPricing ? ' Kept as a pricing document until you say it isn’t.' : ''
          } Reading its text.`,
        )
      } catch (error) {
        if (error instanceof DOMException && error.name === 'AbortError') {
          drop(key)
          setAnnouncement(`${cleanFilename(file.name)}: upload cancelled.`)
          return
        }
        const words = uploadWords(error)
        patch(key, {
          state: 'error',
          error: words,
          retryable: !hasErrorCode(error, ...FINAL_CODES),
        })
        setAnnouncement(`${cleanFilename(file.name)} wasn’t uploaded: ${words.title}.`)
        // A refusal that changes what the bid shows (it is full, the call finished).
        if (hasErrorCode(error, 'too_many_documents', 'bid_call_finished')) {
          documentUploaded(queryClient, ideaKey, bidId)
        }
      } finally {
        controllers.current.delete(key)
      }
    },
    [bidId, drop, ideaKey, patch, queryClient],
  )

  const enqueue = useCallback(
    (key: string, file: File, target: UploadTarget) => {
      queue.current = queue.current.then(() => send(key, file, target))
    },
    [send],
  )

  const hasPrice = call.template.price_question_id !== null
  const documentMustHaves = call.template.must_haves.filter((m) => m.kind === 'document')
  const missing = new Set(
    bid.must_have_results.filter((s) => s.result === 'missing').map((s) => s.must_have.id),
  )

  /** Where a file for the bid as a whole goes: the must-have its name points to, or not. */
  const targetFor = (file: File): UploadTarget => {
    const must = guessMustHave(cleanFilename(file.name), documentMustHaves, missing)
    if (must) {
      return {
        mustHaveId: must.id,
        label: must.text,
        guessed: true,
        pricing: must.pricing || undefined,
      }
    }
    return hasPrice ? { pricing: true, askPricing: true } : {}
  }

  /** Queues the files (or says at once why one can't go). `target` null: guess per file. */
  const start = useCallback(
    (picked: readonly File[], given: UploadTarget | null = null) => {
      const waiting = items.filter((item) => item.state !== 'error').length
      const added: UploadItem[] = []
      for (const file of picked) {
        const target = given ?? targetFor(file)
        counter.current += 1
        const key = `upload-${counter.current}`
        const problem =
          uploadProblem(file, BID_DOCUMENT_MAX_BYTES, cleanFilename(file.name)) ??
          (documentCount + waiting + added.filter((a) => a.state === 'queued').length >=
          BID_DOCUMENTS_PER_BID_MAX
            ? `A bid takes at most ${BID_DOCUMENTS_PER_BID_MAX} documents: delete one first.`
            : null)
        const item: UploadItem = {
          key,
          name: cleanFilename(file.name),
          size: file.size,
          progress: 0,
          state: problem ? 'error' : 'queued',
          target,
          error: problem ? { title: problem } : undefined,
          retryable: false,
        }
        added.push(item)
        if (!problem) {
          files.current.set(key, file)
          enqueue(key, file, target)
        }
      }
      if (added.length > 0) setItems((list) => [...list, ...added])
      const refused = added.filter((item) => item.state === 'error')
      if (refused.length > 0) {
        setAnnouncement(refused.map((item) => item.error?.title ?? '').join(' '))
      }
    },
    // targetFor reads the bid as rendered (its missing must-haves).
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [documentCount, enqueue, items, bid, call],
  )

  const retry = useCallback(
    (key: string) => {
      const file = files.current.get(key)
      const item = items.find((i) => i.key === key)
      if (!file || !item) return
      patch(key, { state: 'queued', error: undefined, progress: 0 })
      enqueue(key, file, item.target)
    },
    [enqueue, items, patch],
  )

  const cancel = useCallback(
    (key: string) => {
      const controller = controllers.current.get(key)
      if (controller) controller.abort()
      else drop(key)
    },
    [drop],
  )

  /**
   * Opens the file picker for this target (a must-have's "Upload"), or with none for the
   * bid as a whole (the documents' "Choose files": each file's must-have is guessed).
   */
  const pick = useCallback((target: UploadTarget | null = null) => {
    pickTarget.current = target
    inputRef.current?.click()
  }, [])

  /** The row's question was answered (or the mark changed some other way). */
  const answered = useCallback((documentId: string) => {
    setAskPricing((ids) => {
      if (!ids.has(documentId)) return ids
      const next = new Set(ids)
      next.delete(documentId)
      return next
    })
  }, [])

  const input = (
    <input
      ref={inputRef}
      type="file"
      multiple
      accept={BID_DOCUMENT_ACCEPT}
      className="sr-only"
      tabIndex={-1}
      aria-hidden="true"
      onChange={(event) => {
        const chosen = Array.from(event.target.files ?? [])
        event.target.value = ''
        if (chosen.length > 0) start(chosen, pickTarget.current)
      }}
    />
  )

  /** Files are going up or waiting to (the reject suggestion waits for them: M2). */
  const busy = items.some((item) => item.state !== 'error')

  return {
    items,
    busy,
    start,
    retry,
    cancel,
    dismiss: drop,
    pick,
    input,
    announcement,
    askPricing,
    answered,
    guessed,
  }
}

export type DocumentUploads = ReturnType<typeof useDocumentUploads>
