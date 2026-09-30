import type { Page } from '@playwright/test'

import { expect, seriousViolations, test } from './support'

/**
 * The project List (wireframe 02): sortable, filterable, virtualised, with
 * j/k navigation; the view choice and filters live in the URL.
 */

const table = (page: Page) => page.getByRole('table', { name: 'Ideas' })
const rows = (page: Page) =>
  table(page)
    .getByRole('row')
    .filter({ has: page.getByRole('link') })
const countText = (page: Page) => page.getByText(/^\d[\d,]* (of [\d,]+ )?ideas?$/)

async function openList(page: Page, query = '') {
  await page.goto(`/p/customer-innovation?view=list${query}`)
  await expect(page.getByRole('heading', { level: 1, name: 'Customer Innovation' })).toBeVisible()
}

/** Score labels of the rendered rows, in order ("hidden" for the blind lock, null for none). */
async function rowScores(page: Page) {
  return rows(page).evaluateAll((nodes) =>
    nodes.map((row) => {
      const label = row.querySelector('[aria-label^="Score"], [aria-label^="Scores hidden"]')
      if (!label) return null
      const text = label.getAttribute('aria-label') ?? ''
      return text.startsWith('Scores hidden') ? 'hidden' : Number(/Score ([\d.]+)/.exec(text)?.[1])
    }),
  )
}

test('lists ideas, newest activity first, with owner, progress, score and status', async ({
  page,
}) => {
  await openList(page)
  await expect(countText(page)).toHaveText('20 ideas')
  await expect(page.getByRole('radio', { name: 'List' })).toBeChecked()
  await expect(page.getByRole('columnheader', { name: 'Updated' })).toHaveAttribute(
    'aria-sort',
    'descending',
  )
  const first = rows(page).first()
  await expect(first).toContainText('CUST-5')
  await expect(first).toContainText('Loyalty tiers for B2B customers')
  const hidden = rows(page).filter({ hasText: 'CUST-1' }).first()
  await expect(
    hidden.getByRole('img', { name: 'Scores hidden until you submit your evaluation' }),
  ).toBeVisible()
  await expect(hidden.getByRole('img', { name: '2 of 3 evaluations submitted' })).toBeVisible()
})

test('sorts by score through the API; hidden scores sort as unscored', async ({ page }) => {
  await openList(page)
  await page.getByRole('button', { name: 'Score', exact: true }).click()
  await expect(page).toHaveURL(/sort=-score/)
  const header = page.getByRole('columnheader', { name: 'Score' })
  await expect(header).toHaveAttribute('aria-sort', 'descending')
  await expect(page.getByRole('button', { name: /Highest score/ })).toBeVisible()

  const scores = await rowScores(page)
  const numbers = scores.filter((score): score is number => typeof score === 'number')
  expect(numbers.length).toBeGreaterThan(3)
  expect(numbers).toEqual([...numbers].sort((a, b) => b - a))
  // Every scored idea comes before any hidden or unscored one.
  expect(scores.slice(0, numbers.length).every((score) => typeof score === 'number')).toBe(true)

  await page.getByRole('button', { name: 'Score', exact: true }).click()
  await expect(page).toHaveURL(/sort=score/)
  await expect(header).toHaveAttribute('aria-sort', 'ascending')
  const ascending = (await rowScores(page)).filter((s): s is number => typeof s === 'number')
  expect(ascending).toEqual([...ascending].sort((a, b) => a - b))

  await page.getByRole('button', { name: 'Idea', exact: true }).click()
  await expect(page).toHaveURL(/sort=title/)
  await expect(rows(page).first()).toContainText('Accessibility audit of the storefront')
})

test('filters by owner, status, text and flags; filters are in the URL', async ({ page }) => {
  await openList(page)
  await page.getByRole('button', { name: /^Owner/ }).click()
  await page.getByRole('option', { name: 'Me' }).click()
  await expect(page).toHaveURL(/owner=me/)
  await expect(countText(page)).toHaveText(/^\d+ of 20 ideas$/)
  const mine = await rows(page).count()
  expect(mine).toBeGreaterThan(1)
  for (const row of await rows(page).all()) {
    await expect(row.getByRole('img', { name: 'Alice Anders' })).toBeVisible()
  }

  await page.getByRole('button', { name: /^Status/ }).click()
  await page.getByRole('option', { name: 'Evaluating' }).click()
  await page.keyboard.press('Escape')
  await expect(page).toHaveURL(/status=evaluating/)
  for (const row of await rows(page).all()) await expect(row).toContainText('Evaluating')

  // The filtered view is a link you can share.
  const shared = page.url()
  await page.goto(shared)
  await expect(page.getByRole('button', { name: /^Owner Me/ })).toBeVisible()
  await expect(page.getByRole('button', { name: /^Status Evaluating/ })).toBeVisible()

  await page.getByRole('button', { name: 'Remove owner filter' }).click()
  await expect(page).not.toHaveURL(/owner=/)

  await page.getByRole('searchbox', { name: 'Search ideas' }).fill('returns')
  await expect(page).toHaveURL(/q=returns/)
  await expect(rows(page)).toHaveCount(2)

  await page.getByRole('searchbox', { name: 'Search ideas' }).fill('zzzz')
  await expect(page.getByText('No ideas match these filters')).toBeVisible()
  await page.getByRole('button', { name: 'Clear filters' }).click()
  await expect(page).toHaveURL(/\/p\/customer-innovation\?view=list$/)
  await expect(page.getByRole('searchbox', { name: 'Search ideas' })).toHaveValue('')
  await expect(countText(page)).toHaveText('20 ideas')

  await page.getByRole('button', { name: 'High disagreement' }).click()
  await expect(page).toHaveURL(/high_disagreement=1/)
  await expect(page.getByRole('button', { name: 'High disagreement' })).toHaveAttribute(
    'aria-pressed',
    'true',
  )
  // Only flagged ideas whose scores Alice may see; her pending CUST-1 never matches.
  await expect(rows(page).filter({ hasText: 'CUST-2' })).toHaveCount(1)
  await expect(rows(page).filter({ hasText: 'CUST-1 ' })).toHaveCount(0)
})

test('j/k move between rows and Enter opens the idea', async ({ page }) => {
  await openList(page)
  await expect(rows(page).first()).toBeVisible()
  await page.keyboard.press('j')
  await expect(page.getByRole('link', { name: /Loyalty tiers for B2B customers/ })).toBeFocused()
  await page.keyboard.press('j')
  await expect(page.getByRole('link', { name: /Self-serve returns portal/ })).toBeFocused()
  await page.keyboard.press('ArrowDown')
  await page.keyboard.press('k')
  await expect(page.getByRole('link', { name: /Self-serve returns portal/ })).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(/\/ideas\/CUST-1$/)
})

test('remembers Board or List per project; v switches', async ({ page }) => {
  await page.goto('/p/customer-innovation')
  await expect(page.getByRole('radio', { name: 'Board' })).toBeChecked()
  await page.getByRole('radio', { name: 'List' }).click()
  await expect(page).toHaveURL(/view=list/)
  await page.goto('/p/internal-tools')
  await expect(page.getByRole('radio', { name: 'Board' })).toBeChecked()
  await page.goto('/p/customer-innovation')
  await expect(page.getByRole('radio', { name: 'List' })).toBeChecked()
  await expect(table(page)).toBeVisible()
  await page.keyboard.press('v')
  await expect(page).toHaveURL(/view=board/)
  await expect(page.getByRole('region', { name: /^New\b/ })).toBeVisible()
})

test('10,000 ideas: rows are virtualised and pages load as you scroll', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('soundings-mock-dataset', 'large'))
  await openList(page)
  await expect(countText(page)).toHaveText('10,020 ideas')
  expect(await rows(page).count()).toBeLessThan(80)

  const scroller = page.locator('[data-slot="table-container"]')
  for (let i = 0; i < 6; i += 1) {
    await scroller.evaluate((node) => node.scrollBy({ top: node.scrollHeight }))
    await page.waitForTimeout(150)
  }
  const last = await rows(page).last().getAttribute('aria-rowindex')
  expect(Number(last)).toBeGreaterThan(200)
  expect(await rows(page).count()).toBeLessThan(80)
})

test('shows an error with a retry when the ideas fail to load', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('soundings-mock-fail', '/ideas'))
  await openList(page)
  await expect(page.getByRole('alert')).toContainText('We couldn’t load the ideas')
  // Filters stay usable.
  await expect(page.getByRole('searchbox', { name: 'Search ideas' })).toBeEnabled()
  await page.evaluate(() => localStorage.removeItem('soundings-mock-fail'))
  await page.getByRole('button', { name: 'Try again' }).click()
  await expect(rows(page).first()).toBeVisible()
})

test('an unknown or private project is a plain not found', async ({ page }) => {
  await page.goto('/p/does-not-exist')
  await expect(
    page.getByRole('heading', { name: 'This project doesn’t exist or you don’t have access' }),
  ).toBeVisible()
})

for (const colorScheme of ['light', 'dark'] as const) {
  test(`list has no serious accessibility violations (${colorScheme})`, async ({ page }) => {
    await page.emulateMedia({ colorScheme })
    await openList(page)
    await expect(rows(page).first()).toBeVisible()
    expect(await seriousViolations(page)).toEqual([])
  })
}

test.describe('on a phone (390px)', () => {
  test.use({ viewport: { width: 390, height: 844 } })

  test('defaults to the List, rows stack as cards, nothing scrolls sideways', async ({ page }) => {
    await page.goto('/p/customer-innovation')
    await expect(page.getByRole('radio', { name: 'List' })).toBeChecked()
    await expect(rows(page).first()).toBeVisible()
    const box = await rows(page).first().boundingBox()
    expect(box?.width).toBeGreaterThan(330)
    const overflow = await page.evaluate(() => {
      const main = document.querySelector('main')
      return {
        page: document.documentElement.scrollWidth - document.documentElement.clientWidth,
        main: main ? main.scrollWidth - main.clientWidth : 0,
      }
    })
    expect(overflow).toEqual({ page: 0, main: 0 })
    await expect(page.getByRole('button', { name: 'New idea' })).toBeVisible()
    expect(await seriousViolations(page)).toEqual([])
  })
})
