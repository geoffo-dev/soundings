import type { Page } from '@playwright/test'

import { expect, seriousViolations, test, USERS } from './support'

/**
 * Admin settings → AI agents (contract-phase6 §3.15) against the mock: Idea
 * evaluator and the Research agent are enabled; Market scout is disabled, has
 * no key, and is a viewer in Internal Tools.
 */
test.use({ signedInAs: USERS.priya })

const row = (page: Page, name: string) => page.getByRole('row').filter({ hasText: name })

async function openPage(page: Page) {
  await page.goto('/settings/ai-agents')
  await expect(page.getByRole('heading', { name: 'AI agents', level: 2 })).toBeVisible()
  await expect(page.locator('[data-slot="skeleton"]')).toHaveCount(0)
}

async function fillRegistration(page: Page) {
  await page.getByRole('button', { name: 'Register agent' }).click()
  const sheet = page.getByRole('dialog', { name: 'Register agent' })
  await sheet.getByRole('textbox', { name: 'Display name' }).fill('Market analyst')
  await sheet.getByRole('textbox', { name: 'Namespace' }).fill('soundings')
  await sheet.getByRole('textbox', { name: 'Agent name' }).fill('market-analyst')
  await sheet.getByRole('checkbox', { name: 'Research ideas' }).click()
  await sheet.getByRole('checkbox', { name: 'Customer Innovation' }).click()
  return sheet
}

test('lists agents with what they do, their projects, keys and the settings in effect', async ({
  page,
}) => {
  await openPage(page)
  const evaluator = row(page, 'Idea evaluator')
  await expect(evaluator).toContainText('soundings/idea-evaluator')
  await expect(evaluator).toContainText('Evaluation')
  await expect(evaluator).toContainText('sdg_Id3aEva1uat0')
  await expect(evaluator).toContainText('Enabled')
  const scout = row(page, 'Market scout')
  await expect(scout).toContainText('Disabled')
  await expect(scout).toContainText('No key: rotate to issue one')
  await expect(scout).toContainText('Viewer: can’t work there')
  const settings = page.getByRole('region', { name: 'Settings in effect' })
  await expect(settings).toContainText('http://kagent-controller.kagent:8083')
  await expect(settings).toContainText('soundings, kagent-agents')
  await expect(
    page.getByRole('link', { name: 'Runs and changes in the audit log' }),
  ).toHaveAttribute('href', '/settings/audit?action=ai')
})

test('registers an agent and shows its key and Secret once', async ({ page }) => {
  await openPage(page)
  const sheet = await fillRegistration(page)
  // The URL is built from the controller URL in effect, never typed.
  await expect(sheet).toContainText(
    'http://kagent-controller.kagent:8083/api/a2a/soundings/market-analyst/',
  )
  await sheet.getByRole('button', { name: /^Register agent/ }).click()

  const dialog = page.getByRole('dialog', { name: 'Copy the agent’s key' })
  await expect(dialog).toBeVisible()
  const key = await dialog.locator('code').first().textContent()
  expect(key).toMatch(/^sdg_[A-Za-z0-9]{12}_[A-Za-z0-9]{40}$/)
  await expect(dialog.getByRole('figure', { name: 'the Secret manifest' })).toContainText(
    `authorization: "Bearer ${key ?? ''}"`,
  )
  await expect(dialog.getByRole('figure', { name: 'the RemoteMCPServer manifest' })).toContainText(
    'name: soundings-agent-market-analyst',
  )
  // Closing before copying asks once.
  await dialog.getByRole('button', { name: 'I’ve copied it' }).click()
  await expect(dialog.getByRole('alert')).toContainText('You haven’t copied the key')
  await dialog.getByRole('button', { name: 'Close without copying' }).click()
  await expect(dialog).toHaveCount(0)

  await expect(row(page, 'Market analyst')).toContainText('soundings/market-analyst')
  // The key is gone from the page for good.
  await expect(page.locator('body')).not.toContainText(key ?? 'no key')
})

test('shows the API’s refusal next to the field it is about', async ({ page }) => {
  await openPage(page)
  const sheet = await fillRegistration(page)
  await sheet.getByRole('textbox', { name: 'Agent name' }).fill('idea-evaluator')
  await sheet.getByRole('button', { name: /^Register agent/ }).click()
  await expect(
    sheet.getByText('An agent with this namespace and name is already registered.'),
  ).toBeVisible()
  await expect(sheet.getByRole('textbox', { name: 'Agent name' })).toBeFocused()

  await sheet.getByRole('textbox', { name: 'Namespace' }).fill('kagent')
  await sheet.getByRole('button', { name: /^Register agent/ }).click()
  await expect(sheet.getByText('Agents can run in soundings, kagent-agents')).toBeVisible()
})

test('tests the connection: the agent card, or why it didn’t answer', async ({ page }) => {
  await openPage(page)
  await row(page, 'Idea evaluator')
    .getByRole('button', { name: 'Actions for Idea evaluator' })
    .click()
  await page.getByRole('menuitem', { name: 'Test connection' }).click()
  const ok = page.getByRole('dialog', { name: 'Idea evaluator answered' })
  await expect(ok).toContainText('soundings__NS__idea_evaluator')
  await expect(ok).toContainText('0.3, 1.0')
  await expect(ok).toContainText('Evaluate an idea')
  await ok.getByRole('button', { name: 'Done' }).click()

  await row(page, 'Market scout').getByRole('button', { name: 'Actions for Market scout' }).click()
  await page.getByRole('menuitem', { name: 'Test connection' }).click()
  const down = page.getByRole('dialog', { name: 'Market scout didn’t answer' })
  await expect(down).toContainText('Couldn’t reach the agent.')
})

test('disables (runs stop, key revoked), enables, then rotates a new key', async ({ page }) => {
  await openPage(page)
  const evaluator = row(page, 'Idea evaluator')
  await evaluator.getByRole('button', { name: 'Actions for Idea evaluator' }).click()
  await page.getByRole('menuitem', { name: 'Disable…' }).click()
  const confirm = page.getByRole('alertdialog', { name: 'Disable Idea evaluator?' })
  await expect(confirm).toContainText('its key is revoked')
  await confirm.getByRole('button', { name: 'Disable agent' }).click()
  await expect(evaluator).toContainText('Disabled')
  await expect(evaluator).toContainText('No key: rotate to issue one')

  await evaluator.getByRole('button', { name: 'Actions for Idea evaluator' }).click()
  await page.getByRole('menuitem', { name: 'Enable' }).click()
  await expect(evaluator).toContainText('Enabled')
  await page.locator('[data-sonner-toast]').getByRole('button', { name: 'Rotate key' }).click()
  const rotate = page.getByRole('alertdialog', { name: 'Rotate Idea evaluator’s key?' })
  await expect(rotate).toContainText('the agent stops until its Secret holds the new key')
  await rotate.getByRole('button', { name: 'Rotate key' }).click()
  const dialog = page.getByRole('dialog', { name: 'Copy the agent’s new key' })
  await dialog.getByRole('button', { name: 'Copy the agent’s key' }).click()
  await dialog.getByRole('button', { name: 'I’ve copied it' }).click()
  await expect(dialog).toHaveCount(0)
  await expect(evaluator).not.toContainText('No key')
})

test('warns that narrowing an agent stops its runs there', async ({ page }) => {
  await openPage(page)
  await row(page, 'Idea evaluator')
    .getByRole('button', { name: 'Actions for Idea evaluator' })
    .click()
  await page.getByRole('menuitem', { name: 'Change…' }).click()
  const sheet = page.getByRole('dialog', { name: 'Change Idea evaluator' })
  await expect(sheet.getByRole('textbox', { name: 'Namespace' })).toBeDisabled()
  await sheet.getByRole('checkbox', { name: 'Research ideas' }).click()
  await expect(sheet).toContainText('cancels the agent’s active runs')
  await sheet.getByRole('button', { name: /^Save changes/ }).click()
  await expect(sheet).toHaveCount(0)
  await expect(row(page, 'Idea evaluator')).not.toContainText('Research')
})

test('is a 404 for everyone but platform admins', async ({ page, context, baseURL }) => {
  await context.addCookies([
    { name: 'soundings_mock_session', value: USERS.alice, url: baseURL ?? '' },
  ])
  await page.goto('/settings/ai-agents')
  await expect(
    page.getByRole('heading', { level: 1, name: 'We couldn’t find that page' }),
  ).toBeVisible()
})

for (const scheme of ['light', 'dark'] as const) {
  test(`has no serious axe violations, with the sheet and the key dialog (${scheme})`, async ({
    page,
  }) => {
    await page.emulateMedia({ colorScheme: scheme })
    await openPage(page)
    expect(await seriousViolations(page)).toEqual([])
    const sheet = await fillRegistration(page)
    expect(await seriousViolations(page)).toEqual([])
    await sheet.getByRole('button', { name: /^Register agent/ }).click()
    await expect(page.getByRole('dialog', { name: 'Copy the agent’s key' })).toBeVisible()
    expect(await seriousViolations(page)).toEqual([])
  })
}

test('fits a phone', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await openPage(page)
  await expect(
    row(page, 'Idea evaluator').getByRole('button', { name: 'Rotate key' }),
  ).toBeVisible()
  const width = await page.evaluate(() => document.documentElement.scrollWidth)
  expect(width).toBeLessThanOrEqual(390)
})
