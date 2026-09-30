import type { QueryClient } from '@tanstack/react-query'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http } from 'msw'
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from 'vitest'

import { createQueryClient } from '@/api/query'
import { resetDb, USERS } from '@/mocks/db'
import { problemResponse } from '@/mocks/http'
import { server } from '@/mocks/server'
import { endSession } from '@/mocks/session'

import { EvaluateSheet } from './evaluate-sheet'
import { renderWithIdea, signInAs } from './test-harness'

let queryClient: QueryClient

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
beforeEach(async () => {
  resetDb()
  localStorage.setItem('soundings-mock-latency', 'none')
  queryClient = createQueryClient()
  await signInAs(USERS.alice)
})
afterEach(() => {
  server.resetHandlers()
  endSession()
  queryClient.clear()
})
afterAll(() => server.close())

const CRITERIA = ['Value', 'Feasibility', 'Effort', 'Strategic fit', 'Risk']

async function openSheet() {
  renderWithIdea(queryClient, 'CUST-1', <EvaluateSheet open onOpenChange={() => undefined} />)
  const sheet = await screen.findByRole('dialog', { name: 'Evaluate' })
  await within(sheet).findByRole('radiogroup', { name: 'Value' })
  return sheet
}

describe('EvaluateSheet', () => {
  it('shows one 1–5 group per criterion, with the rubric guidance', async () => {
    const sheet = await openSheet()
    for (const name of CRITERIA) {
      const group = within(sheet).getByRole('radiogroup', { name })
      expect(within(group).getAllByRole('radio')).toHaveLength(5)
    }
    const value = within(sheet).getByRole('radiogroup', { name: 'Value' })
    expect(within(value).getByRole('radio', { name: '5' })).toHaveAccessibleDescription(
      '5 · A major benefit for many customers or the whole organisation.',
    )
    // Inverted criteria say so in words.
    expect(within(sheet).getByRole('radiogroup', { name: 'Effort' })).toHaveAccessibleDescription(
      /Lower is better/,
    )
    expect(within(sheet).getByText('0 of 5 scored')).toBeInTheDocument()
  })

  it('won’t submit with gaps: marks each one and moves focus to the first', async () => {
    const user = userEvent.setup()
    const sheet = await openSheet()
    const value = within(sheet).getByRole('radiogroup', { name: 'Value' })
    await user.click(within(value).getByRole('radio', { name: '4' }))
    await user.click(within(sheet).getByRole('button', { name: /^Submit/ }))

    expect(within(sheet).getAllByText('Pick a score')).toHaveLength(4)
    expect(within(sheet).getByText('Choose Go, Maybe or No')).toBeInTheDocument()
    // Shown in the footer and announced in the sheet's live region.
    expect(
      within(sheet).getAllByText('4 criteria need a score, and choose Go, Maybe or No'),
    ).toHaveLength(2)
    const feasibility = within(sheet).getByRole('radiogroup', { name: 'Feasibility' })
    expect(feasibility).toHaveAccessibleDescription(/Pick a score/)
    await waitFor(() => expect(within(feasibility).getByRole('radio', { name: '1' })).toHaveFocus())

    // Fixing a gap clears its message, not the others.
    await user.click(within(feasibility).getByRole('radio', { name: '3' }))
    expect(within(sheet).getAllByText('Pick a score')).toHaveLength(3)
  })

  it('autosaves a draft and says so', async () => {
    const user = userEvent.setup()
    const sheet = await openSheet()
    const value = within(sheet).getByRole('radiogroup', { name: 'Value' })
    await user.click(within(value).getByRole('radio', { name: '2' }))
    expect(await within(sheet).findByText(/^Draft saved/, {}, { timeout: 3000 })).toBeVisible()
    const saved = await fetch(`${window.location.origin}/api/v1/ideas/CUST-1/evaluations/me`)
    const body = (await saved.json()) as { state: string; scores: { score: number | null }[] }
    expect(body.state).toBe('draft')
    expect(body.scores.map((score) => score.score)).toEqual([2, null, null, null, null])
  })

  it('submits a complete evaluation, then reveals the others’ scores', async () => {
    const user = userEvent.setup()
    const sheet = await openSheet()
    for (const [index, name] of CRITERIA.entries()) {
      const group = within(sheet).getByRole('radiogroup', { name })
      await user.click(within(group).getByRole('radio', { name: String((index % 5) + 1) }))
    }
    const recommendation = within(sheet).getByRole('radiogroup', {
      name: 'Overall recommendation',
    })
    await user.click(within(recommendation).getByRole('radio', { name: 'Go' }))
    expect(within(sheet).getByText('5 of 5 scored')).toBeInTheDocument()

    await user.click(within(sheet).getByRole('button', { name: /^Submit/ }))

    const reveal = await screen.findByRole('dialog', { name: 'Your evaluation' })
    // Carol and Dave submitted before: their scores are now shown next to yours.
    expect(
      await within(reveal).findAllByRole('img', { name: /^Carol Díaz: \d out of 5$/ }),
    ).toHaveLength(5)
    expect(within(reveal).getAllByRole('img', { name: /^Dave Okafor: \d out of 5$/ })).toHaveLength(
      5,
    )
    expect(within(reveal).getByRole('img', { name: 'Your score: 1 out of 5' })).toBeInTheDocument()
    expect(within(reveal).getByText(/3 evaluations/)).toBeInTheDocument()
    expect(within(reveal).getByRole('button', { name: 'Edit my evaluation' })).toBeEnabled()
  })

  it('keeps the draft and turns read-only when evaluation closed meanwhile', async () => {
    const user = userEvent.setup()
    const sheet = await openSheet()
    server.use(
      http.put('*/api/v1/ideas/:idea/evaluations/me', () =>
        problemResponse(409, 'evaluation_closed'),
      ),
    )
    for (const name of CRITERIA) {
      const group = within(sheet).getByRole('radiogroup', { name })
      await user.click(within(group).getByRole('radio', { name: '3' }))
    }
    await user.click(
      within(within(sheet).getByRole('radiogroup', { name: 'Overall recommendation' })).getByRole(
        'radio',
        { name: 'Maybe' },
      ),
    )
    await user.click(within(sheet).getByRole('button', { name: /^Submit/ }))
    expect(await within(sheet).findByRole('alert')).toHaveTextContent(
      /Evaluation was closed, so your evaluation wasn’t submitted/,
    )
    expect(
      within(within(sheet).getByRole('radiogroup', { name: 'Value' })).getByRole('radio', {
        name: '3',
      }),
    ).toBeDisabled()
  })
})
