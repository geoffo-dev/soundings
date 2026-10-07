import type { Locator, Page } from '@playwright/test'

import { uniqueKey, uniqueSuffix } from './support/api'
import {
  bestPracticeViolations,
  expect,
  heading,
  settled,
  signIn,
  test,
  toast,
} from './support/fixtures'

/**
 * Regression specs for the Phase 7 accessibility audit (WCAG 2.2 AA) against the
 * real app and the demo data, as Alice (platform admin, admin of Customer
 * Innovation): Shift+Tab under the list's sticky header (2.4.11), the rubric at
 * 390 px under the sticky save bar (2.4.11), the list's sort buttons at 390 px
 * (2.4.7), the tab panel's focus ring (2.4.7), an Undo toast that waits while
 * focus is on it (2.2.1), a name that starts with the visible label (2.5.3), and axe's
 * best-practice rules on the main screens. Test plan: A11Y7-*.
 */

const SLUG = 'customer-innovation'

const rect = (locator: Locator) =>
  locator.evaluate((node) => {
    const box = node.getBoundingClientRect()
    return { top: box.top, bottom: box.bottom }
  })
const focused = (page: Page) => page.locator(':focus')

test.beforeEach(async ({ page }) => {
  await signIn(page, 'alice')
})

test.describe('focus is never hidden under a sticky bar', () => {
  test.use({ viewport: { width: 1280, height: 560 } })

  test('A11Y7-01 Shift+Tab up the list keeps each row below the sticky header', async ({
    page,
  }) => {
    await page.goto(`/p/${SLUG}?view=list`)
    await expect(heading(page, 'Customer Innovation')).toBeVisible()
    const table = page.getByRole('table', { name: 'Ideas' })
    await expect(table.locator('tbody a').first()).toBeVisible()
    await page
      .locator('[data-slot="table-container"]')
      .evaluate((node) => node.scrollTo({ top: node.scrollHeight }))
    await table.locator('tbody a').last().focus()
    for (let i = 0; i < 12; i += 1) {
      await page.keyboard.press('Shift+Tab')
      const row = await rect(focused(page))
      const header = await rect(table.locator('thead'))
      expect(row.top, `row ${i}`).toBeGreaterThanOrEqual(header.bottom - 1)
    }
  })
})

test.describe('on a phone (390px)', () => {
  test.use({ viewport: { width: 390, height: 844 } })

  test('A11Y7-02 rubric fields stay clear of the sticky save bar', async ({ page }) => {
    await page.goto(`/p/${SLUG}/settings?tab=rubric`)
    const first = page.getByRole('textbox', { name: 'Name' }).first()
    await expect(first).toBeVisible()
    await first.focus()
    // The rubric's own Save bar (the other tabs' forms stay mounted, hidden).
    const bar = page.locator('[data-sticky-actions]').filter({ visible: true }).first()
    for (let i = 0; i < 14; i += 1) {
      await page.keyboard.press('Tab')
      const target = focused(page)
      if (await target.evaluate((node) => node.closest('[data-sticky-actions]') !== null)) break
      expect((await rect(target)).bottom, `stop ${i}`).toBeLessThanOrEqual(
        (await rect(bar)).top + 1,
      )
    }
  })

  test('A11Y7-03 the list’s card layout leaves its sort buttons out of the Tab order', async ({
    page,
  }) => {
    await page.goto(`/p/${SLUG}?view=list`)
    await expect(page.getByRole('table', { name: 'Ideas' })).toBeVisible()
    const buttons = page.locator('thead button')
    await expect(buttons.first()).toBeAttached()
    for (const button of await buttons.all()) await expect(button).toBeHidden()
    await expect(page.getByRole('columnheader', { name: 'Score' })).toBeAttached()
  })
})

test('A11Y7-04 the idea’s tab panel shows the focus ring', async ({ page }) => {
  await page.goto('/ideas/CUST-2')
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
  await page.getByRole('tab', { name: 'Overview' }).focus()
  await page.keyboard.press('Tab')
  const panel = page.getByRole('tabpanel', { name: 'Overview' })
  await expect(panel).toBeFocused()
  const outline = await panel.evaluate((node) => {
    const style = getComputedStyle(node)
    return `${style.outlineStyle} ${style.outlineWidth}`
  })
  expect(outline).toBe('solid 2px')
})

test('A11Y7-05 an Undo toast waits while focus is on it, then goes', async ({ page, api }) => {
  test.setTimeout(90_000)
  const alice = await api('alice')
  const project = await alice.createProject({
    name: `A11y toast ${uniqueSuffix()}`,
    slug: `a11y-toast-${uniqueSuffix()}`,
    key: uniqueKey('T'),
  })
  const idea = await alice.createIdea(project.slug, {
    title: 'An idea to park and keep',
    summary: 'For the Undo toast.',
  })
  await page.goto(`/ideas/${idea.key}`)
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
  await settled(page)
  await page.keyboard.press('s')
  await page
    .getByRole('dialog', { name: 'Change status' })
    .getByRole('option', { name: 'Evaluating' })
    .click()
  const undo = toast(page, /Evaluating/).getByRole('button', { name: 'Undo' })
  await expect(undo).toBeVisible()
  await undo.focus()
  await page.waitForTimeout(12_000)
  await expect(undo).toBeVisible()
  // Focus leaves (the pointer was never on it): the timer runs again and the toast goes.
  await page.mouse.move(5, 300)
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur())
  await expect(undo).toBeHidden({ timeout: 15_000 })
})

test('A11Y7-06 a draft’s “Continue” is named starting with the word it shows', async ({
  page,
  api,
}) => {
  // A fresh idea in a project of her own, so the draft is surely hers.
  const alice = await api('alice')
  const project = await alice.createProject({
    name: `A11y draft ${uniqueSuffix()}`,
    slug: `a11y-draft-${uniqueSuffix()}`,
    key: uniqueKey('D'),
  })
  const idea = await alice.createIdea(project.slug, {
    title: 'An idea with a saved draft',
    summary: 'For the Continue button.',
  })
  await alice.setOwner(idea.key, 'alice')
  await alice.invite(idea.key, ['alice'])
  await alice.evaluate(idea.key, {}, { submit: false })
  await page.goto('/')
  const link = page.getByRole('link', { name: `Continue evaluating ${idea.key}: ${idea.title}` })
  await expect(link).toBeVisible()
  await expect(link).toHaveText('Continue')
})

test.describe('A11Y7-07 axe best-practice rules pass on the main screens', () => {
  for (const path of [
    '/',
    `/p/${SLUG}`,
    `/p/${SLUG}?view=list`,
    '/ideas/CUST-2',
    '/notifications',
    '/settings',
    '/settings/api-keys',
    '/settings/users',
    '/admin',
    `/p/${SLUG}/settings`,
  ]) {
    test(path, async ({ page }) => {
      await page.goto(path)
      await expect(page.locator('h1').first()).toBeVisible()
      await settled(page)
      expect(await bestPracticeViolations(page)).toEqual([])
    })
  }
})
