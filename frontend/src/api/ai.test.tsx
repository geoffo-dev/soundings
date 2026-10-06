import { QueryClientProvider, type QueryClient } from '@tanstack/react-query'
import { act, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

import { useIdeaAiRuns, useRequestAiRun, useSetEvaluationInclusion } from '@/api/ai'
import { api } from '@/api/client'
import { useEvaluations } from '@/api/evaluations'
import { queryKeys } from '@/api/keys'
import { createQueryClient } from '@/api/query'
import type { AiRun, IdeaDetail } from '@/api/types'
import { TooltipProvider } from '@/components/ui/tooltip'
import { RunCard } from '@/features/ai/run-card'
import { MOCK_AI_OUTCOME_STORAGE_KEY, MOCK_AI_PACE_STORAGE_KEY } from '@/mocks/ai'
import { resetDb, USERS } from '@/mocks/db'
import { AGENTS } from '@/mocks/phase6-fixtures'
import { server } from '@/mocks/server'
import { endSession } from '@/mocks/session'

vi.mock('@/components/ui/toaster', () => ({
  toast: {
    error: () => undefined,
    success: () => undefined,
    info: () => undefined,
    message: () => undefined,
  },
  toastUndo: () => undefined,
}))

let queryClient: QueryClient

function wrapper({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>{children}</TooltipProvider>
    </QueryClientProvider>
  )
}

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
beforeEach(async () => {
  resetDb()
  localStorage.setItem('soundings-mock-latency', 'none')
  localStorage.setItem(MOCK_AI_PACE_STORAGE_KEY, '2')
  localStorage.removeItem(MOCK_AI_OUTCOME_STORAGE_KEY)
  queryClient = createQueryClient()
  await api.POST('/api/v1/auth/dev/login', { body: { user_id: USERS.alice } })
})
afterEach(() => {
  server.resetHandlers()
  endSession()
  queryClient.clear()
})
afterAll(() => server.close())

describe('AI runs data layer', () => {
  it('asks once: a second ask while active answers with the same run', async () => {
    localStorage.setItem(MOCK_AI_OUTCOME_STORAGE_KEY, 'queued')
    const { result } = renderHook(
      () => ({ list: useIdeaAiRuns('CUST-2'), request: useRequestAiRun('CUST-2') }),
      { wrapper },
    )
    await waitFor(() => expect(result.current.list.data).toBeDefined())
    const ask = (): Promise<{ run: AiRun; existing: boolean }> =>
      new Promise((resolve) =>
        result.current.request.mutate(
          { kind: 'evaluate', agentId: AGENTS.evaluator },
          { onSuccess: resolve },
        ),
      )
    const first = await act(ask)
    const second = await act(ask)
    expect(first.existing).toBe(false)
    expect(second).toMatchObject({ existing: true, run: { id: first.run.id } })
    await waitFor(() =>
      expect(result.current.list.data?.items.filter((run) => run.id === first.run.id)).toHaveLength(
        1,
      ),
    )
  })

  it('includes an AI evaluation optimistically, then refetches the idea’s score', async () => {
    await api.POST('/api/v1/auth/dev/login', { body: { user_id: USERS.carol } })
    const { result } = renderHook(
      () => ({ list: useEvaluations('CUST-7'), toggle: useSetEvaluationInclusion('CUST-7') }),
      { wrapper },
    )
    await waitFor(() => expect(result.current.list.data?.items.length).toBe(3))
    const ai = result.current.list.data?.items.find((item) => item.is_ai)
    expect(ai?.include_in_aggregate).toBe(false)
    queryClient.setQueryData<IdeaDetail | undefined>(queryKeys.ideas.detail('CUST-7'), undefined)
    act(() => result.current.toggle.mutate({ evaluationId: ai?.id ?? '', include: true }))
    await waitFor(() =>
      expect(result.current.list.data?.items.find((item) => item.is_ai)?.include_in_aggregate).toBe(
        true,
      ),
    )
    await waitFor(() => expect(result.current.toggle.isSuccess).toBe(true))
  })
})

describe('RunCard', () => {
  const finished = (overrides: Partial<AiRun> = {}): AiRun => ({
    id: 'r-1',
    idea_id: 'i-1',
    kind: 'evaluate',
    section_key: null,
    status: 'timed_out',
    agent: { id: 'a', display_name: 'Idea evaluator', purposes: ['evaluate'], user_id: 'u' },
    requested_by: { id: 'u-a', display_name: 'Alice Anders', avatar_url: null, initials: 'AA' },
    created_at: new Date(Date.now() - 600_000).toISOString(),
    started_at: new Date(Date.now() - 590_000).toISOString(),
    finished_at: new Date(Date.now() - 290_000).toISOString(),
    deadline_at: null,
    cancel_requested: false,
    can_cancel: false,
    error: { code: 'timed_out', message: 'The agent didn’t finish in time.' },
    result: { evaluation_id: null, note_id: null, suggestion_id: null },
    event_count: 0,
    ...overrides,
  })

  async function askResearch(): Promise<AiRun> {
    const asked = await api.POST('/api/v1/ideas/{idea}/ai-runs/research', {
      params: { path: { idea: 'CUST-2' } },
      body: { agent_id: AGENTS.research },
    })
    return asked.data as AiRun
  }

  it('follows a run by polling where there is no EventSource, to its outcome', async () => {
    localStorage.setItem(MOCK_AI_PACE_STORAGE_KEY, '300')
    const run = await askResearch()
    render(<RunCard ideaKey="CUST-2" run={run} />, { wrapper })
    expect(
      screen.getByRole('heading', { name: /Researching · Research agent/ }),
    ).toBeInTheDocument()
    // One line while it works; who asked and every step behind "Steps".
    expect(screen.queryByRole('list', { name: 'Steps' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Steps' }))
    expect(await screen.findByText(/Live updates aren’t available here/)).toBeInTheDocument()
    expect(screen.getByText(/Asked by Alice Anders/)).toBeInTheDocument()
    // Polling (2.5 s) brings the steps; the list refetch would bring the final status.
    expect(
      await screen.findByText('Wrote the research note', {}, { timeout: 6000 }),
    ).toBeInTheDocument()
    expect(screen.getByRole('list', { name: 'Steps' })).toHaveTextContent('Done')
  }, 10_000)

  it('says why a finished run stopped, with the limit and a next step, and offers what the page passes', () => {
    render(<RunCard ideaKey="CUST-2" run={finished()} retry={<button>Try again</button>} />, {
      wrapper,
    })
    expect(screen.getByText('The agent didn’t finish within 5 minutes.')).toBeInTheDocument()
    expect(screen.getByText(/Try again: it may have been busy/)).toBeInTheDocument()
    expect(screen.getByText(/Timed out:/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Steps' })).toHaveAttribute('aria-expanded', 'false')
  })

  it('words failures by code, never as protocol output', () => {
    render(
      <RunCard
        ideaKey="CUST-2"
        run={finished({
          status: 'failed',
          error: {
            code: 'agent_rejected',
            message: 'The agent declined the request. (state rejected)',
          },
        })}
      />,
      { wrapper },
    )
    expect(screen.getByText('The agent turned the request down.')).toBeInTheDocument()
    expect(screen.queryByText(/state rejected/)).not.toBeInTheDocument()
  })

  it('leaves focus where it is when a run ends, and announces how it ended', async () => {
    localStorage.setItem(MOCK_AI_PACE_STORAGE_KEY, '5000')
    const run = await askResearch()
    const { rerender } = render(
      <>
        <textarea aria-label="Comment" />
        <RunCard ideaKey="CUST-2" run={run} />
      </>,
      { wrapper },
    )
    const comment = screen.getByRole('textbox', { name: 'Comment' })
    comment.focus()
    rerender(
      <>
        <textarea aria-label="Comment" />
        <RunCard
          ideaKey="CUST-2"
          run={{ ...run, status: 'succeeded', finished_at: new Date().toISOString() }}
        />
      </>,
    )
    await waitFor(() =>
      expect(document.querySelector('[aria-live="polite"]')).toHaveTextContent(
        'Research by Research agent: Research note saved',
      ),
    )
    await new Promise((resolve) => setTimeout(resolve, 100))
    expect(comment).toHaveFocus()
  })

  it('moves focus to the run when its Cancel had it and goes', async () => {
    localStorage.setItem(MOCK_AI_PACE_STORAGE_KEY, '5000')
    const run = await askResearch()
    const { rerender } = render(<RunCard ideaKey="CUST-2" run={{ ...run, can_cancel: true }} />, {
      wrapper,
    })
    const cancel = screen.getByRole('button', { name: /^Cancel: Researching/ })
    cancel.focus()
    rerender(
      <RunCard
        ideaKey="CUST-2"
        run={{ ...run, status: 'cancelled', finished_at: new Date().toISOString() }}
      />,
    )
    // jsdom leaves focus on a removed element: the browser would put it on <body>.
    if (!cancel.isConnected) document.body.focus()
    const card = document.getElementById(`ai-run-${run.id}`)
    await waitFor(() => expect(card).toHaveFocus())
    expect(screen.getByText('Cancelled: nothing was saved.')).toBeInTheDocument()
  })
})
