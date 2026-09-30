import AxeBuilder from '@axe-core/playwright'
import { test as base, type BrowserContext, type Page } from '@playwright/test'

/**
 * Shared Playwright fixtures for page tests against `npm run dev:mock`.
 *
 * - Every page starts signed in as Alice Anders (member of Customer
 *   Innovation, admin of Internal Tools, evaluator with 4 evaluations due).
 *   Override per file: `test.use({ signedInAs: USERS.priya })`, or
 *   `test.use({ signedInAs: null })` for the login page.
 * - Mock latency is off, so tests are fast and deterministic. Pages that
 *   test skeletons can set `localStorage['soundings-mock-latency'] = '800'`.
 * - The mock database is in memory: every page load starts from the same
 *   fixtures (src/mocks/db.ts).
 */
export { expect } from '@playwright/test'

/** Fixture user ids (src/mocks/db.ts USERS). */
export const USERS = {
  priya: '10000000-0000-4000-8000-000000000001', // platform admin
  alice: '10000000-0000-4000-8000-000000000002',
  bob: '10000000-0000-4000-8000-000000000003',
  emma: '10000000-0000-4000-8000-000000000006', // viewer in Customer Innovation
  ivan: '10000000-0000-4000-8000-00000000000a', // no project roles
} as const

export async function signIn(context: BrowserContext, baseURL: string, userId: string) {
  await context.addCookies([
    { name: 'soundings_mock_session', value: userId, url: baseURL },
    { name: 'soundings_csrf', value: 'playwright', url: baseURL },
  ])
}

export const test = base.extend<{ signedInAs: string | null }>({
  signedInAs: [USERS.alice, { option: true }],
  page: async ({ page, context, baseURL, signedInAs }, use) => {
    await page.addInitScript(() => {
      try {
        localStorage.setItem('soundings-mock-latency', 'none')
      } catch {
        // storage unavailable: realistic latency
      }
    })
    if (signedInAs && baseURL) await signIn(context, baseURL, signedInAs)
    await use(page)
  },
})

const WCAG_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']

/** axe violations of impact serious or critical (the bar: none). */
export async function seriousViolations(page: Page) {
  const results = await new AxeBuilder({ page }).withTags(WCAG_TAGS).analyze()
  return results.violations
    .filter((violation) => violation.impact === 'serious' || violation.impact === 'critical')
    .map((violation) => ({
      id: violation.id,
      impact: violation.impact,
      help: violation.help,
      targets: violation.nodes.slice(0, 5).map((node) => node.target.join(' ')),
    }))
}
