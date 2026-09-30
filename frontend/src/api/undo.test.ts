import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  deferUntilToastCloses,
  flushPendingCommits,
  getHiddenItems,
  hideItem,
  offerUndo,
  pendingCommitCount,
  unhideItem,
} from '@/api/undo'

interface CapturedToast {
  title: string
  onUndo: () => void
  onCommit?: () => void
}

const captured = vi.hoisted(() => ({ toasts: [] as CapturedToast[], errors: [] as string[] }))

vi.mock('@/components/ui/toaster', () => ({
  toast: { error: (title: string) => captured.errors.push(title) },
  toastUndo: (title: string, options: Omit<CapturedToast, 'title'>) =>
    captured.toasts.push({ title, ...options }),
}))

beforeEach(() => {
  captured.toasts.length = 0
  captured.errors.length = 0
})
afterEach(async () => {
  await flushPendingCommits({ keepalive: false })
})

function setup(commit = vi.fn(() => Promise.resolve())) {
  const hide = vi.fn()
  const restore = vi.fn()
  const onCommitted = vi.fn()
  const handle = deferUntilToastCloses({
    title: 'Comment deleted',
    hide,
    restore,
    commit,
    onCommitted,
  })
  const toast = captured.toasts.at(-1)
  if (!toast) throw new Error('no toast')
  return { hide, restore, commit, onCommitted, handle, toast }
}

describe('deferUntilToastCloses', () => {
  it('hides at once and sends the request only when the toast closes', async () => {
    const { hide, commit, onCommitted, toast } = setup()
    expect(hide).toHaveBeenCalledOnce()
    expect(commit).not.toHaveBeenCalled()
    expect(pendingCommitCount()).toBe(1)

    toast.onCommit?.()
    await vi.waitFor(() => expect(onCommitted).toHaveBeenCalledOnce())
    expect(commit).toHaveBeenCalledWith({ keepalive: false })
    expect(pendingCommitCount()).toBe(0)
  })

  it('Undo restores the item and never sends the request', () => {
    const { restore, commit, toast } = setup()
    toast.onUndo()
    toast.onCommit?.() // the toast still closes afterwards
    expect(restore).toHaveBeenCalledOnce()
    expect(commit).not.toHaveBeenCalled()
    expect(pendingCommitCount()).toBe(0)
  })

  it('sends pending deletes with keepalive when the page is hidden', async () => {
    const { commit } = setup()
    window.dispatchEvent(new Event('pagehide'))
    await vi.waitFor(() => expect(commit).toHaveBeenCalledWith({ keepalive: true }))
  })

  it('commits once, even if the toast closes after an early commit', async () => {
    const { commit, handle, toast } = setup()
    await handle.commitNow()
    toast.onCommit?.()
    expect(commit).toHaveBeenCalledOnce()
  })

  it('puts the item back and says so when the request fails', async () => {
    const { restore, toast } = setup(vi.fn(() => Promise.reject(new Error('Server error'))))
    toast.onCommit?.()
    await vi.waitFor(() => expect(restore).toHaveBeenCalledOnce())
    expect(captured.errors).toEqual(['Couldn’t save that change'])
  })
})

describe('offerUndo', () => {
  it('runs the inverse call on Undo', () => {
    const inverse = vi.fn()
    offerUndo('CUST-2 moved to Shortlisted', inverse)
    captured.toasts.at(-1)?.onUndo()
    expect(inverse).toHaveBeenCalledOnce()
  })
})

describe('hidden items', () => {
  it('hides and restores keys immutably', () => {
    const before = getHiddenItems()
    hideItem('comment:1')
    expect(getHiddenItems().has('comment:1')).toBe(true)
    expect(before.has('comment:1')).toBe(false)
    unhideItem('comment:1')
    expect(getHiddenItems().has('comment:1')).toBe(false)
  })
})
