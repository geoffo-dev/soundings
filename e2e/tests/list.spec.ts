import type { Page } from '@playwright/test'

import type { Api } from './support/api'
import { expect, heading, signIn, test } from './support/fixtures'

/**
 * The project list against the real API and the seeded Customer Innovation project:
 * filter chips (needs evaluators, high disagreement, owner me), filters in the URL, and
 * sorting by score. Every result is cross-checked with the API for the same viewer.
 * Test plan: LF-*.
 */

const SLUG = 'customer-innovation'
const table = (page: Page) => page.getByRole('table', { name: 'Ideas' })
const rows = (page: Page) =>
  table(page)
    .getByRole('row')
    .filter({ has: page.getByRole('link') })
const countText = (page: Page) => page.getByText(/^\d[\d,]* (of [\d,]+ )?ideas?$/)

async function openList(page: Page, query = '') {
  await page.goto(`/p/${SLUG}?view=list${query}`)
  await expect(heading(page, 'Customer Innovation')).toBeVisible()
}

/** Idea keys of the rendered rows, in order. */
async function rowKeys(page: Page): Promise<string[]> {
  await expect(rows(page).first()).toBeVisible()
  return rows(page).evaluateAll((nodes) =>
    nodes.map((node) => /[A-Z][A-Z0-9]+-\d+/.exec(node.textContent ?? '')?.[0] ?? ''),
  )
}

/** Keys the API returns to `client` for the same filters (all pages). */
async function apiKeys(client: Api, query: string): Promise<string[]> {
  const page = await client.listIdeas(SLUG, `${query}&limit=200`)
  expect(page.next_cursor).toBeNull()
  return page.items.map((idea) => idea.key)
}

const sorted = (keys: string[]) => [...keys].sort()

test.describe('as Alice (admin of Customer Innovation)', () => {
  test.beforeEach(async ({ page }) => {
    await signIn(page, 'alice')
  })

  test('LF-01: "Needs evaluators" shows open ideas nobody was invited to', async ({
    page,
    api,
  }) => {
    await openList(page)
    await expect(countText(page)).toHaveText('21 ideas')
    await page.getByRole('button', { name: 'Needs evaluators' }).click()
    await expect(page).toHaveURL(/needs_evaluators=1/)
    await expect(page.getByRole('button', { name: 'Needs evaluators' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
    await expect(countText(page)).toHaveText('6 of 21 ideas')
    const keys = await rowKeys(page)
    // CUST-21 came in through the public form (Phase 4 seed) and was approved: new, nobody invited.
    expect(sorted(keys)).toEqual(['CUST-16', 'CUST-17', 'CUST-18', 'CUST-19', 'CUST-20', 'CUST-21'])
    expect(sorted(keys)).toEqual(sorted(await apiKeys(await api('alice'), 'needs_evaluators=true')))
    for (const row of await rows(page).all()) await expect(row).toContainText('New')
  })

  test('LF-02: "High disagreement" never includes an idea whose scores are hidden from you', async ({
    page,
    api,
  }) => {
    await openList(page)
    await page.getByRole('button', { name: 'High disagreement' }).click()
    await expect(page).toHaveURL(/high_disagreement=1/)
    // CUST-8 is flagged; CUST-11 is flagged too, but Alice still owes it an evaluation.
    await expect(rows(page)).toHaveCount(1)
    expect(await rowKeys(page)).toEqual(['CUST-8'])
    expect(await apiKeys(await api('alice'), 'high_disagreement=true')).toEqual(['CUST-8'])
    await expect(rows(page).first().getByRole('img', { name: 'High disagreement' })).toBeVisible()
  })

  test('LF-03/05: "Owner: me", combined with another chip, lives in the URL', async ({
    page,
    api,
  }) => {
    await openList(page)
    await page.getByRole('button', { name: /^Owner/ }).click()
    await page.getByRole('option', { name: 'Me' }).click()
    await page.keyboard.press('Escape')
    await expect(page).toHaveURL(/owner=me/)
    await expect(countText(page)).toHaveText('5 of 21 ideas')
    const mine = await rowKeys(page)
    expect(sorted(mine)).toEqual(['CUST-12', 'CUST-17', 'CUST-2', 'CUST-6', 'CUST-8'])
    expect(sorted(mine)).toEqual(sorted(await apiKeys(await api('alice'), 'owner=me')))
    for (const row of await rows(page).all()) {
      await expect(row.getByRole('img', { name: 'Alice Anders' })).toBeVisible()
    }

    // Filters combine with AND.
    await page.getByRole('button', { name: 'Needs evaluators' }).click()
    await expect(countText(page)).toHaveText('1 of 21 ideas')
    expect(await rowKeys(page)).toEqual(['CUST-17'])

    // The filtered view is a link: it opens the same way for someone else…
    const shared = page.url()
    await page.goto(shared)
    await expect(page.getByRole('button', { name: /^Owner Me/ })).toBeVisible()
    await expect(countText(page)).toHaveText('1 of 21 ideas')
    // …and Clear removes every filter.
    await page.getByRole('button', { name: 'Clear', exact: true }).click()
    await expect(page).not.toHaveURL(/owner=|needs_evaluators/)
    await expect(countText(page)).toHaveText('21 ideas')
  })

  test('LF-04: sorting by score ranks ideas as the API does; hidden and unscored last', async ({
    page,
    api,
  }) => {
    await openList(page)
    await page.getByRole('button', { name: 'Score', exact: true }).click()
    await expect(page).toHaveURL(/sort=-score/)
    await expect(page.getByRole('columnheader', { name: 'Score' })).toHaveAttribute(
      'aria-sort',
      'descending',
    )
    const alice = await api('alice')
    await expect.poll(() => rowKeys(page)).toEqual(await apiKeys(alice, 'sort=-score'))

    const scores = await rows(page).evaluateAll((nodes) =>
      nodes.map((node) => {
        const label = node.querySelector('[aria-label^="Score "]')?.getAttribute('aria-label')
        return label ? Number(/Score ([\d.]+)/.exec(label)?.[1]) : null
      }),
    )
    const numbers = scores.filter((score): score is number => score !== null)
    expect(numbers.length).toBeGreaterThan(8)
    expect(numbers).toEqual([...numbers].sort((a, b) => b - a))
    expect(scores.slice(0, numbers.length).every((score) => score !== null)).toBe(true)
    expect(numbers[0]).toBe(4.1) // CUST-12

    await page.getByRole('button', { name: 'Score', exact: true }).click()
    await expect(page).toHaveURL(/sort=score/)
    await expect.poll(() => rowKeys(page)).toEqual(await apiKeys(alice, 'sort=score'))
    const ascending = await rows(page).evaluateAll((nodes) =>
      nodes.map((node) => node.querySelector('[aria-label^="Score "]') !== null),
    )
    // Ideas without a visible score come last in both directions.
    const firstUnscored = ascending.indexOf(false)
    expect(ascending.slice(firstUnscored).every((scored) => !scored)).toBe(true)
  })
})

test('LF-02: the owner of the hidden idea sees both flagged ideas', async ({ page, api }) => {
  await signIn(page, 'bob')
  await openList(page, '&high_disagreement=1')
  await expect(rows(page)).toHaveCount(2)
  expect(sorted(await rowKeys(page))).toEqual(['CUST-11', 'CUST-8'])
  expect(sorted(await apiKeys(await api('bob'), 'high_disagreement=true'))).toEqual([
    'CUST-11',
    'CUST-8',
  ])
})
