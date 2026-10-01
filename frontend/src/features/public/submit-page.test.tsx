import { QueryClientProvider, type QueryClient } from '@tanstack/react-query'
import {
  createMemoryHistory,
  createRootRoute,
  createRouter,
  RouterProvider,
} from '@tanstack/react-router'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

import { createQueryClient } from '@/api/query'
import type { AltchaChallenge, PublicSubmissionCreate } from '@/api/types'
import { TooltipProvider } from '@/components/ui/tooltip'
import { resetBranding, resetRuntimeBranding } from '@/lib/branding'
import { resetDb } from '@/mocks/db'
import { problemResponse } from '@/mocks/http'
import { server } from '@/mocks/server'

import { PublicSubmitPage } from './submit-page'

let queryClient: QueryClient
let solved: AltchaChallenge[]
let solves: number

/** A stand-in for the proof of work (jsdom has no workers): a payload per challenge. */
const solver = vi.fn((challenge: AltchaChallenge) => {
  solved.push(challenge)
  solves += 1
  return Promise.resolve(btoa(JSON.stringify({ n: solves, s: challenge.signature })))
})

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
beforeEach(() => {
  resetDb()
  localStorage.setItem('soundings-mock-latency', 'none')
  queryClient = createQueryClient()
  solved = []
  solves = 0
  solver.mockClear()
})
afterEach(() => {
  server.resetHandlers()
  queryClient.clear()
  resetRuntimeBranding()
  resetBranding()
})
afterAll(() => server.close())

function renderForm(slug = 'customer-innovation') {
  const rootRoute = createRootRoute({
    component: () => <PublicSubmitPage slug={slug} solver={solver} />,
  })
  const router = createRouter({
    routeTree: rootRoute,
    history: createMemoryHistory({ initialEntries: ['/'] }),
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <RouterProvider router={router} />
      </TooltipProvider>
    </QueryClientProvider>,
  )
}

/** Records what the form posts, then lets the mock API answer (or answers itself). */
function capture(answer?: (body: PublicSubmissionCreate, n: number) => Response | undefined) {
  const bodies: PublicSubmissionCreate[] = []
  server.use(
    http.post('*/api/v1/public/projects/:slug/submissions', async ({ request }) => {
      expect(request.headers.get('Content-Type')).toMatch(/^application\/json/)
      const body = (await request.clone().json()) as PublicSubmissionCreate
      bodies.push(body)
      return answer?.(body, bodies.length)
    }),
  )
  return bodies
}

async function fillAndSend(user: ReturnType<typeof userEvent.setup>) {
  await user.type(await screen.findByRole('textbox', { name: /^Title/ }), 'Print-free returns')
  await user.type(screen.getByRole('textbox', { name: /^Summary/ }), 'Return parcels with a QR code.')
  await user.click(screen.getByRole('button', { name: /Send idea/ }))
}

describe('the public form', () => {
  it('shows the project’s name and intro, and nothing else about it', async () => {
    renderForm()
    expect(
      await screen.findByRole('heading', { level: 1, name: 'Share an idea with Customer Innovation' }),
    ).toBeVisible()
    expect(screen.getByText(/A real person on the Customer Innovation team/)).toBeVisible()
    expect(screen.getByText(/The team reviews new ideas first/)).toBeVisible()
    expect(screen.getByRole('heading', { name: 'Your privacy' })).toBeVisible()
    expect(screen.getByText(/We don’t store your IP address/)).toBeVisible()
  })

  it('has a honeypot no person can reach or autofill', async () => {
    const { container } = renderForm()
    await screen.findByRole('heading', { level: 1 })
    const trap = container.querySelector<HTMLInputElement>('#hp_ref')
    expect(trap).not.toBeNull()
    expect(trap?.name).toBe('hp_ref')
    expect(trap?.tabIndex).toBe(-1)
    expect(trap?.getAttribute('autocomplete')).toBe('off')
    expect(trap?.closest('[aria-hidden="true"]')).not.toBeNull()
    // Not display:none (some bots skip those), not a name browsers fill in.
    expect(trap?.closest('.sr-only')).not.toBeNull()
    expect(container.querySelectorAll('input[name="website"], input[name="url"]')).toHaveLength(0)
    // Not in the accessible form.
    expect(screen.queryByRole('textbox', { name: 'Leave this empty' })).toBeNull()
  })

  it('solves a challenge for this form and sends the idea as JSON', async () => {
    const user = userEvent.setup()
    const bodies = capture()
    renderForm()
    await fillAndSend(user)
    expect(await screen.findByRole('heading', { name: 'Thanks! Your idea is in' })).toBeVisible()
    // One challenge, fetched for this project (signed data passed through untouched).
    expect(solver).toHaveBeenCalledTimes(1)
    expect(solved[0]?.parameters.data).toEqual({ project: 'customer-innovation' })
    expect(bodies).toHaveLength(1)
    expect(bodies[0]).toMatchObject({
      title: 'Print-free returns',
      summary: 'Return parcels with a QR code.',
      name: null,
      email: null,
      wants_updates: false,
      website: '',
    })
    expect(bodies[0]?.altcha).toBe(btoa(JSON.stringify({ n: 1, s: solved[0]?.signature })))
    // The private link, once, with Copy.
    const link = screen.getByRole<HTMLInputElement>('textbox', { name: 'Your private link' })
    expect(link.value).toMatch(/\/track#[A-Za-z0-9_-]{43}$/)
    expect(screen.getByRole('button', { name: 'Copy link' })).toBeVisible()
    expect(screen.getByText('The team reviews new ideas first')).toBeVisible()
  })

  it('says the link was emailed when an address was given', async () => {
    const user = userEvent.setup()
    renderForm()
    await user.type(await screen.findByRole('textbox', { name: /^Your email/ }), 'jo@example.org')
    await user.click(screen.getByRole('checkbox', { name: 'Email me when the status changes' }))
    await fillAndSend(user)
    expect(await screen.findByText('We’ve also emailed it to you')).toBeVisible()
  })

  it('checks fields first and moves focus to the first problem', async () => {
    const user = userEvent.setup()
    const bodies = capture()
    renderForm()
    await screen.findByRole('heading', { level: 1 })
    await user.type(screen.getByRole('textbox', { name: /^Summary/ }), 'Only a summary')
    await user.click(screen.getByRole('button', { name: /Send idea/ }))
    const title = screen.getByRole('textbox', { name: /^Title/ })
    expect(title).toHaveFocus()
    expect(title).toHaveAccessibleDescription(/Give your idea a short title/)
    expect(bodies).toHaveLength(0)
  })

  it('tries a fresh challenge once when the API refuses one, then offers Retry', async () => {
    const user = userEvent.setup()
    const bodies = capture(() => problemResponse(422, 'challenge_failed'))
    renderForm()
    await fillAndSend(user)
    expect(await screen.findByRole('alert')).toHaveTextContent('We couldn’t verify this browser')
    expect(bodies).toHaveLength(2)
    // Each attempt used its own solution (a payload is accepted once).
    expect(bodies[0]?.altcha).not.toBe(bodies[1]?.altcha)
    expect(screen.getByRole('textbox', { name: /^Title/ })).toHaveValue('Print-free returns')
  })

  it('recovers when the second challenge passes', async () => {
    const user = userEvent.setup()
    const bodies = capture((_body, n) => (n === 1 ? problemResponse(422, 'challenge_failed') : undefined))
    renderForm()
    await fillAndSend(user)
    expect(await screen.findByRole('heading', { name: 'Thanks! Your idea is in' })).toBeVisible()
    expect(bodies).toHaveLength(2)
  })

  it('says so kindly when this browser has sent too many ideas', async () => {
    const user = userEvent.setup()
    capture(() => problemResponse(429, 'too_many_attempts'))
    renderForm()
    await fillAndSend(user)
    expect(
      await screen.findByText('You’ve sent several ideas in a short time'),
    ).toBeVisible()
    expect(screen.getByText(/Try again in a few minutes/)).toBeVisible()
    expect(screen.getByRole('textbox', { name: /^Title/ })).toHaveValue('Print-free returns')
  })

  it('shows the same page for a form that is off, unknown or reserved', async () => {
    renderForm('internal-tools')
    expect(await screen.findByRole('heading', { name: 'This form isn’t available' })).toBeVisible()
  })

  it('asks for an address when the project requires confirmation', async () => {
    renderForm('sustainability')
    expect(await screen.findByRole('textbox', { name: /^Your email/ })).toBeRequired()
    expect(screen.getByText(/it reaches the team once you do/)).toBeVisible()
  })
})
