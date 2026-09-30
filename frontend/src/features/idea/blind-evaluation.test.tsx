import type { QueryClient } from '@tanstack/react-query'
import { screen, waitFor, within } from '@testing-library/react'
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from 'vitest'

import { createQueryClient } from '@/api/query'
import { resetDb, USERS } from '@/mocks/db'
import { server } from '@/mocks/server'
import { endSession } from '@/mocks/session'

import { EvaluationsTab } from './evaluations-tab'
import { IdeaProperties } from './idea-sidebar'
import { renderWithIdea, signInAs } from './test-harness'

/**
 * Blind evaluation (role matrix §3) as the idea page renders it: a pending
 * evaluator sees no score data anywhere — no aggregate, no bars, no counts of
 * recommendations, no other evaluator's scores — and the page doesn't even ask
 * for the evaluations. Everyone else sees them.
 */
let queryClient: QueryClient
const requests: string[] = []

beforeAll(() => {
  server.listen({ onUnhandledRequest: 'error' })
  server.events.on('request:start', ({ request }) => requests.push(new URL(request.url).pathname))
})
beforeEach(() => {
  resetDb()
  localStorage.setItem('soundings-mock-latency', 'none')
  queryClient = createQueryClient()
  requests.length = 0
})
afterEach(() => {
  server.resetHandlers()
  endSession()
  queryClient.clear()
})
afterAll(() => server.close())

/** Anything that looks like score data: an aggregate "3.8", a "mean", tallies, bars. */
function expectNoScoreData(root: HTMLElement) {
  const text = root.textContent
  expect(text).not.toMatch(/\d\.\d/)
  expect(text).not.toMatch(/\bmean\b/i)
  expect(text).not.toMatch(/High disagreement/)
  expect(text).not.toMatch(/Maybe\s*\d/)
  expect(within(root).queryAllByRole('meter')).toHaveLength(0)
  expect(within(root).queryAllByRole('img', { name: /out of 5/ })).toHaveLength(0)
}

describe('a pending evaluator (Alice on CUST-1, two others submitted)', () => {
  beforeEach(() => signInAs(USERS.alice))

  it('sees the hidden state in the sidebar, but the evaluators and their progress', async () => {
    const { container } = renderWithIdea(queryClient, 'CUST-1', <IdeaProperties />)
    expect(await screen.findByText('Hidden until you submit')).toBeInTheDocument()
    expect(screen.getByText(/Submit your evaluation to see scores/)).toBeInTheDocument()
    // Progress is not score data (contract §3.7): who submitted is visible.
    expect(screen.getByRole('img', { name: '2 of 3 evaluations submitted' })).toBeInTheDocument()
    expect(screen.getAllByRole('img', { name: 'Submitted' })).toHaveLength(2)
    expect(screen.getByRole('img', { name: 'Not submitted yet' })).toBeInTheDocument()
    expectNoScoreData(container)
  })

  it('sees the blind state on the Evaluations tab and never fetches the evaluations', async () => {
    const { container } = renderWithIdea(queryClient, 'CUST-1', <EvaluationsTab />)
    expect(await screen.findByText('Hidden until you submit')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Evaluate now' })).toBeInTheDocument()
    expectNoScoreData(container)
    expect(requests.some((path) => path.endsWith('/evaluations'))).toBe(false)
  })

  it('keeps it hidden even when the evaluations endpoint would answer', async () => {
    // Belt and braces: the tab renders from `score_hidden`, not from what a list returns.
    const { container } = renderWithIdea(queryClient, 'CUST-1', <EvaluationsTab />)
    await screen.findByText('Hidden until you submit')
    expect(within(container).queryByText('Carol Díaz')).not.toBeInTheDocument()
  })
})

describe('the owner, who is not an evaluator (Alice on CUST-2)', () => {
  beforeEach(() => signInAs(USERS.alice))

  it('sees the aggregate, the disagreement flag and one bar per criterion', async () => {
    renderWithIdea(queryClient, 'CUST-2', <IdeaProperties />)
    expect(await screen.findByText('3.1')).toBeInTheDocument()
    expect(screen.getByText('High disagreement')).toBeInTheDocument()
    expect(screen.getAllByRole('meter')).toHaveLength(5)
    expect(screen.queryByText('Hidden until you submit')).not.toBeInTheDocument()
  })

  it('sees every submitted evaluation with its scores and the comparison', async () => {
    renderWithIdea(queryClient, 'CUST-2', <EvaluationsTab />)
    expect(await screen.findByText('2 submitted of 3')).toBeInTheDocument()
    await waitFor(() => expect(screen.getAllByRole('article')).toHaveLength(2))
    const bob = screen.getByRole('article', { name: 'Bob Chen' })
    const carol = screen.getByRole('article', { name: 'Carol Díaz' })
    expect(within(bob).getByRole('heading', { name: 'Bob Chen' })).toBeVisible()
    expect(within(carol).getByText('Carrier integration is the risk.')).toBeVisible()
    expect(screen.getByRole('table', { name: 'Scores by criterion and evaluator' })).toBeVisible()
    expect(screen.getAllByRole('img', { name: 'Carol Díaz: 5 out of 5' })).toHaveLength(2)
    expect(screen.getByText('Waiting for Dave Okafor')).toBeInTheDocument()
  })
})

describe('a viewer (Emma, viewer in Customer Innovation)', () => {
  beforeEach(() => signInAs(USERS.emma))

  it('sees scores but no controls', async () => {
    renderWithIdea(queryClient, 'CUST-1', <IdeaProperties />)
    await waitFor(() => expect(screen.getAllByRole('meter')).toHaveLength(5))
    expect(screen.queryByText('Hidden until you submit')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Invite evaluators/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Change status/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Remove .* as evaluator/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Edit tags' })).not.toBeInTheDocument()
  })
})
