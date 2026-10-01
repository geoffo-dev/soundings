import type { Page } from '@playwright/test'

import { expect, seriousViolations, test } from './support'

/**
 * Project settings → Members with groups (contract-phase2 §3.7): people with a
 * direct role, groups with a role, and everyone with access and why. Alice is
 * the only direct admin of Internal Tools; the group "Tools members" (6 people,
 * Kofi Boateng and Lena Novak only through it) has the member role there.
 */

const toast = (page: Page, text: string | RegExp) =>
  page.locator('[data-sonner-toast]', { hasText: text })

async function openMembers(page: Page, slug = 'internal-tools') {
  await page.goto(`/p/${slug}/settings?tab=members`)
  await expect(page.getByRole('heading', { level: 1, name: 'Project settings' })).toBeVisible()
  await expect(page.locator('[data-slot="skeleton"]')).toHaveCount(0)
}

const groups = (page: Page) => page.getByRole('list', { name: /^\d+ groups?$/ })
const groupRow = (page: Page, name: string) =>
  groups(page).getByRole('listitem').filter({ hasText: name })
const access = (page: Page) => page.getByRole('list', { name: 'Everyone with access' })
const accessRow = (page: Page, name: string) =>
  access(page).getByRole('listitem').filter({ hasText: name })

test('shows who has access and why', async ({ page }) => {
  await openMembers(page)
  await expect(groupRow(page, 'Tools members')).toContainText('Group · 6 people')
  await expect(page.getByText('7 people, each with the highest of their roles')).toBeVisible()
  await expect(accessRow(page, 'Kofi Boateng')).toContainText('Member')
  await expect(accessRow(page, 'Kofi Boateng')).toContainText('via Tools members')
  await expect(accessRow(page, 'Alice Anders')).toContainText('Direct · via Tools members (member)')
  await expect(accessRow(page, 'Grace Kim')).toContainText('Viewer')
  await expect(
    page.getByText('Platform admins can see and manage every project without a role here.'),
  ).toBeVisible()
})

test('adds a group with a role, changes it and removes it, with Undo', async ({ page }) => {
  await openMembers(page)
  await page.getByRole('radio', { name: 'Group' }).click()
  const picker = page.getByRole('combobox', { name: 'Add a group' })
  await expect(picker).toBeVisible()
  await picker.click()
  // Groups that already have a role are listed but can't be picked.
  await expect(page.getByRole('option', { name: /Tools members/ })).toHaveAttribute(
    'aria-disabled',
    'true',
  )
  await page.getByPlaceholder('Search groups by name…').fill('contr')
  await page.getByRole('option', { name: /Contractors/ }).click()
  await page.getByRole('combobox', { name: 'Role', exact: true }).click()
  await page.getByRole('option', { name: 'Viewer' }).click()
  await page.getByRole('button', { name: 'Add', exact: true }).click()
  await expect(toast(page, 'Contractors added as viewer')).toBeVisible()
  await expect(groupRow(page, 'Contractors')).toContainText('Group · 0 people')
  await expect(picker).toBeFocused()

  await groupRow(page, 'Contractors')
    .getByRole('combobox', { name: 'Role of the group Contractors' })
    .click()
  await page.getByRole('option', { name: 'Member' }).click()
  await expect(toast(page, 'Everyone in Contractors is now a member')).toBeVisible()
  await toast(page, 'Everyone in Contractors is now a member')
    .getByRole('button', { name: 'Undo' })
    .click()
  await expect(
    groupRow(page, 'Contractors').getByRole('combobox', { name: /Role of the group/ }),
  ).toHaveText('Viewer')

  await groupRow(page, 'Tools members')
    .getByRole('button', { name: 'Remove the group Tools members' })
    .click()
  await expect(groupRow(page, 'Tools members')).toHaveCount(0)
  // Access through the group goes with it.
  await expect(accessRow(page, 'Kofi Boateng')).toHaveCount(0)
  await toast(page, 'Tools members removed').getByRole('button', { name: 'Undo' }).click()
  await expect(groupRow(page, 'Tools members')).toBeVisible()
  await expect(accessRow(page, 'Kofi Boateng')).toBeVisible()
})

test('the last admin is protected, whether direct or through a group', async ({ page }) => {
  await openMembers(page)
  const people = page.getByRole('list', { name: /^\d+ members$/ })
  const alice = people.getByRole('listitem').filter({ hasText: 'Alice Anders' })
  await expect(alice.getByRole('combobox', { name: 'Role of Alice Anders' })).toBeDisabled()

  // Make the group an admin source too: then Alice's own role can change…
  await groupRow(page, 'Tools members')
    .getByRole('combobox', { name: 'Role of the group Tools members' })
    .click()
  await page.getByRole('option', { name: 'Admin' }).click()
  await expect(toast(page, 'Everyone in Tools members is now an admin')).toBeVisible()
  await expect(alice.getByRole('combobox', { name: 'Role of Alice Anders' })).toBeEnabled()
  await alice.getByRole('combobox', { name: 'Role of Alice Anders' }).click()
  await page.getByRole('option', { name: 'Member' }).click()
  await expect(toast(page, 'Alice Anders is now a member')).toBeVisible()

  // …and now the group is the only way anyone is an admin here.
  await expect(
    groupRow(page, 'Tools members').getByRole('button', { name: 'Remove the group Tools members' }),
  ).toBeDisabled()
  await expect(accessRow(page, 'Alice Anders')).toContainText('Direct (member) · via Tools members')
})

test('members see the same lists, read-only', async ({ page }) => {
  // Alice is a member (not an admin) of Customer Innovation.
  await openMembers(page, 'customer-innovation')
  await expect(page.getByRole('combobox', { name: 'Add a person' })).toHaveCount(0)
  await expect(groupRow(page, 'Innovation admins')).toContainText('Admin')
  await expect(groupRow(page, 'Innovation members')).toContainText('Member')
  await expect(page.getByRole('combobox', { name: /Role of/ })).toHaveCount(0)
  await expect(
    page.getByText('Everyone signed in can view this project, because it is internal.'),
  ).toBeVisible()
  // Nine people: the list can be searched.
  await page.getByRole('textbox', { name: 'Find someone with access' }).fill('kofi')
  await expect(access(page).getByRole('listitem')).toHaveCount(1)
  await expect(accessRow(page, 'Kofi Boateng')).toContainText('via Innovation members')
  await page.getByRole('textbox', { name: 'Find someone with access' }).fill('nobody')
  await expect(page.getByText('Nobody with access matches “nobody”.')).toBeVisible()
})

test('a list that can’t load says so and offers to try again', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('soundings-mock-fail', '/groups'))
  await page.goto('/p/internal-tools/settings?tab=members')
  // After the client's two retries.
  await expect(page.getByRole('alert')).toContainText('We couldn’t load groups', {
    timeout: 15_000,
  })
  await page.evaluate(() => localStorage.removeItem('soundings-mock-fail'))
  await page.getByRole('button', { name: 'Try again' }).click()
  await expect(groupRow(page, 'Tools members')).toBeVisible()
})

for (const colorScheme of ['light', 'dark'] as const) {
  test(`members with groups have no serious accessibility violations (${colorScheme})`, async ({
    page,
  }) => {
    await page.emulateMedia({ colorScheme })
    for (const slug of ['internal-tools', 'customer-innovation']) {
      await openMembers(page, slug)
      // Alice manages Internal Tools (the add form, on Group) and only views the other.
      if (slug === 'internal-tools') await page.getByRole('radio', { name: 'Group' }).click()
      expect(await seriousViolations(page), slug).toEqual([])
    }
  })
}

test.describe('on a phone (390px)', () => {
  test.use({ viewport: { width: 390, height: 844 } })

  test('the members tab fits, with roles and their sources under each name', async ({ page }) => {
    await openMembers(page)
    await page.getByRole('radio', { name: 'Group' }).click()
    const overflow = await page.evaluate(() => {
      const main = document.querySelector('main')
      return main ? main.scrollWidth - main.clientWidth : 0
    })
    expect(overflow).toBe(0)
    await expect(accessRow(page, 'Kofi Boateng')).toContainText('via Tools members')
  })
})
