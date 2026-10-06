import type { Page } from '@playwright/test'

import { expect, seriousViolations, test, USERS } from './support'

/**
 * Admin settings → API keys (contract-phase5 §3.10) against the mock: seven keys
 * that aren't revoked, among them the Research agent's (a service account, key
 * created by Priya), Mateo Rossi's dormant one and Alice's expired "Old laptop".
 */

test.use({ signedInAs: USERS.priya })

const ALICE = USERS.alice
const WHOLE_KEY = 'sdg_Cl4uDeD3sk7p_0123456789abcdefghijABCDEFGHIJ0123456789'

const table = (page: Page) => page.getByRole('table', { name: 'API keys' })
const keyRow = (page: Page, name: string) => table(page).getByRole('row').filter({ hasText: name })
const toast = (page: Page, text: string | RegExp) =>
  page.locator('[data-sonner-toast]', { hasText: text })

async function open(page: Page, query = '') {
  await page.goto(`/settings/all-api-keys${query}`)
  await expect(page.getByRole('heading', { level: 2, name: 'All API keys' })).toBeVisible()
  await expect(page.locator('[data-slot="skeleton"]')).toHaveCount(0)
}

test('lists every key with its owner, scopes, projects, use, expiry and state', async ({
  page,
}) => {
  await open(page)
  await expect(page.getByText('7 keys')).toBeVisible()
  await expect(table(page).getByRole('row')).toHaveCount(8)
  const agent = keyRow(page, 'kagent research-agent')
  await expect(agent).toContainText('Research agent')
  await expect(agent).toContainText('AI agent')
  // The owner has a line to themselves: their name is never cut off (the key name gives way).
  const ownerLink = agent.getByRole('link', { name: /^Research agent/ })
  expect(
    await ownerLink.evaluate((element) => element.scrollWidth <= element.clientWidth + 1),
  ).toBe(true)
  await expect(agent).toContainText('Created by Priya Natarajan')
  await expect(agent).toContainText('sdg_R3s3archAg3n')
  await expect(agent).toContainText('Customer Innovation')
  const dormant = keyRow(page, 'Spreadsheet sync')
  await expect(dormant).toContainText('Dormant')
  await expect(dormant).toContainText('The owner hasn’t signed in for 30 days')
  await expect(keyRow(page, 'Old laptop')).toContainText('Expired')
  await expect(keyRow(page, 'Jira sync')).toContainText('Never used')
  // The owner links to their admin page.
  await keyRow(page, 'Jira sync').getByRole('link', { name: 'Bob Chen' }).click()
  await expect(page.getByRole('dialog', { name: /Bob Chen/ })).toBeVisible()
})

test('a pasted whole key is searched by its prefix only: never in the URL or a request', async ({
  page,
}) => {
  await open(page)
  const requests: string[] = []
  page.on('request', (request) => requests.push(request.url()))
  const search = page.getByRole('searchbox', { name: 'Search API keys' })
  await search.fill(`Bearer ${WHOLE_KEY}`)
  await expect(page).toHaveURL(/q=sdg_Cl4uDeD3sk7p(&|$)/)
  await expect(search).toHaveValue('sdg_Cl4uDeD3sk7p')
  await expect(page.getByRole('status').filter({ hasText: 'You pasted a whole key' })).toBeVisible()
  await expect(table(page).getByRole('row')).toHaveCount(2)
  await expect(keyRow(page, 'Claude Desktop')).toContainText('Alice Anders')
  expect(page.url()).not.toContain(WHOLE_KEY.slice(17))
  expect(requests.some((url) => url.includes(WHOLE_KEY.slice(17)))).toBe(false)

  // Half a key (pasted short, or being typed): the secret part goes nowhere either.
  await search.fill(WHOLE_KEY.slice(0, 30))
  await expect(page).toHaveURL(/q=sdg_Cl4uDeD3sk7p(&|$)/)
  await expect(page.getByRole('status').filter({ hasText: 'That’s part of a key' })).toBeVisible()
  expect(requests.some((url) => url.includes(WHOLE_KEY.slice(17, 30)))).toBe(false)

  // Names and owners match in part; a near-miss prefix matches nothing.
  await search.fill('sdg_Cl4uDeD3sk7')
  await expect(page.getByRole('heading', { name: 'No keys match' })).toBeVisible()
  await page.getByRole('button', { name: 'Clear filters' }).click()
  await expect(page.getByText('7 keys')).toBeVisible()
  await search.fill('mateo')
  await expect(table(page).getByRole('row')).toHaveCount(2)
})

test('filters by state, and by owner from their admin page', async ({ page }) => {
  await open(page)
  await page.getByRole('button', { name: /^State/ }).click()
  // Two-line options: every line inside its row, nothing overlapping.
  const options = page.getByRole('option')
  await expect(options).toHaveCount(3)
  for (const option of await options.all()) {
    expect(
      await option.evaluate((element) => element.scrollHeight <= element.clientHeight + 1),
    ).toBe(true)
  }
  expect(await seriousViolations(page)).toEqual([])
  await page.getByRole('option', { name: /Dormant/ }).click()
  await expect(page).toHaveURL(/state=dormant/)
  await expect(table(page).getByRole('row')).toHaveCount(2)
  await expect(keyRow(page, 'Spreadsheet sync')).toBeVisible()
  await page.getByRole('button', { name: 'Remove State filter' }).click()

  // From Alice's admin page: her keys only.
  await page.goto(`/settings/users/${ALICE}`)
  const sheet = page.getByRole('dialog', { name: /Alice Anders/ })
  await sheet.getByRole('link', { name: 'API keys' }).click()
  await expect(page).toHaveURL(new RegExp(`/settings/all-api-keys\\?user_id=${ALICE}$`))
  await expect(page.getByText('3 keys')).toBeVisible()
  await expect(page.locator('[data-slot="filter-value-chip"]')).toContainText('Alice Anders')
  await page.getByRole('button', { name: 'Remove Owner filter' }).click()
  await expect(page.getByText('7 keys')).toBeVisible()
})

test('revokes anyone’s key after a confirm that names it; focus moves to the next key', async ({
  page,
}) => {
  await open(page)
  await keyRow(page, 'Jira sync')
    .getByRole('button', { name: 'Revoke Bob Chen’s key Jira sync' })
    .click()
  const confirm = page.getByRole('alertdialog', { name: 'Revoke Bob Chen’s key “Jira sync”?' })
  await expect(confirm).toContainText('stops working immediately')
  await expect(confirm).toContainText('sdg_J1r4SyncB0b2')
  await confirm.getByRole('button', { name: 'Revoke key' }).click()
  await expect(toast(page, 'Bob Chen’s key “Jira sync” revoked')).toBeVisible()
  await expect(keyRow(page, 'Jira sync')).toHaveCount(0)
  await expect(page.getByText('6 keys')).toBeVisible()
  await expect(keyRow(page, 'kagent research-agent').locator('[data-row-id]')).toBeFocused()
  // An agent's key: only an admin can make it a new one.
  await keyRow(page, 'kagent research-agent')
    .getByRole('button', { name: /^Revoke Research agent’s key/ })
    .click()
  await expect(page.getByRole('alertdialog')).toContainText(
    'an admin would need to create a new key for this agent',
  )
  await page.getByRole('alertdialog').getByRole('button', { name: 'Cancel' }).click()
  // The audit log has it (in-app navigation: a page load resets the mock).
  await page
    .getByRole('navigation', { name: 'Settings sections' })
    .getByRole('link', { name: 'Audit log' })
    .click()
  await expect(page.getByText(/revoked API key sdg_J1r4SyncB0b2 of Bob Chen/).first()).toBeVisible()
})

test('"Sign out everywhere" says keys keep working and links to that person’s keys', async ({
  page,
}) => {
  await page.goto(`/settings/users/${USERS.bob}`)
  const sheet = page.getByRole('dialog', { name: /Bob Chen/ })
  await sheet.getByRole('button', { name: 'Sign out everywhere' }).click()
  const confirm = page.getByRole('alertdialog', { name: 'Sign Bob Chen out everywhere?' })
  await expect(confirm).toContainText('API keys keep working')
  await confirm.getByRole('link', { name: 'Review their keys' }).click()
  await expect(page).toHaveURL(new RegExp(`/settings/all-api-keys\\?user_id=${USERS.bob}$`))
  await expect(page.getByText('1 key', { exact: true })).toBeVisible()
})

test('deactivating someone says their keys are revoked, and they are', async ({ page }) => {
  await page.goto(`/settings/users/${ALICE}`)
  const sheet = page.getByRole('dialog', { name: /Alice Anders/ })
  await sheet.getByRole('button', { name: 'Deactivate…' }).click()
  const confirm = page.getByRole('alertdialog', { name: 'Deactivate Alice Anders?' })
  await expect(confirm).toContainText('Their API keys are revoked for good')
  await confirm.getByRole('button', { name: 'Deactivate' }).click()
  await expect(toast(page, 'Alice Anders deactivated')).toBeVisible()
  await sheet.getByRole('link', { name: 'API keys' }).click()
  await expect(page).toHaveURL(new RegExp(`/settings/all-api-keys\\?user_id=${ALICE}$`))
  await expect(page.getByRole('heading', { name: 'No keys match' })).toBeVisible()
})

test('shows an error with a retry when the keys can’t load', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('soundings-mock-fail', '/admin/api-keys'))
  await page.goto('/settings/all-api-keys')
  await expect(page.getByText('Couldn’t load API keys')).toBeVisible({ timeout: 10_000 })
  await page.evaluate(() => localStorage.removeItem('soundings-mock-fail'))
  await page.getByRole('button', { name: 'Try again' }).click()
  await expect(page.getByText('7 keys')).toBeVisible()
})

test('⌘K finds the page', async ({ page }) => {
  await page.goto('/settings')
  await expect(page.getByRole('heading', { level: 1, name: 'Settings' })).toBeVisible()
  await page.keyboard.press('ControlOrMeta+k')
  await page.keyboard.type('all api keys')
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(/\/settings\/all-api-keys$/)
})

test.describe('without platform admin rights', () => {
  test.use({ signedInAs: USERS.alice })

  test('the page is a plain 404', async ({ page }) => {
    await page.goto('/settings/all-api-keys')
    await expect(page.getByRole('heading', { name: 'We couldn’t find that page' })).toBeVisible()
  })
})

for (const theme of ['light', 'dark'] as const) {
  test(`is accessible (${theme}), with the revoke confirm open too`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: theme })
    await open(page)
    expect(await seriousViolations(page)).toEqual([])
    await keyRow(page, 'Jira sync')
      .getByRole('button', { name: 'Revoke Bob Chen’s key Jira sync' })
      .click()
    await expect(page.getByRole('alertdialog')).toBeVisible()
    expect(await seriousViolations(page)).toEqual([])
  })
}

test.describe('on a phone', () => {
  test.use({ viewport: { width: 390, height: 844 } })

  test('keys become cards without sideways scrolling', async ({ page }) => {
    await open(page)
    await expect(keyRow(page, 'kagent research-agent')).toBeVisible()
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true)
  })
})
