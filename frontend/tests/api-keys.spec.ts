import type { Page } from '@playwright/test'

import { expect, seriousViolations, test, USERS } from './support'

/**
 * Settings → API keys (contract-phase5 §3.10) against the mock. Alice has three
 * keys: "Claude Desktop" (read, evaluate, mcp; Customer Innovation only),
 * "Weekly report script" (read) and "Old laptop" (expired).
 */

const keys = (page: Page) => page.getByRole('table', { name: 'Your API keys' })
const keyRow = (page: Page, name: string) => keys(page).getByRole('row').filter({ hasText: name })
const toast = (page: Page, text: string | RegExp) =>
  page.locator('[data-sonner-toast]', { hasText: text })

async function open(page: Page) {
  await page.goto('/settings/api-keys')
  await expect(page.getByRole('heading', { level: 2, name: 'API keys' })).toBeVisible()
  await expect(page.locator('[data-slot="skeleton"]')).toHaveCount(0)
}

test('lists your keys with scopes, projects, expiry and last use', async ({ page }) => {
  await open(page)
  await expect(
    page.getByRole('navigation', { name: 'Settings sections' }).getByRole('link', {
      name: 'API keys',
    }),
  ).toHaveAttribute('aria-current', 'page')
  await expect(keys(page).getByRole('row')).toHaveCount(4) // header + 3
  const claude = keyRow(page, 'Claude Desktop')
  await expect(claude).toContainText('sdg_Cl4uDeD3sk7p')
  await expect(claude).toContainText('Read')
  await expect(claude).toContainText('MCP')
  await expect(claude).toContainText('Customer Innovation')
  await expect(claude).toContainText('Never')
  await expect(claude).toContainText('2 hours ago')
  await expect(keyRow(page, 'Weekly report script')).toContainText('All projects')
  await expect(keyRow(page, 'Old laptop')).toContainText('Expired')
  await expect(page.getByText('Keys pause when you haven’t signed in')).toBeVisible()
  // Connect an MCP client: the URL and header to give a client.
  const connect = page.getByRole('region', { name: 'Connect an MCP client' })
  await expect(connect).toContainText(/http:\/\/localhost:\d+\/mcp/)
  await expect(connect).toContainText('Authorization: Bearer <your key>')
  await expect(connect.getByRole('tab', { name: 'MCP config' })).toHaveAttribute(
    'aria-selected',
    'true',
  )
  await expect(connect).toContainText('"mcpServers"')
  await connect.getByRole('tab', { name: 'curl' }).click()
  await expect(connect).toContainText('/api/v1/projects')
})

test('creates a key, shows it once with ready-made examples, then never again', async ({
  page,
}) => {
  await open(page)
  await page.getByRole('button', { name: 'Create key' }).click()
  const dialog = page.getByRole('dialog', { name: 'Create API key' })
  await expect(dialog.getByLabel('Name')).toBeFocused()

  // A name is needed; the 409 for a name you already use lands on the field.
  await dialog.getByRole('button', { name: /^Create key/ }).click()
  await expect(dialog.getByText('Give the key a name')).toBeVisible()
  await dialog.getByLabel('Name').fill('claude desktop')
  await dialog.getByRole('button', { name: /^Create key/ }).click()
  await expect(dialog.getByText('You already have a key with this name')).toBeVisible()
  await dialog.getByLabel('Name').fill('Claude Code')

  // Presets fill the scopes; write or evaluate ticks and locks read.
  await dialog.getByRole('button', { name: 'AI evaluator' }).click()
  await expect(dialog.getByRole('button', { name: 'AI evaluator' })).toHaveAttribute(
    'aria-pressed',
    'true',
  )
  const read = dialog.getByRole('checkbox', { name: /^Read/ })
  await expect(read).toBeChecked()
  await expect(read).toBeDisabled()
  await dialog.getByRole('checkbox', { name: /^Evaluate/ }).click()
  await expect(read).toBeEnabled()
  await read.click()
  // MCP alone: allowed, but the form says it can't do anything.
  await expect(dialog.getByText('This key can connect, but do nothing')).toBeVisible()
  await dialog.getByRole('button', { name: 'AI evaluator' }).click()

  await dialog.getByRole('radio', { name: '30 days' }).click()
  await expect(dialog.getByText(/Stops working on/)).toBeVisible()
  await dialog.getByText('Only these projects').click()
  await dialog.getByRole('button', { name: /^Create key/ }).click()
  await expect(dialog.getByText('Choose at least one project')).toBeVisible()
  await dialog.getByRole('checkbox', { name: 'Customer Innovation' }).click()

  const created = page.waitForResponse(
    (response) => response.url().includes('/me/api-keys') && response.request().method() === 'POST',
  )
  await dialog.getByRole('button', { name: /^Create key/ }).click()
  const body = (await (await created).json()) as { secret: string; key: { prefix: string } }
  expect(body.secret).toMatch(/^sdg_[A-Za-z0-9]{12}_[A-Za-z0-9]{40}$/)

  const secret = page.getByRole('dialog', { name: 'Copy your new key' })
  await expect(secret).toContainText(body.secret)
  await expect(secret).toContainText('you won’t see it again')
  await expect(secret.getByRole('tab', { name: 'MCP config' })).toBeVisible()
  await expect(secret.locator('pre')).toContainText(`Bearer ${body.secret}`)
  await secret.getByRole('tab', { name: 'Claude Code' }).click()
  await expect(secret.locator('pre')).toContainText('claude mcp add --transport http soundings')
  // A click outside doesn't lose the key.
  await page.mouse.click(5, 5)
  await expect(secret).toBeVisible()
  await secret.getByRole('button', { name: 'Done' }).click()
  await expect(secret).toHaveCount(0)

  // The new row is first and has focus; the secret is nowhere on the page any more.
  const row = keyRow(page, 'Claude Code')
  await expect(row).toContainText(body.key.prefix)
  await expect(row).toContainText('Evaluate')
  await expect(row.locator('[data-row-id]')).toBeFocused()
  await expect(page.locator('body')).not.toContainText(body.secret)
  expect(page.url()).not.toContain(body.secret)
  expect(
    await page.evaluate(
      (value) => JSON.stringify(localStorage).includes(value) || document.cookie.includes(value),
      body.secret,
    ),
  ).toBe(false)
})

test('revoking asks first, explains there is no undo, and focuses the next key', async ({
  page,
}) => {
  await open(page)
  await keyRow(page, 'Claude Desktop')
    .getByRole('button', { name: 'Revoke Claude Desktop' })
    .click()
  const confirm = page.getByRole('alertdialog', { name: 'Revoke “Claude Desktop”?' })
  await expect(confirm).toContainText('stops working immediately')
  await expect(confirm).toContainText('There is no undo')
  await confirm.getByRole('button', { name: 'Cancel' }).click()
  await expect(keyRow(page, 'Claude Desktop')).toHaveCount(1)

  await keyRow(page, 'Claude Desktop')
    .getByRole('button', { name: 'Revoke Claude Desktop' })
    .click()
  await page
    .getByRole('alertdialog', { name: 'Revoke “Claude Desktop”?' })
    .getByRole('button', { name: 'Revoke key' })
    .click()
  await expect(toast(page, '“Claude Desktop” revoked')).toBeVisible()
  await expect(keyRow(page, 'Claude Desktop')).toHaveCount(0)
  await expect(keyRow(page, 'Weekly report script').locator('[data-row-id]')).toBeFocused()
})

test.describe('without keys', () => {
  test.use({ signedInAs: USERS.ivan })

  test('explains what keys are for, with one way to start', async ({ page }) => {
    await open(page)
    await expect(page.getByRole('heading', { name: 'No API keys yet' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Create key' })).toHaveCount(1)
    await expect(page.getByRole('region', { name: 'Connect an MCP client' })).toBeVisible()
  })
})

test('shows an error with a retry when the keys can’t load', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('soundings-mock-fail', '/me/api-keys'))
  await page.goto('/settings/api-keys')
  await expect(page.getByText('Couldn’t load your API keys')).toBeVisible({ timeout: 10_000 })
  await expect(page.getByRole('button', { name: 'Try again' })).toBeVisible()
})

for (const theme of ['light', 'dark'] as const) {
  test(`is accessible (${theme}), with the dialogs open too`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: theme })
    await open(page)
    expect(await seriousViolations(page)).toEqual([])
    await page.getByRole('button', { name: 'Create key' }).click()
    const dialog = page.getByRole('dialog', { name: 'Create API key' })
    await dialog.getByLabel('Name').fill('Axe check')
    await dialog.getByText('Only these projects').click()
    await dialog.getByRole('checkbox', { name: 'Customer Innovation' }).click()
    expect(await seriousViolations(page)).toEqual([])
    await dialog.getByRole('button', { name: /^Create key/ }).click()
    await expect(page.getByRole('dialog', { name: 'Copy your new key' })).toBeVisible()
    expect(await seriousViolations(page)).toEqual([])
  })
}

test.describe('on a phone', () => {
  test.use({ viewport: { width: 390, height: 844 } })

  test('keys become cards and the form fills the screen', async ({ page }) => {
    await open(page)
    await expect(keyRow(page, 'Claude Desktop')).toBeVisible()
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true)
    await page.getByRole('button', { name: 'Create key' }).click()
    const dialog = page.getByRole('dialog', { name: 'Create API key' })
    const box = await dialog.boundingBox()
    expect(box?.width).toBeGreaterThan(385)
  })
})
