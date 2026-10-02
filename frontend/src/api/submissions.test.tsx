import { QueryClientProvider, type QueryClient } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import { createQueryClient } from '@/api/query'
import {
  useEraseSubmitter,
  useIdeaSubmission,
  useModerate,
  useModerationCount,
  useModerationQueue,
} from '@/api/submissions'
import { resetDb, USERS } from '@/mocks/db'
import { server } from '@/mocks/server'

/** The Undo toasts: each one's callbacks, so a test can press Undo or let it close. */
const toasts = vi.hoisted(() => ({
  undo: [] as { title: string; onUndo: () => void; onCommit?: () => void }[],
}))
vi.mock('@/components/ui/toaster', () => ({
  toast: {
    error: () => undefined,
    success: () => undefined,
    info: () => undefined,
    message: () => undefined,
  },
  toastUndo: (title: string, options: { onUndo: () => void; onCommit?: () => void }) => {
    toasts.undo.push({ title, ...options })
  },
}))

let queryClient: QueryClient

function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
}

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
beforeEach(async () => {
  resetDb()
  localStorage.setItem('soundings-mock-latency', 'none')
  toasts.undo.length = 0
  queryClient = createQueryClient()
  // Priya (platform admin) moderates Sustainability: GREEN-10 and GREEN-11 wait.
  await api.POST('/api/v1/auth/dev/login', { body: { user_id: USERS.priya } })
})
afterEach(() => {
  server.resetHandlers()
  queryClient.clear()
})
afterAll(() => server.close())

function useQueue() {
  return {
    queue: useModerationQueue('sustainability'),
    count: useModerationCount('sustainability'),
    moderate: useModerate(),
  }
}

describe('moderation', () => {
  it('approve hides the idea until its toast closes; Undo sends nothing', async () => {
    const posts: string[] = []
    server.events.on('request:start', ({ request }) => {
      if (request.method === 'POST' && request.url.includes('/submission/')) posts.push(request.url)
    })
    const { result } = renderHook(useQueue, { wrapper })
    await waitFor(() => expect(result.current.queue.data?.items).toHaveLength(2))
    expect(result.current.queue.data?.total).toBe(2)
    const first = result.current.queue.data?.items[0]
    if (!first) throw new Error('no idea waiting')

    act(() => result.current.moderate.approve(first))
    await waitFor(() => expect(result.current.queue.data?.items).toHaveLength(1))
    expect(result.current.queue.data?.total).toBe(1)
    await waitFor(() => expect(result.current.count.data).toBe(1))
    expect(toasts.undo[0]?.title).toBe(`${first.key} approved: it’s in New now`)

    act(() => toasts.undo[0]?.onUndo())
    await waitFor(() => expect(result.current.queue.data?.items).toHaveLength(2))
    expect(result.current.queue.data?.total).toBe(2)
    expect(posts).toEqual([])
    server.events.removeAllListeners()
  })

  it('the toast closing sends the approval, and the queue refreshes', async () => {
    const { result } = renderHook(useQueue, { wrapper })
    await waitFor(() => expect(result.current.queue.data?.items).toHaveLength(2))
    const first = result.current.queue.data?.items[0]
    if (!first) throw new Error('no idea waiting')

    act(() => result.current.moderate.approve(first))
    act(() => toasts.undo[0]?.onCommit?.())
    await waitFor(() => expect(result.current.queue.data?.total).toBe(1))
    expect(result.current.queue.data?.items.map((item) => item.key)).not.toContain(first.key)
    const idea = await api.GET('/api/v1/ideas/{idea}', { params: { path: { idea: first.key } } })
    expect(idea.data?.held_for).toBeNull()
  })

  it('reject deletes the idea once committed', async () => {
    const { result } = renderHook(useQueue, { wrapper })
    await waitFor(() => expect(result.current.queue.data?.items).toHaveLength(2))
    const second = result.current.queue.data?.items[1]
    if (!second) throw new Error('no idea waiting')

    act(() => result.current.moderate.reject(second))
    expect(toasts.undo[0]?.title).toBe(`${second.key} rejected and deleted`)
    act(() => toasts.undo[0]?.onCommit?.())
    await waitFor(() => expect(result.current.queue.data?.total).toBe(1))
    await expect(
      api.GET('/api/v1/ideas/{idea}', { params: { path: { idea: second.key } } }),
    ).rejects.toMatchObject({ status: 404 })
  })
})

describe('erasing a submitter', () => {
  it('stores the erased submission and drops the contact details', async () => {
    const { result } = renderHook(
      () => ({ submission: useIdeaSubmission('GREEN-9'), erase: useEraseSubmitter('GREEN-9') }),
      { wrapper },
    )
    await waitFor(() => expect(result.current.submission.data?.contact?.email).toBeTruthy())
    expect(result.current.submission.data?.permissions.can_erase).toBe(true)

    await act(() => result.current.erase.mutateAsync())
    await waitFor(() => expect(result.current.submission.data?.erased_at).not.toBeNull())
    expect(result.current.submission.data?.name).toBeNull()
    expect(result.current.submission.data?.contact?.email ?? null).toBeNull()
    expect(result.current.submission.data?.permissions.can_erase).toBe(false)
  })
})
