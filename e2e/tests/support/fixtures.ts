import AxeBuilder from '@axe-core/playwright'
import { test as base, expect, type Locator, type Page } from '@playwright/test'

import { Api, PEOPLE, userOf, type Person } from './api'

export { expect }

/**
 * Fixtures for the e2e suite:
 *
 * - `api(person)`: a signed-in API client (disposed after the test).
 * - `signIn(page, person)`: signs the page's browser context in with the dev login
 *   through the API (fast), then the app treats it like any session. The acceptance
 *   test switches users through the real login page instead (`switchUserInUi`).
 */
export const test = base.extend<{
  api: (person: Person) => Promise<Api>
}>({
  api: async ({ baseURL }, use) => {
    const clients: Api[] = []
    await use(async (person) => {
      const client = await Api.as(baseURL ?? '', person)
      clients.push(client)
      return client
    })
    for (const client of clients) {
      await client.archiveCreated()
      await client.dispose()
    }
  },
})

/** Signs `page`'s context in as `person` (cookies land in the browser context). */
export async function signIn(page: Page, person: Person) {
  const user = await userOf(testBaseURL(), person)
  const response = await page.request.post('/api/v1/auth/dev/login', {
    data: { user_id: user.id },
  })
  expect(response.status()).toBe(200)
}

function testBaseURL(): string {
  const url = test.info().project.use.baseURL
  if (!url) throw new Error('baseURL is not configured')
  return url
}

/** Signs out from the account menu, then picks `person` on the login page. */
export async function switchUserInUi(page: Page, person: Person) {
  const name = PEOPLE[person]
  const menu = page.getByRole('button', { name: /^Account menu for / })
  if (await menu.isVisible()) {
    await menu.click()
    await page.getByRole('menuitem', { name: 'Sign out' }).click()
    await expect(page).toHaveURL(/\/login/)
  } else {
    await page.goto('/login')
  }
  await page.getByRole('textbox', { name: 'Filter people' }).fill(name.split(' ')[0] ?? name)
  await page.getByRole('button', { name: new RegExp(name) }).click()
  await expect(page.getByRole('button', { name: `Account menu for ${name}` })).toBeVisible()
}

// --- Locators shared by several specs --------------------------------------------------
export const heading = (page: Page, name: string | RegExp) =>
  page.getByRole('heading', { level: 1, name })
export const details = (page: Page) => page.getByRole('complementary', { name: 'Idea details' })
/** Waits until nothing on the page is a loading skeleton. */
export async function settled(page: Page) {
  await expect(page.locator('[data-slot="skeleton"]')).toHaveCount(0)
}

/** Opens an idea page and waits until it is interactive (title and sidebar painted). */
export async function openIdea(page: Page, key: string) {
  await page.goto(`/ideas/${key}`)
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
  await expect(details(page).getByRole('heading', { name: 'Score' })).toBeVisible()
}
export const toast = (page: Page, text: string | RegExp) =>
  page.locator('[data-sonner-toast]', { hasText: text })
export const primaryAction = (page: Page) => page.locator('[data-primary-action]:visible')
export const evaluateSheet = (page: Page) =>
  page.getByRole('dialog', { name: /^(Evaluate|Your evaluation)$/ })

export async function pickScore(dialog: Locator, criterion: string, value: number) {
  await dialog
    .getByRole('radiogroup', { name: criterion, exact: true })
    .getByRole('radio', { name: String(value), exact: true })
    .click()
}

export async function pickRecommendation(dialog: Locator, value: 'Go' | 'Maybe' | 'No') {
  await dialog
    .getByRole('radiogroup', { name: 'Overall recommendation' })
    .getByRole('radio', { name: value })
    .click()
}

/** Text that reveals score data: a 1-decimal number such as "3.7". */
export const SCORE_TEXT = /\b[1-5]\.\d\b/

// --- Accessibility ---------------------------------------------------------------------
const WCAG_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']

/** axe violations of impact serious or critical on the page (the bar: none). */
export async function seriousViolations(page: Page, include?: string) {
  let builder = new AxeBuilder({ page }).withTags(WCAG_TAGS)
  if (include) builder = builder.include(include)
  const results = await builder.analyze()
  return results.violations
    .filter((violation) => violation.impact === 'serious' || violation.impact === 'critical')
    .map((violation) => ({
      id: violation.id,
      impact: violation.impact,
      help: violation.help,
      targets: violation.nodes.slice(0, 5).map((node) => node.target.join(' ')),
      // e.g. "insufficient color contrast of 3.9 (foreground #…, background #…)"
      detail: violation.nodes[0]?.any[0]?.message ?? violation.nodes[0]?.failureSummary ?? '',
    }))
}
