import type { Page } from '@playwright/test'

import { expect, test, USERS } from './support'

/**
 * Admin settings → Audit log (contract-phase2 §3.11): plain-language rows,
 * newest first, filters in the URL, raw fields on demand. The mock has ~200
 * entries (src/mocks/access-fixtures.ts).
 */

test.use({ signedInAs: USERS.priya })

const entries = (page: Page) => page.getByRole('region', { name: 'Audit entries' })

async function openAudit(page: Page, query = '') {
  await page.goto(`/settings/audit${query}`)
  await expect(page.getByRole('heading', { level: 2, name: 'Audit log' })).toBeVisible()
  await expect(page.locator('[data-slot="skeleton"]')).toHaveCount(0)
}

test('reads each entry as a sentence, newest first, with raw fields on demand', async ({
  page,
}) => {
  await openAudit(page)
  await expect(entries(page).getByRole('heading', { level: 3 }).first()).toHaveText('Today')
  await expect(entries(page).getByText('Alice Anders signed in with SSO').first()).toBeVisible()

  await openAudit(page, '?action=groups')
  // Names from `details` are resolved: the member added, not just the group.
  await expect(
    entries(page).getByText('Priya Natarajan added Lena Novak to group Tools members'),
  ).toBeVisible({ timeout: 10_000 })

  const details = entries(page).getByRole('button', { name: 'Details' }).first()
  await details.click()
  await expect(details).toHaveAttribute('aria-expanded', 'true')
  await expect(entries(page).locator('dl').first()).toContainText('action')
  await details.click()
  await expect(details).toHaveAttribute('aria-expanded', 'false')
})

test('filters by kind of action, person, project and days', async ({ page }) => {
  await openAudit(page)

  await page.getByRole('button', { name: /^What/ }).click()
  await page.getByRole('option', { name: 'Denied sign-ins' }).click()
  await page.keyboard.press('Escape')
  await expect(page).toHaveURL(/action=denied/)
  await expect(
    entries(page).getByText(/An SSO sign-in was denied: no matching account/),
  ).toBeVisible()
  await expect(
    entries(page).getByText('SSO sign-in denied for Jonas Berg: the account is deactivated'),
  ).toBeVisible()
  await expect(entries(page).getByText(/signed in with SSO/)).toHaveCount(0)

  await page.getByRole('button', { name: 'Clear filters' }).click()
  await expect(page).toHaveURL(/\/settings\/audit$/)

  await page.getByRole('button', { name: /^Who/ }).click()
  await page.getByPlaceholder('Search people…').fill('priya')
  await page.getByRole('option', { name: /Priya Natarajan/ }).click()
  await expect(page).toHaveURL(new RegExp(`actor=${USERS.priya}`))
  await expect(page.getByRole('button', { name: /^Who\s+Priya Natarajan/ })).toBeVisible()
  await expect(entries(page).getByText(/^Alice Anders/)).toHaveCount(0)
  await expect(entries(page).getByText(/Priya Natarajan created group Contractors/)).toBeVisible()

  await page.getByRole('button', { name: /^Project/ }).click()
  await page.getByRole('option', { name: 'Customer Innovation' }).click()
  await expect(
    entries(page).getByText(
      'Priya Natarajan changed the role of Hannah Weber in Customer Innovation from viewer to member',
    ),
  ).toBeVisible()
  await expect(entries(page).getByText(/created group Contractors/)).toHaveCount(0)

  await page.getByRole('button', { name: 'Remove project filter' }).click()
  await page.getByRole('button', { name: /^When/ }).click()
  await page.getByLabel('From').fill('2020-01-01')
  await page.getByLabel('To (inclusive)').fill('2020-01-31')
  await page.keyboard.press('Escape')
  await expect(page).toHaveURL(/from=2020-01-01&to=2020-01-31|to=2020-01-31.*from=2020-01-01/)
  await expect(page.getByText('No entries match these filters')).toBeVisible()
  await page.getByRole('button', { name: 'Clear filters' }).first().click()
  await expect(entries(page)).toBeVisible()
})

test('a user’s “Audit log” link shows the entries about them', async ({ page }) => {
  await page.goto(`/settings/users/${USERS.bob}`)
  const sheet = page.getByRole('dialog', { name: /Bob Chen/ })
  await sheet.getByRole('link', { name: 'Audit log' }).click()
  await expect(page).toHaveURL(new RegExp(`/settings/audit\\?target=user(:|%3A)${USERS.bob}$`))
  await expect(page.getByText('About · Bob Chen')).toBeVisible()
  await expect(entries(page).getByText('Bob Chen signed in with SSO').first()).toBeVisible()
  await expect(
    entries(page).getByText(/Priya Natarajan signed Bob Chen out everywhere/),
  ).toBeVisible()
  await page.getByRole('button', { name: 'Remove “about Bob Chen” filter' }).click()
  await expect(page).toHaveURL(/\/settings\/audit$/)
})

test('scrolling loads older entries', async ({ page }) => {
  await openAudit(page)
  const main = page.locator('main')
  const lastDay = async () =>
    (await entries(page).getByRole('heading', { level: 3 }).allInnerTexts()).at(-1)
  const before = await lastDay()
  for (let i = 0; i < 6; i++) {
    await main.evaluate((m) => m.scrollBy(0, 4000))
    await page.waitForTimeout(150)
  }
  await expect.poll(lastDay).not.toBe(before)
})
