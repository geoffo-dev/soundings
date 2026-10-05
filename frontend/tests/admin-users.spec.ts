import type { Page } from '@playwright/test'

import { expect, test, USERS } from './support'

/**
 * Admin settings → Users (contract-phase2 §3.4) against the mock: Priya
 * Natarajan is the platform admin; Bob Chen has SSO, an employee_no and two
 * groups; Lena Novak was pre-created and never signed in; Jonas is deactivated.
 */

test.use({ signedInAs: USERS.priya })

const BOB = USERS.bob

const toast = (page: Page, text: string | RegExp) =>
  page.locator('[data-sonner-toast]', { hasText: text })

const usersTable = (page: Page) => page.getByRole('table', { name: 'Users' })
const userRow = (page: Page, name: string) =>
  usersTable(page).getByRole('row').filter({ hasText: name })

async function openUsers(page: Page, query = '') {
  await page.goto(`/settings/users${query}`)
  await expect(page.getByRole('heading', { level: 2, name: 'Users' })).toBeVisible()
  await expect(page.locator('[data-slot="skeleton"]')).toHaveCount(0)
}

test('lists everyone, searches and filters through the URL', async ({ page }) => {
  await openUsers(page)
  await expect(page.getByRole('navigation', { name: 'Settings sections' })).toBeVisible()
  await expect(userRow(page, 'Bob Chen')).toContainText('Linked')
  await expect(userRow(page, 'Break-glass admin')).toContainText('Break-glass')
  await expect(userRow(page, 'Priya Natarajan')).toContainText('Platform admin')

  await page.getByRole('searchbox', { name: 'Search users' }).fill('lena')
  await expect(page).toHaveURL(/\?q=lena$/)
  await expect(usersTable(page).getByRole('row')).toHaveCount(2)
  await expect(userRow(page, 'Lena Novak')).toContainText('Not linked yet')

  await page.getByRole('searchbox', { name: 'Search users' }).fill('')
  await page.getByRole('button', { name: 'SSO not linked' }).click()
  await expect(page).toHaveURL(/unlinked=1/)
  await expect(userRow(page, 'Lena Novak')).toBeVisible()
  await expect(userRow(page, 'Bob Chen')).toHaveCount(0)

  await page.getByRole('button', { name: 'SSO not linked' }).click()
  await page.getByRole('button', { name: /^Status/ }).click()
  await page.getByRole('option', { name: 'Deactivated' }).click()
  await expect(page).toHaveURL(/status=deactivated/)
  await expect(userRow(page, 'Jonas')).toContainText('Deactivated')
  await expect(usersTable(page).getByRole('row')).toHaveCount(2)
})

test('opens a user in a sheet and returns to the filtered list', async ({ page }) => {
  await openUsers(page, '?q=bob')
  await userRow(page, 'Bob Chen').getByRole('link').click()
  const sheet = page.getByRole('dialog', { name: /Bob Chen/ })
  await expect(sheet).toBeVisible()
  await expect(page).toHaveURL(new RegExp(`/settings/users/${BOB}\\?q=bob$`))

  // Where access comes from, groups with provenance, the linked SSO account.
  const projects = sheet.getByRole('region', { name: 'Project access' })
  await expect(projects.getByRole('listitem').filter({ hasText: 'Internal Tools' })).toContainText(
    'Direct · via Tools members',
  )
  const groups = sheet.getByRole('region', { name: 'Groups' })
  await expect(groups.getByRole('listitem').filter({ hasText: 'Tools members' })).toContainText(
    'Synced',
  )
  await expect(sheet.getByText('http://localhost:8080/realms/soundings')).toBeVisible()
  await expect(sheet.getByLabel('External ID 1', { exact: true })).toHaveValue('E1002')

  await page.keyboard.press('Escape')
  await expect(sheet).toBeHidden()
  await expect(page).toHaveURL(/\/settings\/users\?q=bob$/)
})

test('pre-creates a user with an external ID', async ({ page }) => {
  await openUsers(page)
  await page.getByRole('button', { name: 'Add user' }).click()
  const dialog = page.getByRole('dialog', { name: 'Add user' })
  await expect(dialog.getByRole('textbox', { name: 'Email' })).toBeFocused()

  // Client-side checks first.
  await dialog.getByRole('button', { name: /^Add user/ }).click()
  await expect(dialog.getByText('Enter an email address')).toBeVisible()
  await expect(dialog.getByText('Enter their name')).toBeVisible()

  await dialog.getByRole('textbox', { name: 'Email' }).fill('nia.lee@example.com')
  await dialog.getByRole('textbox', { name: 'Name' }).fill('Nia Lee')
  // The configured kind (employee_no) is suggested in the first row.
  await expect(dialog.getByLabel('Kind of external ID 1')).toHaveValue('employee_no')
  await dialog.getByLabel('External ID 1', { exact: true }).fill('E1042')

  // The API answers 409 for an ID someone already has.
  await dialog.getByLabel('External ID 1', { exact: true }).fill('E1002')
  await dialog.getByRole('button', { name: /^Add user/ }).click()
  await expect(
    dialog.getByText(/Another person already has one of these external IDs/),
  ).toBeVisible()

  await dialog.getByLabel('External ID 1', { exact: true }).fill('E1042')
  await page.keyboard.press('ControlOrMeta+Enter')
  await expect(dialog).toBeHidden()
  await expect(toast(page, 'Nia Lee added')).toBeVisible()
  const sheet = page.getByRole('dialog', { name: /Nia Lee/ })
  await expect(sheet).toBeVisible()
  await expect(sheet.getByLabel('External ID 1', { exact: true })).toHaveValue('E1042')
  await expect(sheet.getByText(/Not linked yet/)).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(userRow(page, 'Nia Lee')).toContainText('Not linked yet')
})

test('deactivates and reactivates with a confirm; platform admin asks first', async ({ page }) => {
  await page.goto(`/settings/users/${BOB}`)
  const sheet = page.getByRole('dialog', { name: /Bob Chen/ })
  await expect(sheet.getByRole('switch', { name: 'Platform admin' })).not.toBeChecked()

  await sheet.getByRole('switch', { name: 'Platform admin' }).click()
  const grant = page.getByRole('alertdialog', { name: 'Make Bob Chen a platform admin?' })
  await grant.getByRole('button', { name: 'Make platform admin' }).click()
  await expect(toast(page, 'Bob Chen is now a platform admin')).toBeVisible()
  await expect(sheet.getByRole('switch', { name: 'Platform admin' })).toBeChecked()

  // Taking it away asks too (an Undo toast can't be reached over the sheet).
  await sheet.getByRole('switch', { name: 'Platform admin' }).click()
  await page
    .getByRole('alertdialog', { name: 'Remove Bob Chen’s platform admin rights?' })
    .getByRole('button', { name: 'Remove admin rights' })
    .click()
  await expect(sheet.getByRole('switch', { name: 'Platform admin' })).not.toBeChecked()

  await sheet.getByRole('button', { name: 'Deactivate…' }).click()
  const confirm = page.getByRole('alertdialog', { name: 'Deactivate Bob Chen?' })
  await expect(confirm).toContainText('signed out everywhere')
  await confirm.getByRole('button', { name: 'Deactivate' }).click()
  await expect(toast(page, 'Bob Chen deactivated')).toBeVisible()
  await expect(sheet.getByText('Deactivated', { exact: true }).first()).toBeVisible()
  await expect(sheet.getByText('Signed in on 1 browser.')).toHaveCount(0)

  await sheet.getByRole('button', { name: 'Reactivate…' }).click()
  await page
    .getByRole('alertdialog', { name: 'Reactivate Bob Chen?' })
    .getByRole('button', { name: 'Reactivate' })
    .click()
  await expect(toast(page, 'Bob Chen reactivated')).toBeVisible()
  await expect(sheet.getByRole('button', { name: 'Deactivate…' })).toBeVisible()
})

test('edits external IDs and unlinks the SSO account', async ({ page }) => {
  await page.goto(`/settings/users/${BOB}`)
  const sheet = page.getByRole('dialog', { name: /Bob Chen/ })
  await sheet.getByRole('button', { name: 'Add an external ID' }).click()
  await sheet.getByLabel('Kind of external ID 2').fill('gitlab')
  await sheet.getByLabel('External ID 2', { exact: true }).fill('bchen')
  await sheet.getByRole('button', { name: 'Save external IDs' }).click()
  await expect(toast(page, 'External IDs saved')).toBeVisible()
  await expect(sheet.getByRole('button', { name: 'Save external IDs' })).toHaveCount(0)

  await sheet.getByRole('button', { name: 'Unlink…' }).click()
  await page
    .getByRole('alertdialog', { name: 'Unlink this SSO account?' })
    .getByRole('button', { name: 'Unlink' })
    .click()
  await expect(toast(page, 'SSO account unlinked')).toBeVisible()
  await expect(sheet.getByText(/Not linked yet/)).toBeVisible()
})

test('you can’t deactivate yourself or change your own admin rights', async ({ page }) => {
  await page.goto(`/settings/users/${USERS.priya}`)
  const sheet = page.getByRole('dialog', { name: /Priya Natarajan/ })
  await expect(sheet.getByRole('switch', { name: 'Platform admin' })).toBeDisabled()
  await expect(
    sheet.getByText('You can’t change this for yourself.', { exact: false }),
  ).toBeVisible()
  await expect(sheet.getByText('You can’t deactivate yourself.')).toBeVisible()
  await expect(sheet.getByRole('button', { name: 'Deactivate…' })).toHaveCount(0)
})

test.describe('without platform admin rights', () => {
  test.use({ signedInAs: USERS.alice })

  test('the admin pages are a plain 404 and the section row has no admin pages', async ({
    page,
  }) => {
    await page.goto('/settings/users')
    await expect(page.getByRole('heading', { name: 'We couldn’t find that page' })).toBeVisible()
    await expect(page).toHaveTitle('Page not found · Soundings')
    await expect(page.getByRole('navigation', { name: 'Breadcrumb' })).not.toContainText('Users')

    await page.goto('/settings')
    await expect(page.getByRole('heading', { level: 1, name: 'Settings' })).toBeVisible()
    // Account, Notifications and API keys only: no admin sections, not even as disabled links.
    const nav = page.getByRole('navigation', { name: 'Settings sections' })
    await expect(nav.getByRole('link')).toHaveText(['Account', 'Notifications', 'API keys'])
  })
})

test('the command palette lists the admin pages for platform admins', async ({ page }) => {
  await page.goto('/settings')
  await expect(page.getByRole('heading', { level: 1, name: 'Settings' })).toBeVisible()
  await page.keyboard.press('ControlOrMeta+k')
  await page.keyboard.type('audit log')
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(/\/settings\/audit$/)
  await expect(page.getByRole('heading', { level: 2, name: 'Audit log' })).toBeVisible()
  // j/k move between rows, Enter opens one.
  await openUsers(page)
  const alice = userRow(page, 'Alice Anders').getByRole('link')
  await expect(alice).toBeVisible()
  await page.keyboard.press('j')
  await expect(alice).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('dialog', { name: /Alice Anders/ })).toBeVisible()
})

test('the user sheet opens on itself and closes back to the row', async ({ page }) => {
  await openUsers(page)
  const bob = userRow(page, 'Bob Chen').getByRole('link')
  await bob.focus()
  await page.keyboard.press('Enter')
  const sheet = page.getByRole('dialog', { name: /Bob Chen/ })
  // Focus on the sheet, never on the Name field with its text selected.
  await expect(sheet).toBeFocused()
  await expect(sheet.getByRole('textbox', { name: 'Name' })).not.toBeFocused()
  await page.keyboard.press('Escape')
  await expect(sheet).toHaveCount(0)
  await expect(bob).toBeFocused()

  // Same with the close button, and from a cached user.
  await page.keyboard.press('Enter')
  await expect(sheet).toBeFocused()
  await sheet.getByRole('button', { name: 'Close' }).click()
  await expect(bob).toBeFocused()
})
