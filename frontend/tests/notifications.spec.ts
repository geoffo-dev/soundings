import type { Page } from '@playwright/test'

import { expect, test } from './support'

/**
 * The notification bell and inbox (contract-phase3 §3.2) against the mock:
 * Alice Anders has five unread notifications (a mention, two comments, all
 * evaluations in, an evaluation reminder) and older read ones of every type.
 */

const bell = (page: Page) => page.getByRole('button', { name: /^Notifications/ })
const panel = (page: Page) => page.getByRole('dialog', { name: 'Notifications' })

test('the bell shows the unread count; the popover lists notifications by day', async ({
  page,
}) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { level: 1, name: 'My work' })).toBeVisible()
  await expect(bell(page)).toHaveAccessibleName('Notifications, 5 unread')
  await bell(page).click()
  const inbox = panel(page)
  await expect(inbox.getByRole('heading', { name: 'Today' })).toBeVisible()
  await expect(inbox.getByRole('heading', { name: 'Yesterday' })).toBeVisible()
  const mention = inbox.getByRole('link', { name: /^Unread: Carol Díaz mentioned you/ })
  await expect(mention).toContainText('CUST-1')
  await expect(mention).toContainText('Self-serve returns portal')
  await expect(mention).toContainText('“@Alice Anders could you check')
  // Unread only.
  await inbox.getByRole('radio', { name: 'Unread (5)' }).click()
  await expect(inbox.getByRole('link', { name: /^Unread:/ })).toHaveCount(5)
  await expect(inbox.getByRole('link', { name: /made you the owner/ })).toHaveCount(0)
  // Esc closes it and focus goes back to the bell.
  await page.keyboard.press('Escape')
  await expect(inbox).toBeHidden()
  await expect(bell(page)).toBeFocused()
})

test('opening a reminder marks it read and opens the evaluate sheet', async ({ page }) => {
  await page.goto('/')
  await bell(page).click()
  await panel(page)
    .getByRole('link', { name: /Your evaluation is due/ })
    .click()
  await expect(page).toHaveURL(/\/ideas\/CUST-1\?evaluate=1$/)
  await expect(page.getByRole('dialog', { name: 'Evaluate' })).toBeVisible()
  await page.keyboard.press('Escape')
  // Visiting CUST-1 reads its other two notifications too (§3.2).
  await expect(bell(page)).toHaveAccessibleName('Notifications, 2 unread')
})

test('opening a mention jumps to the comment and highlights it', async ({ page }) => {
  await page.goto('/')
  await bell(page).click()
  await panel(page)
    .getByRole('link', { name: /Carol Díaz mentioned you/ })
    .click()
  await expect(page).toHaveURL(/\/ideas\/CUST-1#comment-/)
  const comment = page.locator('article[data-comment-id]').filter({ hasText: 'carrier API copes' })
  await expect(comment).toBeFocused()
  await expect(comment).toBeInViewport()
  // The mention is a name chip, not a link.
  await expect(comment.locator('[data-mention]')).toHaveText('@Alice Anders')
  await expect(comment.locator('a[href^="user:"]')).toHaveCount(0)
})

test('mark all read clears the badge, keeps focus, and can be undone', async ({ page }) => {
  await page.goto('/')
  await bell(page).click()
  const markAll = panel(page).getByRole('button', { name: 'Mark all read' })
  await markAll.click()
  await expect(bell(page)).toHaveAccessibleName('Notifications')
  await expect(panel(page).getByRole('link', { name: /^Unread:/ })).toHaveCount(0)
  // Focus stays on the (now unavailable) button rather than falling to the page.
  await expect(markAll).toHaveAttribute('aria-disabled', 'true')
  await expect(markAll).toBeFocused()
  await expect(page.getByText('5 notifications marked read')).toBeVisible()
  await page.getByRole('button', { name: 'Undo' }).click()
  await expect(bell(page)).toHaveAccessibleName('Notifications, 5 unread')
})

test('"g i" opens the inbox page; j/k move between notifications; All / Unread', async ({
  page,
}) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { level: 1, name: 'My work' })).toBeVisible()
  await page.keyboard.press('g')
  await page.keyboard.press('i')
  await expect(page).toHaveURL(/\/notifications$/)
  await expect(page.getByRole('heading', { level: 1, name: 'Notifications' })).toBeVisible()
  await expect(page.getByRole('heading', { level: 2, name: 'Today' })).toBeVisible()
  await page.keyboard.press('j')
  await expect(page.getByRole('link', { name: /Carol Díaz mentioned you/ })).toBeFocused()
  await page.keyboard.press('j')
  await expect(page.getByRole('link', { name: /Bob Chen commented/ })).toBeFocused()

  await page.getByRole('radio', { name: 'Unread (5)' }).click()
  await expect(page).toHaveURL(/\/notifications\?unread=1$/)
  await page.getByRole('button', { name: 'Mark all read' }).click()
  await expect(page.getByRole('heading', { name: 'You’re all caught up' })).toBeVisible()
  await page.getByRole('button', { name: 'Show all' }).click()
  await expect(page).toHaveURL(/\/notifications$/)
})

test('the "?" sheet lists the inbox shortcut', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { level: 1, name: 'My work' })).toBeVisible()
  await page.keyboard.press('?')
  await expect(
    page
      .getByRole('dialog', { name: 'Keyboard shortcuts' })
      .getByText('Go to notifications (inbox)'),
  ).toBeVisible()
})

test('loading and error states', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('soundings-mock-fail', '/me/notifications'))
  await page.goto('/notifications')
  await expect(page.getByRole('alert')).toContainText('Couldn’t load your notifications')
  await page.evaluate(() => localStorage.removeItem('soundings-mock-fail'))
  await page.getByRole('button', { name: 'Try again' }).click()
  await expect(page.getByRole('heading', { level: 2, name: 'Today' })).toBeVisible()
})

test.describe('on a phone (390px)', () => {
  test.use({ viewport: { width: 390, height: 844 } })

  test('the bell opens a full-height sheet', async ({ page }) => {
    await page.goto('/')
    await bell(page).click()
    const sheet = page.getByRole('dialog', { name: 'Notifications' })
    await expect(sheet).toBeVisible()
    const box = await sheet.boundingBox()
    expect(box?.height).toBeGreaterThan(780)
    await sheet.getByRole('link', { name: 'See all notifications' }).click()
    await expect(page).toHaveURL(/\/notifications$/)
    await expect(sheet).toBeHidden()
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - window.innerWidth,
    )
    expect(overflow).toBeLessThanOrEqual(0)
  })
})

test.describe('signed out', () => {
  test.use({ signedInAs: null })

  test('an evaluate link from an email survives sign-in', async ({ page }) => {
    await page.goto('/ideas/cust-1?evaluate=1')
    await expect(page).toHaveURL(/\/login\?next=/)
    expect(decodeURIComponent(new URL(page.url()).searchParams.get('next') ?? '')).toContain(
      'evaluate=1',
    )
    await page.getByRole('button', { name: /Alice Anders/ }).click()
    await expect(page).toHaveURL(/\/ideas\/CUST-1\?evaluate=1$/)
    await expect(page.getByRole('dialog', { name: 'Evaluate' })).toBeVisible()
  })
})
