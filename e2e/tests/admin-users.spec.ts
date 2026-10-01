import { request, type Page } from '@playwright/test'

import { issuer } from '../scripts/keycloak.ts'
import { uniqueSuffix, userOf } from './support/api'
import { expect, settled, signIn, test, toast } from './support/fixtures'
import { requireSso, sidebarProjects, ssoSignInAs } from './support/sso'

/**
 * Admin settings → Users (contract-phase2 §3.4) against the real stack, as Alice
 * (platform admin in the seed). With SSO: a pre-created user is linked to their Keycloak
 * account at the first sign-in by external ID, gets access from their Keycloak group,
 * and an unlink ends their SSO session. Test plan: AU-*.
 */

const usersTable = (page: Page) => page.getByRole('table', { name: 'Users' })
const userRow = (page: Page, name: string) =>
  usersTable(page).getByRole('row').filter({ hasText: name })
const sheetOf = (page: Page, name: string) => page.getByRole('dialog', { name: new RegExp(name) })

async function openUsers(page: Page, query = '') {
  await page.goto(`/settings/users${query}`)
  await expect(page.getByRole('heading', { level: 2, name: 'Users' })).toBeVisible()
  await settled(page)
}

test('AU-01: lists everyone, searches and filters through the URL', async ({ page }) => {
  await signIn(page, 'alice')
  await openUsers(page)
  await expect(page.getByRole('navigation', { name: 'Settings sections' })).toBeVisible()
  await expect(userRow(page, 'Alice Anders')).toContainText('Platform admin')

  await page.getByRole('searchbox', { name: 'Search users' }).fill('carol')
  await expect(page).toHaveURL(/\?q=carol$/)
  await expect(usersTable(page).getByRole('row')).toHaveCount(2) // header + Carol
  await expect(userRow(page, 'Carol Chen')).toContainText('carol@example.com')

  await page.getByRole('searchbox', { name: 'Search users' }).fill('')
  await page.getByRole('button', { name: 'Platform admins' }).click()
  await expect(page).toHaveURL(/admins=1/)
  await expect(userRow(page, 'Alice Anders')).toBeVisible()
  await expect(userRow(page, 'Bob Brown')).toHaveCount(0)
})

test('AU-02: deactivating ends the person’s sessions at once; reactivating lets them back', async ({
  page,
  api,
  baseURL,
}) => {
  const alice = await api('alice')
  const run = uniqueSuffix()
  const temp = await alice.createUser({
    email: `temp-${run}@example.com`,
    display_name: `Temp Person ${run}`,
  })
  // They are signed in somewhere (dev login, their own cookie jar).
  const theirs = await request.newContext({ baseURL })
  try {
    await theirs.post('/api/v1/auth/dev/login', { data: { user_id: temp.id } })
    expect((await theirs.get('/api/v1/auth/me')).status()).toBe(200)

    await signIn(page, 'alice')
    await page.goto(`/settings/users/${temp.id}`)
    const sheet = sheetOf(page, temp.display_name)
    await expect(sheet.getByText('Signed in on 1 browser.')).toBeVisible()
    await sheet.getByRole('button', { name: 'Deactivate…' }).click()
    const confirm = page.getByRole('alertdialog', { name: `Deactivate ${temp.display_name}?` })
    await expect(confirm).toContainText('signed out everywhere')
    await confirm.getByRole('button', { name: 'Deactivate' }).click()
    await expect(toast(page, `${temp.display_name} deactivated`)).toBeVisible()
    expect((await theirs.get('/api/v1/auth/me')).status()).toBe(401)
    const devLogin = await theirs.post('/api/v1/auth/dev/login', { data: { user_id: temp.id } })
    expect(devLogin.status()).not.toBe(200)

    await sheet.getByRole('button', { name: 'Reactivate…' }).click()
    await page
      .getByRole('alertdialog', { name: `Reactivate ${temp.display_name}?` })
      .getByRole('button', { name: 'Reactivate' })
      .click()
    await expect(toast(page, `${temp.display_name} reactivated`)).toBeVisible()
    const again = await theirs.post('/api/v1/auth/dev/login', { data: { user_id: temp.id } })
    expect(again.status()).toBe(200)
  } finally {
    await theirs.dispose()
  }
})

test('AU-03: you can’t lock yourself out; non-admins get a plain 404', async ({ page, api }) => {
  const alice = await userOf((await api('alice')).baseURL, 'alice')
  await signIn(page, 'alice')
  await page.goto(`/settings/users/${alice.id}`)
  const sheet = sheetOf(page, 'Alice Anders')
  await expect(sheet.getByRole('switch', { name: 'Platform admin' })).toBeDisabled()
  await expect(sheet.getByText('You can’t deactivate yourself.')).toBeVisible()
  await expect(sheet.getByRole('button', { name: 'Deactivate…' })).toHaveCount(0)

  const bob = await api('bob')
  expect((await bob.raw('GET', '/admin/users')).status()).toBe(403)
  await signIn(page, 'bob')
  await page.goto('/settings/users')
  await expect(page.getByRole('heading', { name: 'We couldn’t find that page' })).toBeVisible()
  // Phase 3: everyone has Account and Notifications; the admin sections stay hidden.
  await page.goto('/settings')
  await expect(
    page.getByRole('navigation', { name: 'Settings sections' }).getByRole('link'),
  ).toHaveText(['Account', 'Notifications'])
})

test.describe('pre-created users and SSO', { tag: '@sso' }, () => {
  test.describe.configure({ mode: 'serial' })

  test('AU-04: a pre-created user is linked at their first SSO sign-in by external ID, with access from their Keycloak group; unlinking ends their SSO session', async ({
    page,
    browser,
    api,
  }) => {
    await requireSso()
    const alice = await api('alice')
    // grace's Keycloak email (grace@corp.example) is nobody's: only E2001 can match.
    await signIn(page, 'alice')
    await openUsers(page)
    await page.getByRole('button', { name: 'Add user' }).click()
    const dialog = page.getByRole('dialog', { name: 'Add user' })
    await dialog.getByRole('textbox', { name: 'Email' }).fill('grace.gale@example.com')
    await dialog.getByRole('textbox', { name: 'Name' }).fill('Grace Gale')
    await expect(dialog.getByLabel('Kind of external ID 1')).toHaveValue('employee_no')
    await dialog.getByLabel('External ID 1', { exact: true }).fill('e2001') // any case
    await dialog.getByRole('button', { name: /^Add user/ }).click()
    await expect(toast(page, 'Grace Gale added')).toBeVisible()
    const sheet = sheetOf(page, 'Grace Gale')
    await expect(sheet.getByText(/Not linked yet/)).toBeVisible()
    const grace = await alice.adminUserByEmail('grace.gale@example.com')
    if (!grace) throw new Error('Grace was not created')

    // Grace signs in with Keycloak: the pre-created account, its name, and Internal
    // Tools through the seeded "Tools team" group (mapped to /tools/members).
    const context = await browser.newContext()
    const gracePage = await context.newPage()
    await ssoSignInAs(gracePage, 'grace', 'Grace Gale')
    await expect(
      sidebarProjects(gracePage).getByRole('link', { name: 'Internal Tools' }),
    ).toBeVisible()
    const [link] = await alice.audit({ action: 'user.identity_link', target_id: grace.id })
    expect(link?.details).toMatchObject({ matched_by: 'external_id', issuer: issuer() })

    // The admin sees the linked account, the synced group and where access comes from.
    await page.reload()
    await expect(sheet.getByText(issuer())).toBeVisible()
    const groups = sheet.getByRole('region', { name: 'Groups' })
    await expect(groups.getByRole('listitem').filter({ hasText: 'Tools team' })).toContainText(
      'Synced',
    )
    const projects = sheet.getByRole('region', { name: 'Project access' })
    await expect(
      projects.getByRole('listitem').filter({ hasText: 'Internal Tools' }),
    ).toContainText('via Tools team')
    await expect(userRow(page, 'Grace Gale')).toContainText('Linked')

    // Unlink: her SSO session ends now; her next sign-in links her again.
    await sheet.getByRole('button', { name: 'Unlink…' }).click()
    await page
      .getByRole('alertdialog', { name: 'Unlink this SSO account?' })
      .getByRole('button', { name: 'Unlink' })
      .click()
    await expect(toast(page, 'SSO account unlinked')).toBeVisible()
    await expect(sheet.getByText(/Not linked yet/)).toBeVisible()
    expect((await gracePage.request.get('/api/v1/auth/me')).status()).toBe(401)
    await gracePage.reload()
    await expect(gracePage).toHaveURL(/\/login\?/)

    await context.clearCookies() // and out of Keycloak, so it asks for the password
    await ssoSignInAs(gracePage, 'grace', 'Grace Gale')
    const links = await alice.audit({ action: 'user.identity_link', target_id: grace.id })
    expect(links).toHaveLength(2)
    await context.close()
  })
})
