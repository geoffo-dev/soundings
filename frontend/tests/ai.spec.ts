import type { Page } from '@playwright/test'

import { expect, seriousViolations, test, USERS } from './support'

/**
 * AI assistance on the idea page and in the proposal editor (contract-phase6
 * §3.15) against the mock, whose pretend worker walks each run through the
 * steps the real one streams (SSE). CUST-2 (owner Alice; Bob and Carol
 * submitted, Dave pending) has no runs yet; CUST-7 (owner Carol; Alice pending)
 * has Idea evaluator's submitted evaluation, left out of the score; CUST-4 has a
 * research note and a run that timed out; CUST-3 is in Proposal.
 */

const CAROL = '10000000-0000-4000-8000-000000000004'

/** Knobs for the mock worker: ms per step, and how runs end. */
async function aiMock(page: Page, options: { pace?: number; outcome?: string } = {}) {
  await page.addInitScript(
    ({ pace, outcome }) => {
      localStorage.setItem('soundings-mock-ai-pace', String(pace))
      if (outcome) localStorage.setItem('soundings-mock-ai-outcome', outcome)
    },
    { pace: options.pace ?? 120, outcome: options.outcome ?? '' },
  )
}

const runCard = (page: Page) => page.locator('article[id^="ai-run-"]').first()
const sidebar = (page: Page) => page.getByRole('complementary', { name: 'Idea details' })

async function openIdea(page: Page, key: string, query = '') {
  await page.goto(`/ideas/${key}${query}`)
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
}

test('“Ask AI to evaluate”: live steps, a badged, cited evaluation left out of the score', async ({
  page,
}) => {
  await aiMock(page)
  const stream = page.waitForRequest(
    (request) => request.url().includes('/ai-runs/') && request.url().includes('/events'),
  )
  await openIdea(page, 'CUST-2')
  const evaluators = sidebar(page).getByRole('list', { name: 'Evaluators' })
  await expect(sidebar(page).getByText('2 evaluations')).toBeVisible()

  await sidebar(page).getByRole('button', { name: 'Ask AI to evaluate' }).click()
  // Focus moves to the AI evaluator's row (the button went away).
  await expect(
    page.getByRole('button', { name: /AI run (in progress|waiting to start)\. View progress/ }),
  ).toBeFocused()
  await expect(evaluators.getByText('Idea evaluator')).toBeVisible()
  await expect(evaluators).toContainText('AI agent')
  await stream // progress comes over the event stream (SSE), not polling

  const card = runCard(page)
  await expect(card.getByRole('heading', { name: /Idea evaluator/ })).toBeVisible()
  const steps = card.getByRole('list', { name: 'Steps' })
  await expect(steps).toContainText('Read the rubric')
  await expect(steps).toContainText('Evaluation submitted')
  await expect(card).toContainText('Done')
  await expect(card.getByText('Live updates aren’t available here')).toHaveCount(0)
  // The run held no score data, and the score didn't change.
  await expect(card).not.toContainText(/\b[1-5] out of 5\b|Rationale|example\.org/)
  await expect(sidebar(page).getByText('2 evaluations')).toBeVisible()
  await expect(evaluators.getByRole('img', { name: 'Submitted', exact: true })).toHaveCount(3)

  await card.getByRole('button', { name: 'View the evaluation' }).click()
  await expect(page.getByRole('tab', { name: /^Evaluations/, selected: true })).toBeVisible()
  const ai = page.locator('article[id^="evaluation-card-"]').filter({ hasText: 'Idea evaluator' })
  await expect(ai).toBeFocused()
  await expect(ai).toContainText('Not in score')
  await expect(ai).toContainText('Rationale')
  const sources = ai.getByRole('list', { name: 'Sources cited by AI, not checked' }).first()
  const link = sources.getByRole('link').first()
  await expect(link).toHaveAttribute('rel', 'noopener noreferrer nofollow')
  await expect(link).toHaveAttribute('target', '_blank')
  await expect(sources).toContainText('example.org')

  const include = ai.getByRole('switch', {
    name: /Include Idea evaluator’s evaluation in the score/,
  })
  await include.click()
  await expect(include).toBeChecked()
  await expect(sidebar(page).getByText('3 evaluations')).toBeVisible()
  await expect(ai).not.toContainText('Not in score')
  await include.click()
  await expect(include).not.toBeChecked()
  await expect(sidebar(page).getByText('2 evaluations')).toBeVisible()
})

test('a pending evaluator sees the AI evaluator and its run, never its scores', async ({
  page,
}) => {
  await openIdea(page, 'CUST-7') // Alice hasn't submitted
  const evaluators = sidebar(page).getByRole('list', { name: 'Evaluators' })
  await expect(evaluators.getByText('Idea evaluator')).toBeVisible()
  const card = runCard(page)
  await expect(card).toContainText('Evaluation submitted')
  // No way to the evaluation itself: the tab is blind.
  await expect(card.getByRole('button', { name: 'View the evaluation' })).toHaveCount(0)
  await card.getByRole('button', { name: /Steps/ }).click()
  await expect(card.getByRole('list', { name: 'Steps' })).toContainText('Saved its evaluation')
  await expect(page.getByRole('main')).not.toContainText(/Rationale|Cited by AI|example\.org/)
  // The agent's lines in the feed carry the AI label too, as subject and as object.
  const feed = page.getByRole('list', { name: 'Activity, oldest first' })
  await expect(
    feed.getByRole('listitem').filter({ hasText: 'submitted an evaluation' }).last(),
  ).toContainText('Idea evaluator AI agent submitted an evaluation')
  await expect(
    feed.getByRole('listitem').filter({ hasText: /invited .*Idea evaluator/ }),
  ).toContainText('Idea evaluator AI agent to evaluate')
  // Members and evaluators get no AI actions.
  await expect(page.getByRole('button', { name: 'AI actions' })).toHaveCount(0)
  await page.getByRole('tab', { name: /^Evaluations/ }).click()
  await expect(page.getByText('Hidden until you submit').first()).toBeVisible()
})

test('cancel stops a working run; the assignment it made is taken back', async ({ page }) => {
  await aiMock(page, { outcome: 'slow' })
  await openIdea(page, 'CUST-2')
  await page.getByRole('button', { name: 'AI actions' }).first().click()
  await page.getByRole('menuitem', { name: /Ask AI to evaluate/ }).click()
  const card = runCard(page)
  await expect(card.getByRole('list', { name: 'Steps' })).toContainText('Read the rubric')
  // While it runs the menu offers its progress instead of a second run.
  await page.getByRole('button', { name: 'AI actions' }).first().click()
  await expect(page.getByRole('menuitem', { name: /Evaluating…/ })).toBeVisible()
  await page.keyboard.press('Escape')

  await card.getByRole('button', { name: /^Cancel: Evaluating/ }).click()
  await expect(card).toContainText('Cancelled')
  await expect(sidebar(page).getByText('Idea evaluator')).toHaveCount(0)
  await expect(page.getByText('ended its run without an evaluation')).toBeVisible()
})

test('a failed run says why in Soundings’ words and offers “Try again”', async ({ page }) => {
  await aiMock(page, { outcome: 'fail' })
  await openIdea(page, 'CUST-2')
  await sidebar(page).getByRole('button', { name: 'Ask AI to evaluate' }).click()
  const card = runCard(page)
  await expect(card).toContainText('The agent stopped with an error.')
  await expect(card.getByText('Failed')).toBeVisible()
  await expect(card.getByRole('button', { name: 'Try again' })).toBeVisible()
})

test('“Research this” adds a cited research note to the feed', async ({ page }) => {
  await aiMock(page)
  await openIdea(page, 'CUST-2')
  await page.getByRole('button', { name: 'AI actions' }).first().click()
  await page.getByRole('menuitem', { name: 'Research this' }).click()
  await page.getByRole('menuitem', { name: 'Research agent' }).click()
  const card = runCard(page)
  await expect(card).toContainText('Research note saved')
  await card.getByRole('button', { name: 'Read the note' }).click()
  const note = page.locator('article[id^="research-note-"]')
  await expect(note).toBeFocused()
  await expect(note).toContainText('Research note by Research agent')
  await expect(note).toContainText('AI agent')
  const sources = note.getByRole('list', { name: 'Cited by AI, not checked' })
  await expect(sources.getByRole('listitem')).toHaveCount(3)
  await expect(sources.getByRole('link').first()).toHaveAttribute(
    'rel',
    'noopener noreferrer nofollow',
  )
})

test('the owner deletes a research note after confirming', async ({ page }) => {
  await openIdea(page, 'CUST-4')
  const note = page.locator('article[id^="research-note-"]')
  await expect(note).toContainText('What comparable programmes did')
  // Agent links show their host and open safely.
  await expect(note.getByRole('link', { name: 'developer survey' })).toHaveAttribute(
    'rel',
    'noopener noreferrer nofollow',
  )
  await expect(note).toContainText('(research.example.com)')
  await note.getByRole('button', { name: /Research note actions/ }).click()
  await page.getByRole('menuitem', { name: 'Delete note…' }).click()
  await page.getByRole('alertdialog').getByRole('button', { name: 'Delete note' }).click()
  await expect(note).toHaveCount(0)
  await expect(page.getByText('wrote a research note, since deleted')).toBeVisible()
})

test('“Draft with AI” on a section brings an AI suggestion to accept', async ({ page }) => {
  await aiMock(page)
  await openIdea(page, 'CUST-3', '?tab=proposal')
  await expect(page.getByTestId('proposal-editor')).toBeVisible()
  const risks = page.locator('#proposal-section-risks')
  await risks.getByRole('button', { name: 'Draft Risks with AI' }).click()
  const suggestion = risks.locator('article[id^="proposal-suggestion-"]')
  await expect(suggestion).toContainText('Research agent')
  await expect(suggestion).toContainText('AI agent')
  await suggestion.getByRole('button', { name: /^Accept/ }).click()
  await expect(suggestion).toHaveCount(0)
  await risks.getByRole('radio', { name: 'Preview' }).click()
  await expect(risks).toContainText('Check the facts before you accept this text.')
})

test.describe('without AI', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem('soundings-mock-ai', 'off'))
  })
  test('hides the AI actions while AI assistance is off', async ({ page }) => {
    await openIdea(page, 'CUST-2')
    await expect(sidebar(page).getByRole('heading', { name: 'Evaluators' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'AI actions' })).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Ask AI to evaluate' })).toHaveCount(0)
  })
})

test.describe('as the owner of CUST-7', () => {
  test.use({ signedInAs: CAROL })
  test('explains an AI action that can’t be done here', async ({ page }) => {
    await openIdea(page, 'CUST-7')
    await page.getByRole('button', { name: 'AI actions' }).first().click()
    // Its evaluator can evaluate again; research has two agents to choose from.
    await expect(page.getByRole('menuitem', { name: /Ask AI to evaluate/ })).toBeEnabled()
    await page.keyboard.press('Escape')
    await expect(
      sidebar(page).getByRole('button', { name: 'Ask AI to evaluate again' }),
    ).toBeVisible()
  })
})

test.describe('accessibility', () => {
  for (const scheme of ['light', 'dark'] as const) {
    test(`idea page with AI runs and notes has no serious axe violations (${scheme})`, async ({
      page,
    }) => {
      await page.emulateMedia({ colorScheme: scheme })
      await openIdea(page, 'CUST-4')
      await expect(page.locator('article[id^="research-note-"]')).toBeVisible()
      expect(await seriousViolations(page)).toEqual([])
    })
  }

  test('the AI evaluation card has no serious axe violations', async ({
    page,
    context,
    baseURL,
  }) => {
    await context.addCookies([{ name: 'soundings_mock_session', value: CAROL, url: baseURL ?? '' }])
    await openIdea(page, 'CUST-7', '?tab=evaluations')
    await expect(page.getByRole('switch', { name: /Include Idea evaluator’s/ })).toBeVisible()
    expect(await seriousViolations(page)).toEqual([])
  })

  test('the run card works by keyboard and stays inside 390 px', async ({ page }) => {
    await aiMock(page, { outcome: 'slow' })
    await page.setViewportSize({ width: 390, height: 844 })
    await openIdea(page, 'CUST-2')
    await page.getByRole('button', { name: 'AI actions' }).focus()
    await page.keyboard.press('Enter')
    // Opened by keyboard: the first item has focus.
    await expect(page.getByRole('menuitem', { name: /Ask AI to evaluate/ })).toBeFocused()
    await page.keyboard.press('Enter')
    const card = runCard(page)
    await expect(card.getByRole('list', { name: 'Steps' })).toContainText('Read the rubric')
    const width = await page.evaluate(() => document.documentElement.scrollWidth)
    expect(width).toBeLessThanOrEqual(390)
    expect(await seriousViolations(page)).toEqual([])
  })
})

test('admins see the AI menu on any idea of a project its agents serve', async ({
  page,
  context,
  baseURL,
}) => {
  await context.addCookies([
    { name: 'soundings_mock_session', value: USERS.priya, url: baseURL ?? '' },
  ])
  await openIdea(page, 'CUST-1')
  await expect(page.getByRole('button', { name: 'AI actions' }).first()).toBeVisible()
})
