import type { Locator, Page } from '@playwright/test'

import { bestPracticeViolations, expect, test } from './support'

/**
 * Phase 7 accessibility fixes (WCAG 2.2 AA audit) against the mock: focus never
 * hides under sticky bars, the card layout's sort buttons take no focus, tab panels
 * show the ring, highlighted items and selected states are marked by more than a
 * grey fill, Undo toasts wait while focus is on them, single-key shortcuts can be
 * turned off, names start with the words on screen, and a board column comes into
 * view when focus moves into it on a phone. The real-stack versions are in
 * e2e/tests/a11y-phase7.spec.ts.
 */

const rect = (locator: Locator) =>
  locator.evaluate((node) => {
    const box = node.getBoundingClientRect()
    return { top: box.top, bottom: box.bottom, left: box.left, right: box.right }
  })
const focused = (page: Page) => page.locator(':focus')

async function outlineOf(locator: Locator) {
  return locator.evaluate((node) => {
    const style = getComputedStyle(node)
    return { style: style.outlineStyle, width: style.outlineWidth }
  })
}

test.describe('focus is never hidden under a sticky bar (2.4.11)', () => {
  test.use({ viewport: { width: 1280, height: 560 } })

  test('Shift+Tab up the list keeps each row clear of the sticky header', async ({ page }) => {
    await page.goto('/p/customer-innovation?view=list')
    const table = page.getByRole('table', { name: 'Ideas' })
    await expect(table).toBeVisible()
    const scroller = page.locator('[data-slot="table-container"]')
    await scroller.evaluate((node) => node.scrollTo({ top: node.scrollHeight }))
    const links = table.locator('tbody a')
    await links.last().focus()
    const header = table.locator('thead')
    for (let i = 0; i < 12; i += 1) {
      await page.keyboard.press('Shift+Tab')
      const row = await rect(focused(page))
      const head = await rect(header)
      expect(row.top, `row ${i}`).toBeGreaterThanOrEqual(head.bottom - 1)
    }
    // A row's score badge never paints over the header.
    const z = await header.evaluate((node) => Number(getComputedStyle(node).zIndex))
    expect(z).toBeGreaterThan(10)
  })
})

test.describe('on a phone (390px)', () => {
  test.use({ viewport: { width: 390, height: 844 } })

  test('rubric fields stay clear of the sticky save bar', async ({ page }) => {
    await page.goto('/p/internal-tools/settings?tab=rubric')
    const first = page.getByRole('textbox', { name: 'Name' }).first()
    await expect(first).toBeVisible()
    await first.focus()
    // The rubric's own bar (the other tabs' forms stay mounted, hidden).
    const bar = page.locator('[data-sticky-actions]:visible')
    for (let i = 0; i < 14; i += 1) {
      await page.keyboard.press('Tab')
      const target = focused(page)
      const inBar = await target.evaluate((node) => node.closest('[data-sticky-actions]') !== null)
      if (inBar) break
      const box = await rect(target)
      const top = (await rect(bar)).top
      expect(box.bottom, `stop ${i}`).toBeLessThanOrEqual(top + 1)
    }
  })

  test('the list’s card layout leaves its sort buttons out of the Tab order', async ({ page }) => {
    await page.goto('/p/customer-innovation?view=list')
    await expect(page.getByRole('table', { name: 'Ideas' })).toBeVisible()
    const buttons = page.locator('thead button')
    await expect(buttons.first()).toBeAttached()
    for (const button of await buttons.all()) await expect(button).toBeHidden()
    // The columns keep their names for screen readers.
    await expect(page.getByRole('columnheader', { name: 'Score' })).toBeAttached()
  })

  test('Tab into another board column brings that column into view', async ({ page }) => {
    await page.goto('/p/customer-innovation?view=board')
    const columns = page.getByRole('region', { name: /^(New|Evaluating)\b/ })
    await expect(columns.first()).toBeVisible()
    const second = page.getByRole('region', { name: /^Evaluating\b/ })
    await second.getByRole('link').first().focus()
    await page.waitForTimeout(100)
    const card = await rect(focused(page))
    expect(card.left).toBeGreaterThanOrEqual(0)
    expect(card.right).toBeLessThanOrEqual(390)
  })
})

test('tab panels show the focus ring (2.4.7)', async ({ page }) => {
  await page.goto('/ideas/CUST-2')
  const tab = page.getByRole('tab', { name: 'Overview' })
  await tab.focus()
  await page.keyboard.press('Tab')
  const panel = page.getByRole('tabpanel', { name: 'Overview' })
  await expect(panel).toBeFocused()
  expect(await outlineOf(panel)).toEqual({ style: 'solid', width: '2px' })
})

test('a highlighted menu item has a ring, not only a grey fill (1.4.11)', async ({ page }) => {
  await page.goto('/p/customer-innovation?view=board')
  await page.getByRole('button', { name: /^Sort: / }).click()
  await page.keyboard.press('ArrowDown')
  const item = page.locator('[role="menuitemradio"][data-highlighted]')
  await expect(item).toHaveCount(1)
  expect(await outlineOf(item)).toEqual({ style: 'solid', width: '2px' })
})

test('the selected segment is told apart by its outline and weight (1.4.11)', async ({ page }) => {
  await page.goto('/p/customer-innovation?view=board')
  const selected = page.getByRole('radio', { name: 'Board' })
  await expect(selected).toBeChecked()
  const style = await selected.evaluate((node) => {
    const computed = getComputedStyle(node)
    return { weight: computed.fontWeight, shadow: computed.boxShadow }
  })
  expect(style.weight).toBe('600')
  expect(style.shadow).not.toBe('none')
})

test('an Undo toast waits while focus is on it (2.2.1)', async ({ page }) => {
  test.setTimeout(60_000)
  await page.goto('/ideas/CUST-2')
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
  await page.keyboard.press('s')
  await page
    .getByRole('dialog', { name: 'Change status' })
    .getByRole('option', { name: 'Shortlisted' })
    .click()
  const undo = page.locator('[data-sonner-toast]').getByRole('button', { name: 'Undo' })
  await expect(undo).toBeVisible()
  await undo.focus()
  // Well past the 10 s it would have stayed: still there.
  await page.waitForTimeout(12_000)
  await expect(undo).toBeVisible()
  // Focus leaves: the timer runs again and the toast goes.
  await page.mouse.move(5, 300)
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur())
  await expect(undo).toBeHidden({ timeout: 15_000 })
})

test('Undo toasts last 10 seconds and Alt+T is in the shortcut sheet', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('heading', { level: 1, name: 'My work' }).waitFor()
  await page.keyboard.press('?')
  const sheet = page.getByRole('dialog', { name: 'Keyboard shortcuts' })
  await expect(sheet.getByText('Go to messages such as Undo')).toBeVisible()
  // The toaster region is "Messages"; the bell is the app's notifications.
  await expect(page.locator('section[aria-label^="Messages"]')).toBeAttached()
})

test('single-key shortcuts can be turned off and on again (2.1.4)', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('heading', { level: 1, name: 'My work' }).waitFor()
  const newIdea = page.getByRole('dialog', { name: /New idea|Submit an idea/ })
  await page.keyboard.press('?')
  const sheet = page.getByRole('dialog', { name: 'Keyboard shortcuts' })
  const toggle = sheet.getByRole('switch', { name: 'Single-key shortcuts' })
  await expect(toggle).toBeChecked()
  await toggle.click()
  await expect(toggle).not.toBeChecked()
  await page.keyboard.press('Escape')
  await page.keyboard.press('n')
  await expect(newIdea).toHaveCount(0)
  // The hint goes with it; ⌘K still works.
  await expect(page.locator('main').getByText('N', { exact: true })).toHaveCount(0)
  await page.keyboard.press('ControlOrMeta+k')
  await expect(page.getByRole('dialog', { name: /command/i })).toBeVisible()
  await page.keyboard.press('Escape')

  // Remembered in this browser.
  await page.reload()
  await page.getByRole('heading', { level: 1, name: 'My work' }).waitFor()
  await page.keyboard.press('n')
  await expect(newIdea).toHaveCount(0)
  await page.getByRole('button', { name: /^Account menu/ }).click()
  await page.getByRole('menuitem', { name: 'Keyboard shortcuts' }).click()
  await sheet.getByRole('switch', { name: 'Single-key shortcuts' }).click()
  await expect(sheet.getByRole('switch', { name: 'Single-key shortcuts' })).toBeChecked()
  await page.keyboard.press('Escape')
  await expect(sheet).toBeHidden()
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur())
  await page.keyboard.press('n')
  await expect(newIdea).toBeVisible()
})

test('a draft’s “Continue” is named by the word it shows (2.5.3)', async ({ page }) => {
  await page.goto('/')
  const continueLink = page.getByRole('link', { name: /^Continue evaluating / })
  await expect(continueLink.first()).toBeVisible()
  await expect(continueLink.first()).toHaveText('Continue')
})

test('shortcut hints stay out of buttons’ names (aria-keyshortcuts instead)', async ({ page }) => {
  await page.goto('/p/customer-innovation')
  const button = page.getByRole('main').getByRole('button', { name: 'New idea', exact: true })
  await expect(button).toBeVisible()
  await expect(button).toHaveAttribute('aria-keyshortcuts', 'N')
})

test('rubric criteria move up and down from a menu, without dragging (2.5.7)', async ({ page }) => {
  await page.goto('/p/internal-tools/settings?tab=rubric')
  const criteria = page.getByRole('list', { name: 'Criteria' }).getByRole('listitem')
  const firstName = await criteria.first().getAttribute('aria-label')
  const secondName = await criteria.nth(1).getAttribute('aria-label')
  await page
    .getByRole('button', { name: `Move ${firstName ?? ''}`, exact: true })
    .locator('visible=true')
    .click()
  await expect(page.getByRole('menuitem', { name: 'Move up' })).toBeDisabled()
  await page.getByRole('menuitem', { name: 'Move down' }).click()
  await expect(criteria.first()).toHaveAttribute('aria-label', secondName ?? '')
  await expect(criteria.nth(1)).toHaveAttribute('aria-label', firstName ?? '')
  await expect(page.getByText('Unsaved changes')).toBeVisible()
})

test('after following a link, focus lands on the new page’s heading', async ({ page }) => {
  await page.goto('/p/customer-innovation?view=list')
  const link = page.getByRole('table', { name: 'Ideas' }).locator('tbody a').first()
  await link.focus()
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(/\/ideas\//)
  await expect(page.getByRole('heading', { level: 1 })).toBeFocused()
})

test.describe('axe best-practice rules pass on the main screens', () => {
  for (const path of [
    '/',
    '/p/customer-innovation',
    '/p/customer-innovation?view=list',
    '/ideas/CUST-2',
    '/ideas/CUST-3?tab=proposal',
    '/notifications',
    '/settings',
    '/settings/api-keys',
    '/settings/users',
    '/admin',
    '/p/customer-innovation/settings',
  ]) {
    test(path, async ({ page }) => {
      await page.goto(path)
      await expect(page.locator('h1').first()).toBeVisible()
      await expect(page.locator('[data-slot="skeleton"]')).toHaveCount(0)
      expect(await bestPracticeViolations(page)).toEqual([])
    })
  }
})
