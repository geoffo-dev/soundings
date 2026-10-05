import { QueryClientProvider, type QueryClient } from '@tanstack/react-query'
import {
  createMemoryHistory,
  createRootRoute,
  createRouter,
  RouterProvider,
} from '@tanstack/react-router'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from 'vitest'

import { api } from '@/api/client'
import { createQueryClient } from '@/api/query'
import type { CurrentUser, IdeaDetail } from '@/api/types'
import { TooltipProvider } from '@/components/ui/tooltip'
import { resetDb, USERS } from '@/mocks/db'
import { server } from '@/mocks/server'
import { endSession } from '@/mocks/session'

import { ProposalPanel } from './proposal-panel'

let queryClient: QueryClient

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
beforeEach(() => {
  resetDb()
  localStorage.setItem('soundings-mock-latency', 'none')
  queryClient = createQueryClient()
})
afterEach(() => {
  server.resetHandlers()
  endSession()
  queryClient.clear()
})
afterAll(() => server.close())

async function renderPanel(userId: string, ideaKey: string) {
  await api.POST('/api/v1/auth/dev/login', { body: { user_id: userId } })
  const me = (await api.GET('/api/v1/auth/me')).data as CurrentUser
  const idea = (await api.GET('/api/v1/ideas/{idea}', { params: { path: { idea: ideaKey } } }))
    .data as IdeaDetail
  const rootRoute = createRootRoute({
    component: () => <ProposalPanel ideaKey={ideaKey} idea={idea} me={me} archived={false} />,
  })
  const router = createRouter({
    routeTree: rootRoute,
    history: createMemoryHistory({ initialEntries: ['/'] }),
  })
  render(
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <RouterProvider router={router} />
      </TooltipProvider>
    </QueryClientProvider>,
  )
}

describe('ProposalPanel', () => {
  it('lets the owner start a proposal on a shortlisted idea', async () => {
    const user = userEvent.setup()
    await renderPanel(USERS.alice, 'CUST-4')
    expect(await screen.findByRole('heading', { name: 'Write the proposal' })).toBeVisible()
    expect(screen.getByText(/Starting it moves the idea to Proposal/)).toBeVisible()
    await user.click(screen.getByRole('button', { name: 'Start proposal' }))
    // The eight sections, Summary seeded from the idea's summary (jsdom is phone-sized:
    // written sections open in Preview there).
    const summary = await screen.findByRole('region', { name: '1. Summary' })
    expect(
      within(summary).getByText(
        'Open a documented API so marketplace sellers can sync stock and orders.',
      ),
    ).toBeVisible()
    expect(screen.getByRole('textbox', { name: 'Problem' })).toHaveValue('')
    expect(screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent)).toEqual(
      expect.arrayContaining(['1. Summary', '8. Next steps / the ask']),
    )
  })

  it('says when a proposal becomes available', async () => {
    await renderPanel(USERS.alice, 'CUST-5')
    expect(
      await screen.findByRole('heading', { name: 'Available once the idea is shortlisted' }),
    ).toBeVisible()
    expect(screen.queryByRole('button', { name: 'Start proposal' })).not.toBeInTheDocument()
  })

  it('shows viewers the proposal read-only, with export but no editing or commenting', async () => {
    await renderPanel(USERS.emma, 'CUST-3')
    const problem = await screen.findByRole('region', { name: '2. Problem' })
    expect(within(problem).getByText(/Repeat purchase rate dropped/)).toBeVisible()
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Comment/ })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Export' })).toBeEnabled()
    // Empty sections say so, instead of showing the prompt.
    expect(
      within(screen.getByRole('region', { name: '6. Benefits / revenue' })).getByText(
        'Not written yet.',
      ),
    ).toBeVisible()
  })

  it('autosaves a section and says so', async () => {
    const user = userEvent.setup()
    await renderPanel(USERS.alice, 'CUST-3')
    const risks = await screen.findByRole('textbox', { name: 'Risks' })
    await user.type(risks, 'Supplier delays')
    await waitFor(
      async () => {
        const { data } = await api.GET('/api/v1/ideas/{idea}/proposal', {
          params: { path: { idea: 'CUST-3' } },
        })
        expect(data?.proposal?.sections.find((s) => s.key === 'risks')?.body_md).toBe(
          'Supplier delays',
        )
      },
      { timeout: 3000 },
    )
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent(/^Saved/))
  }, 15_000)
})
