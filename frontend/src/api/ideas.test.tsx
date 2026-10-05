import { QueryClientProvider, type QueryClient } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import { delay, http } from 'msw'
import type { ReactNode } from 'react'
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import {
  boardQueryOptions,
  ideaQueryOptions,
  useChangeIdeaStatus,
  useIdea,
  useRemoveEvaluator,
  useVoteIdea,
} from '@/api/ideas'
import { queryKeys } from '@/api/keys'
import { createQueryClient } from '@/api/query'
import type { Board, IdeaDetail } from '@/api/types'
import { resetDb, USERS } from '@/mocks/db'
import { problemResponse } from '@/mocks/http'
import { server } from '@/mocks/server'
import { endSession } from '@/mocks/session'

const toasts = vi.hoisted(() => ({
  undo: [] as { title: string; onUndo: () => void; onCommit?: () => void }[],
  errors: [] as string[],
}))

vi.mock('@/components/ui/toaster', () => ({
  toast: {
    error: (title: string) => toasts.errors.push(title),
    success: () => undefined,
    info: () => undefined,
    message: () => undefined,
  },
  toastUndo: (title: string, options: { onUndo: () => void; onCommit?: () => void }) =>
    toasts.undo.push({ title, onUndo: options.onUndo, onCommit: options.onCommit }),
}))

let queryClient: QueryClient

function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
}

const board = () =>
  queryClient.getQueryData<Board>(boardQueryOptions('customer-innovation').queryKey)
const column = (status: string) => board()?.columns.find((c) => c.status === status)
const onColumn = (status: string, key: string) =>
  column(status)?.items.some((item) => item.key === key) ?? false

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
beforeEach(async () => {
  resetDb()
  localStorage.setItem('soundings-mock-latency', 'none')
  toasts.undo.length = 0
  toasts.errors.length = 0
  queryClient = createQueryClient()
  await api.POST('/api/v1/auth/dev/login', { body: { user_id: USERS.alice } })
  // Warm the caches the way the screens would: the board and the idea page.
  await queryClient.query(boardQueryOptions('customer-innovation'))
  await queryClient.query(ideaQueryOptions('CUST-2'))
})
afterEach(() => {
  server.resetHandlers()
  endSession()
  queryClient.clear()
})
afterAll(() => server.close())

describe('useChangeIdeaStatus', () => {
  it('moves the card at once, then keeps the server answer', async () => {
    const before = {
      evaluating: column('evaluating')?.count,
      shortlisted: column('shortlisted')?.count,
    }
    const { result } = renderHook(() => useChangeIdeaStatus('CUST-2'), { wrapper })

    act(() => result.current.mutate({ status: 'shortlisted' }))
    // Optimistic: moved before the request resolves.
    await waitFor(() => expect(onColumn('shortlisted', 'CUST-2')).toBe(true))
    expect(onColumn('evaluating', 'CUST-2')).toBe(false)
    expect(column('shortlisted')?.count).toBe((before.shortlisted ?? 0) + 1)
    expect(column('evaluating')?.count).toBe((before.evaluating ?? 0) - 1)
    expect(queryClient.getQueryData<IdeaDetail>(queryKeys.ideas.detail('CUST-2'))?.status).toBe(
      'shortlisted',
    )

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    const { data } = await api.GET('/api/v1/ideas/{idea}', { params: { path: { idea: 'CUST-2' } } })
    expect(data?.status).toBe('shortlisted')
  })

  it('snaps back and reports the error when the server refuses', async () => {
    server.use(
      http.post('*/api/v1/ideas/:idea/status', () =>
        problemResponse(409, 'project_archived', 'This project is archived.'),
      ),
    )
    const { result } = renderHook(() => useChangeIdeaStatus('CUST-2'), { wrapper })
    act(() => result.current.mutate({ status: 'closed', resolution: 'parked' }))
    await waitFor(() => expect(result.current.isError).toBe(true))
    expect(onColumn('evaluating', 'CUST-2')).toBe(true)
    expect(onColumn('closed', 'CUST-2')).toBe(false)
    expect(queryClient.getQueryData<IdeaDetail>(queryKeys.ideas.detail('CUST-2'))?.status).toBe(
      'evaluating',
    )
    expect(toasts.errors).toEqual(['Couldn’t change the status'])
    expect(toasts.undo).toHaveLength(0)
  })

  it('offers Undo, which sends the previous status and resolution', async () => {
    const { result } = renderHook(() => useChangeIdeaStatus('CUST-2'), { wrapper })
    act(() => result.current.mutate({ status: 'closed', resolution: 'rejected' }))
    await waitFor(() => expect(toasts.undo).toHaveLength(1))
    expect(toasts.undo[0]?.title).toBe('CUST-2 moved to Rejected')

    act(() => toasts.undo[0]?.onUndo())
    await waitFor(async () => {
      const { data } = await api.GET('/api/v1/ideas/{idea}', {
        params: { path: { idea: 'CUST-2' } },
      })
      expect(data).toMatchObject({ status: 'evaluating', resolution: null })
    })
    // The undo itself doesn't offer another undo.
    expect(toasts.undo).toHaveLength(1)
  })
})

describe('useVoteIdea', () => {
  it('counts the vote at once and rolls back on failure', async () => {
    const detail = () => queryClient.getQueryData<IdeaDetail>(queryKeys.ideas.detail('CUST-2'))
    const votes = detail()?.vote_count ?? 0
    server.use(
      http.put('*/api/v1/ideas/:idea/vote', async () => {
        await delay(100)
        return problemResponse(403, 'forbidden', 'You can’t vote here.')
      }),
    )
    const { result } = renderHook(() => useVoteIdea('CUST-2'), { wrapper })
    act(() => result.current.mutate({ vote: true }))
    // Both at once (one snapshot): on a loaded machine the rollback can land between two reads.
    await waitFor(() => expect(detail()).toMatchObject({ has_voted: true, vote_count: votes + 1 }))
    await waitFor(() => expect(result.current.isError).toBe(true))
    expect(detail()).toMatchObject({ has_voted: false, vote_count: votes })
  })
})

describe('useRemoveEvaluator (deferred)', () => {
  const dave = { id: USERS.dave, display_name: 'Dave Okafor', avatar_url: null, initials: 'DO' }

  function renderRemoval() {
    return renderHook(() => ({ idea: useIdea('CUST-2'), remove: useRemoveEvaluator('CUST-2') }), {
      wrapper,
    })
  }
  const evaluatorIds = (result: ReturnType<typeof renderRemoval>['result']) =>
    result.current.idea.data?.evaluators.map((e) => e.user.id)
  const serverEvaluatorIds = async () => {
    const { data } = await api.GET('/api/v1/ideas/{idea}', { params: { path: { idea: 'CUST-2' } } })
    return data?.evaluators.map((e) => e.user.id)
  }

  it('hides the row at once and deletes when the toast closes', async () => {
    const { result } = renderRemoval()
    await waitFor(() => expect(evaluatorIds(result)).toContain(USERS.dave))
    act(() => result.current.remove(dave))
    expect(evaluatorIds(result)).not.toContain(USERS.dave)
    expect(result.current.idea.data?.evaluator_progress).toEqual({ submitted: 2, total: 2 })
    // Nothing is sent until the toast closes.
    expect(await serverEvaluatorIds()).toContain(USERS.dave)

    act(() => toasts.undo.at(-1)?.onCommit?.())
    await waitFor(async () => expect(await serverEvaluatorIds()).not.toContain(USERS.dave))
    await waitFor(() => expect(evaluatorIds(result)).not.toContain(USERS.dave))
  })

  it('Undo brings the row back and sends nothing', async () => {
    const { result } = renderRemoval()
    await waitFor(() => expect(evaluatorIds(result)).toContain(USERS.dave))
    act(() => result.current.remove(dave))
    act(() => toasts.undo.at(-1)?.onUndo())
    expect(evaluatorIds(result)).toContain(USERS.dave)
    act(() => toasts.undo.at(-1)?.onCommit?.())
    expect(await serverEvaluatorIds()).toContain(USERS.dave)
  })
})
