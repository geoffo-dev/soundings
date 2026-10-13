import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useRef, useState } from 'react'

import {
  BID_DOCUMENT_ACCEPT,
  BID_DOCUMENT_MAX_BYTES,
  BID_DOCUMENTS_PER_BID_MAX,
  documentUploaded,
  uploadBidDocument,
} from '@/api/bids'
import { describeError, hasErrorCode } from '@/api/errors'

import { uploadProblem } from './bid-copy'

export interface UploadTarget {
  /** Upload into this document must-have (it is met once the file is linked). */
  mustHaveId?: string | null
  /** Mark the files pricing (default: the must-have's mark, else not). */
  pricing?: boolean
  /** The must-have's text, for the messages ("for Insurance certificate"). */
  label?: string
}

export interface UploadItem {
  key: string
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
]

/**
 * A bid's uploads (contract-phase10 §6.1): one file at a time (the API takes two at once
 * per process), each with its progress, and its refusal in plain words beside the file.
 * Sizes are checked before sending; the type is the server's to decide (from the bytes).
 * A finished upload leaves the list: the document appears with the bid's others.
 */
export function useDocumentUploads(ideaKey: string, bidId: string, documentCount: number) {
  const queryClient = useQueryClient()
  const [items, setItems] = useState<UploadItem[]>([])
  const [announcement, setAnnouncement] = useState('')
  const queue = useRef<Promise<void>>(Promise.resolve())
  const counter = useRef(0)
  const files = useRef(new Map<string, File>())
  const controllers = useRef(new Map<string, AbortController>())
  const inputRef = useRef<HTMLInputElement>(null)
  const pickTarget = useRef<UploadTarget>({})

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
        await uploadBidDocument(
          {
            idea: ideaKey,
            bidId,
            file,
            mustHaveId: target.mustHaveId ?? null,
            pricing: target.pricing,
          },
          { onProgress: (progress) => patch(key, { progress }), signal: controller.signal },
        )
        drop(key)
        documentUploaded(queryClient, ideaKey, bidId)
        setAnnouncement(
          `${file.name} uploaded${target.label ? ` for ${target.label}` : ''}. Reading its text.`,
        )
      } catch (error) {
        if (error instanceof DOMException && error.name === 'AbortError') {
          drop(key)
          setAnnouncement(`${file.name}: upload cancelled.`)
          return
        }
        const words = describeError(error)
        patch(key, {
          state: 'error',
          error: words,
          retryable: !hasErrorCode(error, ...FINAL_CODES),
        })
        setAnnouncement(`${file.name} wasn’t uploaded: ${words.title}.`)
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

  /** Queues the files (or says at once why one can't go). */
  const start = useCallback(
    (picked: readonly File[], target: UploadTarget = {}) => {
      const waiting = items.filter((item) => item.state !== 'error').length
      const added: UploadItem[] = []
      for (const file of picked) {
        counter.current += 1
        const key = `upload-${counter.current}`
        const problem =
          uploadProblem(file, BID_DOCUMENT_MAX_BYTES) ??
          (documentCount + waiting + added.filter((a) => a.state === 'queued').length >=
          BID_DOCUMENTS_PER_BID_MAX
            ? `A bid takes at most ${BID_DOCUMENTS_PER_BID_MAX} documents: delete one first.`
            : null)
        const item: UploadItem = {
          key,
          name: file.name,
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
    [documentCount, enqueue, items],
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

  /** Opens the file picker for this target (a must-have's "Upload", the documents' button). */
  const pick = useCallback((target: UploadTarget = {}) => {
    pickTarget.current = target
    inputRef.current?.click()
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

  return { items, start, retry, cancel, dismiss: drop, pick, input, announcement }
}

export type DocumentUploads = ReturnType<typeof useDocumentUploads>
