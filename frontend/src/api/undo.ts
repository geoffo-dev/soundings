/**
 * Undo (contract §3.14). Two mechanisms, no undo endpoints:
 *
 * 1. **Inverse call** — the change is sent at once; Undo sends the opposite
 *    request (status back, previous owner, unvote, reopen…):
 *      offerUndo('CUST-12 moved to Shortlisted', () => changeStatus.mutate(previous))
 *
 * 2. **Deferred commit** — for comment delete and evaluator removal, whose
 *    effects can't be reversed. The UI hides the item at once; the DELETE is
 *    sent only when the toast closes (or the page is hidden/unloaded); Undo
 *    cancels it and restores the item:
 *      deferUntilToastCloses({ title: 'Comment deleted', hide, restore, commit })
 */
import { useSyncExternalStore } from 'react'

import { toast, toastUndo } from '@/components/ui/toaster'

export const UNDO_TOAST_MS = 6000

export interface CommitOptions {
  /** True when flushing on page hide: send with `keepalive` so it survives unload. */
  keepalive: boolean
}

interface PendingCommit {
  run: (options: CommitOptions) => Promise<unknown>
}

const pending = new Map<string, PendingCommit>()
let listening = false

function listen() {
  if (listening || typeof window === 'undefined') return
  listening = true
  // pagehide fires on unload and bfcache; visibilitychange covers mobile tab switches.
  window.addEventListener('pagehide', () => void flushPendingCommits())
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') void flushPendingCommits()
  })
}

/** Sends every deferred commit now (page hide, sign-out, tests). */
export async function flushPendingCommits(options: CommitOptions = { keepalive: true }) {
  const entries = [...pending.values()]
  pending.clear()
  await Promise.allSettled(entries.map((entry) => entry.run(options)))
}

/** Number of deferred commits waiting for their toast (for tests and diagnostics). */
export function pendingCommitCount(): number {
  return pending.size
}

export interface DeferredOptions {
  title: string
  description?: string
  /** Apply the optimistic change (hide the item). Called immediately. */
  hide: () => void
  /** Put the item back (Undo, or the commit failed). */
  restore: () => void
  /** Send the real request. */
  commit: (options: CommitOptions) => Promise<unknown>
  /** Called after a successful commit (e.g. invalidate queries). */
  onCommitted?: () => void
  /** Title of the error toast if the commit fails. */
  errorTitle?: string
  duration?: number
}

export interface DeferredHandle {
  /** Cancel and restore, as if Undo was clicked. */
  undo: () => void
  /** Send the request now instead of waiting for the toast. */
  commitNow: () => Promise<void>
}

let nextId = 0

/** Mechanism 2: hide now, commit when the Undo toast closes. */
export function deferUntilToastCloses({
  title,
  description,
  hide,
  restore,
  commit,
  onCommitted,
  errorTitle = 'Couldn’t save that change',
  duration = UNDO_TOAST_MS,
}: DeferredOptions): DeferredHandle {
  listen()
  const id = `deferred-${++nextId}`
  let state: 'waiting' | 'undone' | 'committed' = 'waiting'

  const run = async (options: CommitOptions) => {
    if (state !== 'waiting') return
    state = 'committed'
    pending.delete(id)
    try {
      await commit(options)
      onCommitted?.()
    } catch (error) {
      restore()
      toast.error(errorTitle, {
        description: error instanceof Error ? error.message : 'Please try again.',
      })
    }
  }
  const undo = () => {
    if (state !== 'waiting') return
    state = 'undone'
    pending.delete(id)
    restore()
  }

  pending.set(id, { run })
  hide()
  toastUndo(title, {
    id,
    description,
    duration,
    onUndo: undo,
    onCommit: () => void run({ keepalive: false }),
  })
  return { undo, commitNow: () => run({ keepalive: false }) }
}

/* ------------------------------------------------------------------ */
/* Items hidden while their deferred delete waits                      */
/* ------------------------------------------------------------------ */

/**
 * Keys of items hidden by a pending deferred delete, e.g.
 * `comment:<id>` or `evaluator:<ideaId>:<userId>`. Queries filter them out
 * with `select`, so a refetch during the Undo window can't bring them back
 * and Undo is exact (the cache itself is never changed).
 */
let hiddenItems: ReadonlySet<string> = new Set()
const hiddenListeners = new Set<() => void>()

export function hideItem(key: string): void {
  hiddenItems = new Set([...hiddenItems, key])
  hiddenListeners.forEach((listener) => listener())
}

export function unhideItem(key: string): void {
  if (!hiddenItems.has(key)) return
  const next = new Set(hiddenItems)
  next.delete(key)
  hiddenItems = next
  hiddenListeners.forEach((listener) => listener())
}

export function subscribeHiddenItems(listener: () => void): () => void {
  hiddenListeners.add(listener)
  return () => hiddenListeners.delete(listener)
}

export function getHiddenItems(): ReadonlySet<string> {
  return hiddenItems
}

/** The hidden-item keys; re-renders when an item is hidden or restored. */
export function useHiddenItems(): ReadonlySet<string> {
  return useSyncExternalStore(subscribeHiddenItems, getHiddenItems, getHiddenItems)
}

export const hiddenKey = {
  comment: (commentId: string) => `comment:${commentId}`,
  evaluator: (ideaId: string, userId: string) => `evaluator:${ideaId}:${userId}`,
}

/** Mechanism 1: the change is saved; Undo runs the inverse request. */
export function offerUndo(
  title: string,
  inverse: () => void,
  options: { description?: string; duration?: number } = {},
): void {
  toastUndo(title, { onUndo: inverse, duration: options.duration ?? UNDO_TOAST_MS, ...options })
}
