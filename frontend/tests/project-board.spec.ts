import type { Locator, Page } from '@playwright/test'

import { expect, seriousViolations, test, USERS } from './support'

/**
 * The project Board (wireframe 02): columns by status, drag and drop with the
 * mouse and the keyboard, the Closed resolution picker, Undo, load more.
 * Alice owns CUST-5 (New), CUST-2 (Evaluating), CUST-4 and CUST-3, so she can
 * move those; everything else has no drag.
 */

const column = (page: Page, label: string) =>
  page.getByRole('region', { name: new RegExp(`^${label}\\b`) })
const card = (scope: Page | Locator, key: string) =>
  // Cards are named "Title (KEY)".
  scope.getByRole('link', { name: new RegExp(`\\(${key}\\)$`) })
const announcer = (page: Page) => page.locator('[id^="DndLiveRegion"]')
const toast = (page: Page, text: string) => page.locator('[data-sonner-toast]', { hasText: text })

async function openBoard(page: Page, path = '/p/customer-innovation?view=board') {
  await page.goto(path)
  await expect(page.getByRole('heading', { level: 1, name: 'Customer Innovation' })).toBeVisible()
  await expect(card(column(page, 'New'), 'CUST-5')).toBeVisible()
}

async function drag(page: Page, from: Locator, to: Locator) {
  await from.scrollIntoViewIfNeeded()
  const a = await from.boundingBox()
  const b = await to.boundingBox()
  if (!a || !b) throw new Error('not visible')
  await page.mouse.move(a.x + a.width / 2, a.y + a.height / 2)
  await page.mouse.down()
  await page.mouse.move(a.x + a.width / 2 + 12, a.y + a.height / 2, { steps: 4 })
  await page.mouse.move(b.x + b.width / 2, b.y + 120, { steps: 12 })
  await page.mouse.up()
}

test('shows five columns with the project labels, counts and card details', async ({ page }) => {
  await openBoard(page)
  for (const [label, count] of [
    ['New', 5],
    ['Evaluating', 6],
    ['Shortlisted', 3],
    ['Proposal', 1],
    ['Closed', 5],
  ] as const) {
    await expect(column(page, label).getByRole('heading', { level: 2 })).toHaveText(
      `${label}${count}`,
    )
  }
  // Blind evaluation: Alice owes CUST-1 an evaluation, so its score is a lock.
  await expect(
    card(page, 'CUST-1').getByRole('img', {
      name: 'Scores hidden until you submit your evaluation',
    }),
  ).toBeVisible()
  await expect(card(page, 'CUST-17').getByRole('img', { name: /^Score 4\.3/ })).toBeVisible()
  await expect(card(page, 'CUST-2').getByRole('img', { name: 'High disagreement' })).toBeVisible()
  await expect(
    card(page, 'CUST-17').getByRole('img', { name: '3 of 3 evaluations submitted' }),
  ).toBeVisible()
  // Closed starts collapsed to its resolution counts.
  await expect(column(page, 'Closed').getByRole('button', { name: /Accepted/ })).toContainText('2')
  await expect(page.getByRole('radio', { name: 'Board' })).toBeChecked()
})

test('drags a card to another column with the mouse, then undoes it', async ({ page }) => {
  await openBoard(page)
  await drag(page, card(page, 'CUST-5'), column(page, 'Evaluating'))

  await expect(card(column(page, 'Evaluating'), 'CUST-5')).toBeVisible()
  await expect(card(column(page, 'New'), 'CUST-5')).toHaveCount(0)
  await expect(column(page, 'Evaluating').getByRole('heading', { level: 2 })).toHaveText(
    'Evaluating7',
  )
  // The drop didn't open the idea.
  await expect(page).toHaveURL(/\/p\/customer-innovation/)
  await expect(toast(page, 'CUST-5 moved to Evaluating')).toBeVisible()

  await toast(page, 'CUST-5 moved to Evaluating').getByRole('button', { name: 'Undo' }).click()
  await expect(card(column(page, 'New'), 'CUST-5')).toBeVisible()
  await expect(column(page, 'Evaluating').getByRole('heading', { level: 2 })).toHaveText(
    'Evaluating6',
  )
})

test('moves a card with the keyboard, announced to screen readers', async ({ page }) => {
  await openBoard(page)
  const item = card(page, 'CUST-5')
  await item.focus()
  await expect(item).toHaveAttribute('aria-describedby', /DndDescribedBy/)

  await page.keyboard.press('Space')
  await expect(announcer(page)).toContainText('Picked up CUST-5')
  await page.keyboard.press('ArrowRight')
  await expect(announcer(page)).toContainText('CUST-5 is over Evaluating')
  await page.keyboard.press('ArrowRight')
  await expect(announcer(page)).toContainText('CUST-5 is over Shortlisted')
  await page.keyboard.press('Space')
  await expect(announcer(page)).toContainText('CUST-5 moved to Shortlisted')

  await expect(card(column(page, 'Shortlisted'), 'CUST-5')).toBeFocused()
  await expect(toast(page, 'CUST-5 moved to Shortlisted')).toBeVisible()

  // Escape cancels a move.
  await page.keyboard.press('Space')
  await page.keyboard.press('ArrowLeft')
  await page.keyboard.press('Escape')
  await expect(announcer(page)).toContainText('Move cancelled. CUST-5 stays in Shortlisted')
  await expect(card(column(page, 'Shortlisted'), 'CUST-5')).toBeVisible()
})

test('dropping on Closed asks how it was closed', async ({ page }) => {
  await openBoard(page)
  await card(page, 'CUST-5').focus()
  await page.keyboard.press('Space')
  for (let i = 0; i < 4; i += 1) await page.keyboard.press('ArrowRight')
  await expect(announcer(page)).toContainText('CUST-5 is over Closed')
  await page.keyboard.press('Space')

  const picker = page.getByRole('dialog', { name: 'Close CUST-5 as' })
  await expect(picker).toBeVisible()
  await expect(picker.getByRole('button', { name: /Accepted/ })).toBeFocused()
  // Escape keeps the card where it was.
  await page.keyboard.press('Escape')
  await expect(picker).toBeHidden()
  await expect(card(column(page, 'New'), 'CUST-5')).toBeFocused()

  await drag(page, card(page, 'CUST-5'), column(page, 'Closed'))
  await expect(picker).toBeVisible()
  await page.keyboard.press('2')
  await expect(toast(page, 'CUST-5 moved to Rejected')).toBeVisible()
  // Closed is collapsed, so focus goes to its toggle.
  await expect(
    column(page, 'Closed').getByRole('button', { name: 'Show Closed ideas' }),
  ).toBeFocused()
  await expect(column(page, 'Closed').getByRole('heading', { level: 2 })).toHaveText('Closed6')
  await expect(column(page, 'Closed').getByRole('button', { name: /Rejected/ })).toContainText('2')
  await expect(card(page, 'CUST-5')).toHaveCount(0)

  // Expanding Closed filtered to Rejected shows it.
  await column(page, 'Closed')
    .getByRole('button', { name: /Rejected/ })
    .click()
  await expect(card(column(page, 'Closed'), 'CUST-5')).toBeVisible()
  await expect(
    column(page, 'Closed').getByRole('button', { name: /Rejected/, pressed: true }),
  ).toBeVisible()
})

test('cards you may not move have no drag', async ({ page }) => {
  await openBoard(page)
  const item = card(page, 'CUST-1') // owned by Bob
  // Described by what the card shows only, not by the drag instructions.
  await expect(item).toHaveAttribute('aria-describedby', /^card-[^ ]+-description$/)
  await item.focus()
  await page.keyboard.press('Space')
  await expect(announcer(page)).not.toContainText('Picked up')
  await drag(page, item, column(page, 'Shortlisted'))
  await expect(card(column(page, 'Evaluating'), 'CUST-1')).toBeVisible()
})

test.describe('as a platform admin', () => {
  test.use({ signedInAs: USERS.priya })

  test('a failed move snaps back with an error', async ({ page }) => {
    await openBoard(page)
    await page.evaluate(() => localStorage.setItem('soundings-mock-fail', '/status'))
    await drag(page, card(page, 'CUST-1'), column(page, 'Proposal'))
    await expect(toast(page, 'Couldn’t change the status')).toBeVisible()
    await expect(card(column(page, 'Evaluating'), 'CUST-1')).toBeVisible()
    await expect(card(column(page, 'Proposal'), 'CUST-1')).toHaveCount(0)
  })

  test('a card loaded with "Show more" moves at once', async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem('soundings-mock-dataset', 'large'))
    await page.goto('/p/customer-innovation?view=board')
    const from = column(page, 'New')
    const to = column(page, 'Shortlisted')
    await expect(from.getByRole('link')).toHaveCount(50)
    await from.getByRole('button', { name: 'Show 50 more' }).click()
    await expect(from.getByRole('link')).toHaveCount(100)
    const count = async (region: Locator) =>
      Number((await region.getByRole('heading', { level: 2 }).innerText()).replace(/\D/g, ''))
    const [before, target] = [await count(from), await count(to)]

    const item = from.getByRole('link').nth(80)
    const key = (await item.innerText()).split('\n')[0] ?? ''
    // A slow server: the card must land before it answers (optimistic, not a refetch).
    await page.evaluate(() => localStorage.setItem('soundings-mock-latency', '3000'))
    await item.focus()
    await page.keyboard.press('Space')
    await page.keyboard.press('ArrowRight')
    await page.keyboard.press('ArrowRight')
    await page.keyboard.press('Space')

    await expect(card(to, key)).toBeVisible({ timeout: 1000 })
    await expect(card(from, key)).toHaveCount(0, { timeout: 1000 })
    expect(await count(from)).toBe(before - 1)
    expect(await count(to)).toBe(target + 1)
  })
})

test('loads more of a column on request (10,000 ideas)', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('soundings-mock-dataset', 'large'))
  await page.goto('/p/customer-innovation?view=board')
  const newColumn = column(page, 'New')
  await expect(newColumn.getByRole('link')).toHaveCount(50)
  await newColumn.getByRole('button', { name: 'Show 50 more' }).click()
  await expect(newColumn.getByRole('link')).toHaveCount(100)
})

test('filters apply to the board and live in the URL', async ({ page }) => {
  await openBoard(page)
  await page.getByRole('button', { name: 'Needs evaluators' }).click()
  await expect(page).toHaveURL(/needs_evaluators=1/)
  await expect(card(page, 'CUST-1')).toHaveCount(0)
  await expect(card(column(page, 'New'), 'CUST-5')).toBeVisible()
  // There is no status filter on the board: its columns are the statuses.
  await expect(page.getByRole('button', { name: /^Status/ })).toHaveCount(0)
  await page.getByRole('button', { name: 'Clear' }).click()
  await expect(page).not.toHaveURL(/needs_evaluators/)
  await expect(card(page, 'CUST-1')).toBeVisible()
})

for (const colorScheme of ['light', 'dark'] as const) {
  test(`board has no serious accessibility violations (${colorScheme})`, async ({ page }) => {
    await page.emulateMedia({ colorScheme })
    await openBoard(page)
    expect(await seriousViolations(page)).toEqual([])
  })
}

test.describe('on a phone (390px)', () => {
  test.use({ viewport: { width: 390, height: 844 } })

  test('the board scrolls sideways a column at a time, the page does not', async ({ page }) => {
    await openBoard(page)
    const overflow = await page.evaluate(() => {
      const main = document.querySelector('main')
      return {
        page: document.documentElement.scrollWidth - document.documentElement.clientWidth,
        main: main ? main.scrollWidth - main.clientWidth : 0,
      }
    })
    expect(overflow).toEqual({ page: 0, main: 0 })
    const width = await column(page, 'New').evaluate((node) => node.getBoundingClientRect().width)
    expect(width).toBeGreaterThan(300)
    await expect(page.getByRole('button', { name: 'New idea' })).toBeVisible()
    expect(await seriousViolations(page)).toEqual([])
  })
})
