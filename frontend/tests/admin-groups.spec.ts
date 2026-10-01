import type { Page } from '@playwright/test'

import { expect, test, USERS } from './support'

/**
 * Admin settings → Groups (contract-phase2 §3.5, §3.6, §3.12): the list, a
 * group's identity-provider mapping (normalised values, managed/additive),
 * manual members, and the "Test mapping" box. Fixture groups mirror the dev
 * Keycloak realm; ids from src/mocks/access-fixtures.ts.
 */

test.use({ signedInAs: USERS.priya })

const GROUPS = {
  toolsMembers: '90000000-0000-4000-8000-000000000003',
  viewers: '90000000-0000-4000-8000-000000000004',
  champions: '90000000-0000-4000-8000-000000000005',
}

const toast = (page: Page, text: string | RegExp) =>
  page.locator('[data-sonner-toast]', { hasText: text })

async function openGroup(page: Page, id: string, name: string) {
  await page.goto(`/settings/groups/${id}`)
  await expect(page.getByRole('heading', { level: 2, name })).toBeVisible()
}

test('lists groups with members, mapping and projects; creates one', async ({ page }) => {
  await page.goto('/settings/groups')
  const table = page.getByRole('table', { name: 'Groups' })
  const row = (name: string) => table.getByRole('row').filter({ hasText: name })
  await expect(row('Tools members')).toContainText('6 people')
  await expect(row('Tools members')).toContainText('Managed:')
  await expect(row('Tools members')).toContainText('tools/members')
  await expect(row('Sustainability champions')).toContainText('Not mapped')
  await expect(row('Viewers')).toContainText('Additive:')

  await page.getByRole('searchbox', { name: 'Search groups' }).fill('innov')
  await expect(table.getByRole('row')).toHaveCount(3)

  await page.getByRole('button', { name: 'New group' }).click()
  const dialog = page.getByRole('dialog', { name: 'New group' })
  await dialog.getByRole('textbox', { name: 'Name' }).fill('Innovation members')
  await dialog.getByRole('button', { name: /^Create group/ }).click()
  await expect(dialog.getByText('A group with this name already exists.')).toBeVisible()

  await dialog.getByRole('textbox', { name: 'Name' }).fill('Board')
  const values = dialog.getByRole('textbox', { name: 'Identity provider groups' })
  await values.fill(' /Leadership/Board ')
  await expect(dialog.getByText('Saved as')).toBeVisible()
  await expect(dialog.locator('code', { hasText: 'leadership/board' })).toBeVisible()
  await values.press('Enter')
  await dialog.getByRole('radio', { name: /Additive/ }).click()
  await dialog.getByRole('button', { name: /^Create group/ }).click()
  await expect(toast(page, 'Board created')).toBeVisible()
  await expect(page.getByRole('heading', { level: 2, name: 'Board' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Remove leadership/board' })).toBeVisible()
  await expect(page.getByRole('radio', { name: /Additive/ })).toBeChecked()
})

test('edits a mapping with normalised values and saves it', async ({ page }) => {
  await openGroup(page, GROUPS.viewers, 'Viewers')
  const values = page.getByRole('textbox', { name: 'Identity provider groups' })
  // Pasting a list adds every entry, normalised.
  await values.fill('/Stakeholders/, //Board/Members')
  await values.press('Enter')
  await expect(page.getByRole('button', { name: 'Remove stakeholders' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Remove board/members' })).toBeVisible()
  // A value that is empty once normalised is refused.
  await values.fill('/')
  await values.press('Enter')
  await expect(page.getByText('“/” is empty once the slashes are removed.')).toBeVisible()

  await page.getByRole('radio', { name: /Managed/ }).click()
  await page.getByRole('button', { name: 'Remove viewers' }).click()
  // Test mapping is a sheet: it says the unsaved mapping isn't what it tests.
  await page
    .getByRole('region', { name: 'Identity provider' })
    .getByRole('button', {
      name: 'Test mapping',
    })
    .click()
  const sheet = page.getByRole('dialog', { name: 'Test mapping' })
  await expect(sheet.getByText('Save the mapping to test it')).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(sheet).toHaveCount(0)
  await page.getByRole('button', { name: 'Save mapping' }).click()
  await expect(toast(page, 'Mapping saved')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Save mapping' })).toHaveCount(0)
  await expect(page.getByText(/managed sync/)).toBeVisible()
})

test('adds a manual member and removes them with Undo; synced rows are read-only', async ({
  page,
}) => {
  await openGroup(page, GROUPS.champions, 'Sustainability champions')
  const members = page.getByRole('list', { name: 'Members' })
  await expect(members.getByRole('listitem')).toHaveCount(2)

  await page.getByRole('combobox', { name: 'Add a person by hand' }).click()
  await page.getByPlaceholder('Search by name or email…').fill('ivan')
  await page.getByRole('option', { name: /Ivan Petrov/ }).click()
  await page.getByRole('button', { name: 'Add', exact: true }).click()
  await expect(toast(page, 'Ivan Petrov added to Sustainability champions')).toBeVisible()
  const ivan = members.getByRole('listitem').filter({ hasText: 'Ivan Petrov' })
  await expect(ivan).toContainText('Manual')

  await ivan.getByRole('button', { name: 'Remove Ivan Petrov' }).click()
  await expect(ivan).toHaveCount(0)
  await toast(page, 'Ivan Petrov removed from Sustainability champions')
    .getByRole('button', { name: 'Undo' })
    .click()
  await expect(members.getByRole('listitem').filter({ hasText: 'Ivan Petrov' })).toBeVisible()

  // Synced-only members have no Remove button, only the tucked-away menu.
  await openGroup(page, GROUPS.toolsMembers, 'Tools members')
  const bob = page.getByRole('list', { name: 'Members' }).getByRole('listitem').filter({
    hasText: 'Bob Chen',
  })
  await expect(bob).toContainText('Synced')
  await expect(bob.getByRole('button', { name: 'Remove Bob Chen' })).toHaveCount(0)
  await bob.getByRole('button', { name: /More for Bob Chen/ }).click()
  await expect(page.getByRole('menuitem', { name: 'Remove until next sign-in' })).toBeVisible()
})

test('test mapping shows joins, leaves and stays for a person', async ({ page }) => {
  await page.goto('/settings/groups')
  await page.getByRole('button', { name: 'Test mapping' }).click()
  const sheet = page.getByRole('dialog', { name: 'Test mapping' })
  const claims = sheet.getByRole('textbox', { name: 'Claims' })

  await claims.fill('{ "groups": [ ')
  await sheet.getByRole('button', { name: 'Test mapping' }).click()
  await expect(
    sheet.getByText('That isn’t valid JSON. Check for missing quotes or commas.'),
  ).toBeVisible()
  // Straight back to the field to fix.
  await expect(claims).toBeFocused()

  await claims.fill(
    JSON.stringify({ sub: 'k-1', groups: ['/Innovation/Members', '/viewers', 42, '/'] }),
  )
  await sheet.getByRole('combobox', { name: /Person/ }).click()
  await page.getByPlaceholder('Search by name or email…').fill('bob')
  await page.getByRole('option', { name: /Bob Chen/ }).click()
  await sheet.getByRole('button', { name: 'Test mapping' }).click()

  const result = sheet.getByRole('region', { name: 'Test result' })
  await expect(result.getByText('Found 2 values in “groups”')).toBeVisible()
  await expect(result.getByText('2 entries were ignored (not text, or empty).')).toBeVisible()
  await expect(
    result.getByText('This person joins 1 group, leaves 1 group and stays in 1 group'),
  ).toBeVisible()
  const rows = result.getByRole('list', { name: 'Groups' }).getByRole('listitem')
  await expect(rows.nth(0)).toContainText('Joins')
  await expect(rows.nth(0)).toContainText('Viewers')
  await expect(rows.nth(1)).toContainText('Leaves')
  await expect(rows.nth(1)).toContainText('Tools members')
  await expect(rows.nth(1)).toContainText('No longer matches, so they leave this managed group.')
  await expect(rows.nth(2)).toContainText('Stays')
  await expect(rows.nth(2)).toContainText('Innovation members')
  const roles = result.getByRole('list', { name: 'Project roles after signing in' })
  await expect(roles.getByRole('listitem').filter({ hasText: 'Sustainability' })).toContainText(
    'via Viewers',
  )

  // A missing claim counts as no groups.
  await claims.fill('{ "sub": "k-1" }')
  await expect(result.getByText('The claims changed: test again to update.')).toBeVisible()
  await sheet.getByRole('button', { name: 'Test mapping' }).click()
  await expect(sheet.getByText('No “groups” claim in these claims')).toBeVisible()
})

test('the group page puts members first and returns to its row in the list', async ({ page }) => {
  await page.goto('/settings/groups')
  const table = page.getByRole('table', { name: 'Groups' })
  const tools = table.getByRole('row').filter({ hasText: 'Tools members' }).getByRole('link')
  await tools.focus()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('heading', { level: 2, name: 'Tools members' })).toBeVisible()
  await expect(page.getByRole('main').getByRole('heading', { level: 3 }).first()).toHaveText(
    'Members',
  )

  // The test keeps its claims when the sheet closes and opens again.
  await page.getByRole('button', { name: 'Test mapping' }).click()
  const sheet = page.getByRole('dialog', { name: 'Test mapping' })
  await expect(sheet).toBeFocused()
  await sheet.getByRole('textbox', { name: 'Claims' }).fill('{ "groups": ["/tools/members"] }')
  await page.keyboard.press('Escape')
  await page.getByRole('button', { name: 'Test mapping' }).click()
  await expect(sheet.getByRole('textbox', { name: 'Claims' })).toHaveValue(
    '{ "groups": ["/tools/members"] }',
  )
  await sheet.getByRole('button', { name: 'Test mapping' }).click()
  await expect(sheet.getByRole('region', { name: 'Test result' })).toContainText('This group')
  await page.keyboard.press('Escape')

  await page.getByRole('link', { name: 'All groups' }).click()
  await expect(tools).toBeFocused()
})
