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
  // What it can do in plain words; the scope names for assistive tech.
  await expect(claude).toContainText('Read and evaluate')
  await expect(claude).toContainText('Also through AI assistants')
  await expect(claude).toContainText('Scopes: Read, Evaluate, AI assistants (MCP)')
  await expect(claude).toContainText('Customer Innovation')
  await expect(claude).toContainText('Never')
  await expect(claude).toContainText('2 hours ago')
  await expect(keyRow(page, 'Weekly report script')).toContainText('All projects')
  await expect(keyRow(page, 'Weekly report script')).toContainText('Read only')
  // Within a week of its expiry: when, relatively.
  await expect(keyRow(page, 'Weekly report script')).toContainText('in 3 days')
  // Expired: last, and only removable (it already stopped).
  const old = keyRow(page, 'Old laptop')
  await expect(old).toContainText('Expired')
  await expect(old.getByRole('button', { name: 'Remove Old laptop' })).toBeVisible()
  await expect(keys(page).getByRole('row').last()).toContainText('Old laptop')
  await expect(page.getByText('Keys pause when you haven’t signed in')).toBeVisible()
  // For developers: folded away until asked for, then the URL and header to give a client.
  const connect = page.getByRole('region', { name: 'For developers and AI assistants' })
  const toggle = connect.getByRole('button', { name: 'For developers and AI assistants' })
  await expect(toggle).toHaveAttribute('aria-expanded', 'false')
  await expect(connect).not.toContainText('Authorization: Bearer')
  await toggle.click()
  await expect(toggle).toHaveAttribute('aria-expanded', 'true')
  await expect(connect).toContainText(/http:\/\/localhost:\d+\/mcp/)
  await expect(connect.getByRole('link', { name: /Every endpoint/ })).toHaveAttribute(
    'href',
    '/api/docs',
  )
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
  await dialog.getByRole('button', { name: 'Evaluate with an assistant' }).click()
  await expect(dialog.getByRole('button', { name: 'Evaluate with an assistant' })).toHaveAttribute(
    'aria-pressed',
    'true',
  )
  await expect(dialog.getByText('they count as yours')).toBeVisible()
  // What the choices add up to, in plain words, by the Create button.
  const summary = dialog.locator('#create-key-summary')
  await expect(summary).toHaveText(
    /^This key can read everything you can see and submit your evaluations, also through AI assistants, in every project you can open, until .+ or until you revoke it\.$/,
  )
  await expect(dialog.getByRole('button', { name: /^Create key/ })).toHaveAccessibleDescription(
    /This key can read everything/,
  )
  // An assistant on every project: a nudge towards fewer.
  await expect(dialog.getByText('keep it to the projects it needs')).toBeVisible()
  // The scopes themselves are behind "Custom".
  await expect(dialog.getByRole('checkbox', { name: /^Read/ })).toBeHidden()
  await dialog.getByRole('button', { name: 'Custom' }).click()
  await expect(dialog.getByRole('button', { name: 'Custom' })).toHaveAttribute(
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
  await dialog.getByRole('button', { name: 'Evaluate with an assistant' }).click()
  await expect(dialog.getByRole('checkbox', { name: /^Read/ })).toBeHidden()

  await dialog.getByRole('radio', { name: '30 days' }).click()
  await expect(dialog.getByText(/Stops working on/)).toBeVisible()
  await dialog.getByText('Only these projects').click()
  await dialog.getByRole('button', { name: /^Create key/ }).click()
  await expect(dialog.getByText('Choose at least one project')).toBeVisible()
  await dialog.getByRole('checkbox', { name: 'Customer Innovation' }).click()
  await expect(summary).toContainText('only in Customer Innovation, until')

  const created = page.waitForResponse(
    (response) => response.url().includes('/me/api-keys') && response.request().method() === 'POST',
  )
  await dialog.getByRole('button', { name: /^Create key/ }).click()
  const body = (await (await created).json()) as { secret: string; key: { prefix: string } }
  expect(body.secret).toMatch(/^sdg_[A-Za-z0-9]{12}_[A-Za-z0-9]{40}$/)

  const secret = page.getByRole('dialog', { name: 'Copy your new key' })
  await expect(secret).toContainText(body.secret)
  await expect(secret).toContainText('you won’t see it again')
  // What anyone holding it could do, before it goes anywhere.
  await expect(secret).toContainText('Treat it like a password')
  await expect(secret).toContainText(
    'Anyone who has it can act as you: read everything you can see and submit your evaluations, also through AI assistants, only in Customer Innovation, until',
  )
  await expect(secret.getByRole('tab', { name: 'MCP config' })).toBeVisible()
  await expect(secret.locator('pre')).toContainText(`Bearer ${body.secret}`)
  await secret.getByRole('tab', { name: 'Claude Code' }).click()
  await expect(secret.locator('pre')).toContainText('claude mcp add --transport http soundings')
  // A click outside doesn't lose the key.
  await page.mouse.click(5, 5)
  await expect(secret).toBeVisible()
  // Not copied yet: closing asks once, and the question offers the copy.
  await secret.getByRole('button', { name: 'I’ve copied it' }).click()
  await expect(secret.getByRole('alert')).toContainText('You haven’t copied the key')
  await expect(secret).toBeVisible()
  await expect(secret.locator('#new-key-copy-after-all')).toBeFocused()
  await secret.getByRole('button', { name: 'Close without copying' }).click()
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

test('a copied key closes at once; uncopied, Esc asks once and then closes', async ({
  page,
  context,
}) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write'])
  await open(page)
  const create = async (name: string) => {
    await page.getByRole('button', { name: 'Create key' }).click()
    const dialog = page.getByRole('dialog', { name: 'Create API key' })
    await dialog.getByLabel('Name').fill(name)
    await dialog.getByRole('button', { name: /^Create key/ }).click()
    const secret = page.getByRole('dialog', { name: 'Copy your new key' })
    await expect(secret.getByRole('button', { name: 'Copy key' })).toBeFocused()
    return secret
  }

  let secret = await create('Copied first')
  await secret.getByRole('button', { name: 'Copy key' }).click()
  await expect(secret.getByText('Copied', { exact: true })).toBeVisible()
  await secret.getByRole('button', { name: 'I’ve copied it' }).click()
  await expect(secret).toHaveCount(0)
  await expect(keyRow(page, 'Copied first').locator('[data-row-id]')).toBeFocused()

  secret = await create('Never copied')
  await page.keyboard.press('Escape')
  await expect(secret.getByRole('alert')).toContainText('You haven’t copied the key')
  // The question's own Copy takes focus: copying from there goes back to "I've copied it".
  await page.keyboard.press('Enter')
  await expect(secret.getByRole('alert')).toHaveCount(0)
  await expect(secret.getByRole('button', { name: 'I’ve copied it' })).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(secret).toHaveCount(0)

  secret = await create('Closed anyway')
  await page.keyboard.press('Escape')
  await expect(secret.getByRole('alert')).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(secret).toHaveCount(0)
})

test('an expired key is removed, not revoked', async ({ page }) => {
  await open(page)
  await keyRow(page, 'Old laptop').getByRole('button', { name: 'Remove Old laptop' }).click()
  const confirm = page.getByRole('alertdialog', { name: 'Remove “Old laptop”?' })
  await expect(confirm).toContainText('It already stopped working when it expired')
  await confirm.getByRole('button', { name: 'Remove key' }).click()
  await expect(toast(page, '“Old laptop” removed')).toBeVisible()
  await expect(keyRow(page, 'Old laptop')).toHaveCount(0)
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
    await expect(
      page.getByRole('region', { name: 'For developers and AI assistants' }),
    ).toBeVisible()
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
    await expect(dialog).toBeVisible()
    // Measured once the open animation (a slight zoom) has finished.
    await expect.poll(async () => (await dialog.boundingBox())?.width ?? 0).toBeGreaterThan(385)
  })
})
