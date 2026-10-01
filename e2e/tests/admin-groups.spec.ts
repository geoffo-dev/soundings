import type { Page } from '@playwright/test'

import { createTeamProject, uniqueSuffix, userOf } from './support/api'
import { expect, settled, signIn, test, toast } from './support/fixtures'
import { requireSso, ssoSignInAs } from './support/sso'

/**
 * Admin settings → Groups (contract-phase2 §3.5–3.7, §3.12) against the real stack, as
 * Alice (platform admin): a mapping typed any way is stored normalised, the "Test
 * mapping" box reads the saved mappings, manual members are added and removed with
 * Undo, and a group's project role reaches its members (any sign-in method). Every
 * group and value is run-unique, so the seeded groups and other specs never match.
 * Test plan: AG-*.
 */

const testResult = (scope: Page | ReturnType<Page['getByRole']>) =>
  scope.getByRole('region', { name: 'Test result' })

async function openGroup(page: Page, id: string, name: string) {
  await page.goto(`/settings/groups/${id}`)
  await expect(page.getByRole('heading', { level: 2, name })).toBeVisible()
  await settled(page)
}

test('AG-01: creates a group with a normalised mapping, then changes it', async ({ page, api }) => {
  const alice = await api('alice')
  const run = uniqueSuffix()
  const name = `Board ${run}`
  await signIn(page, 'alice')
  await page.goto('/settings/groups')
  await page.getByRole('button', { name: 'New group' }).click()
  const dialog = page.getByRole('dialog', { name: 'New group' })
  await dialog.getByRole('textbox', { name: 'Name' }).fill(name)
  const values = dialog.getByRole('textbox', { name: 'Identity provider groups' })
  await values.fill(` /Leadership/${run.toUpperCase()}/Board/ `)
  await expect(dialog.locator('code', { hasText: `leadership/${run}/board` })).toBeVisible()
  await values.press('Enter')
  await dialog.getByRole('radio', { name: /Additive/ }).click()
  await dialog.getByRole('button', { name: /^Create group/ }).click()
  await expect(toast(page, `${name} created`)).toBeVisible()
  await expect(page.getByRole('heading', { level: 2, name })).toBeVisible()
  const group = await alice.groupByName(name)
  alice.createdGroups.push(group.id)
  expect(group).toMatchObject({ sync_mode: 'additive', idp_values: [`leadership/${run}/board`] })

  // A second value, managed now; saved as one change.
  const editor = page.getByRole('textbox', { name: 'Identity provider groups' })
  await editor.fill(`/Leadership/${run}/Exec`)
  await editor.press('Enter')
  await page.getByRole('radio', { name: /Managed/ }).click()
  await page.getByRole('button', { name: 'Save mapping' }).click()
  await expect(toast(page, 'Mapping saved')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Save mapping' })).toHaveCount(0)
  expect(await alice.group(group.id)).toMatchObject({
    sync_mode: 'managed',
    idp_values: [`leadership/${run}/board`, `leadership/${run}/exec`],
  })
  const [change] = await alice.audit({ action: 'group.mapping_replace', target_id: group.id })
  expect(change?.details).toMatchObject({ from_sync_mode: 'additive', sync_mode: 'managed' })

  // In the list: managed, its values, no members yet.
  await page.goto(`/settings/groups?q=${run}`)
  const row = page.getByRole('table', { name: 'Groups' }).getByRole('row').filter({ hasText: name })
  await expect(row).toContainText('Managed:')
  await expect(row).toContainText(`leadership/${run}/board`)
})

test('AG-02: “Test mapping” shows who joins and the roles that would follow', async ({
  page,
  api,
}) => {
  const alice = await api('alice')
  const run = uniqueSuffix()
  const group = await alice.createGroup({
    name: `Pilots ${run}`,
    idp_values: [`/e2e/${run}/pilots`],
  })
  const project = await createTeamProject(alice, 'Mapped', {})
  await alice.grantGroup(project.slug, group.id, 'member')

  await signIn(page, 'alice')
  await page.goto('/settings/groups')
  await page.getByRole('button', { name: 'Test mapping' }).click()
  const sheet = page.getByRole('dialog', { name: 'Test mapping' })
  const claims = sheet.getByRole('textbox', { name: 'Claims' })
  await claims.fill('{ "groups": [ ')
  await sheet.getByRole('button', { name: 'Test mapping' }).click()
  await expect(
    sheet.getByText('That isn’t valid JSON. Check for missing quotes or commas.'),
  ).toBeVisible()

  // A decoded ID token: the full path in another case, a value nobody maps, junk.
  await claims.fill(
    JSON.stringify({
      sub: 'k-1',
      groups: [`/E2E/${run}/Pilots`, `/e2e/${run}/unmapped`, 42, '/'],
    }),
  )
  await sheet.getByRole('button', { name: 'Test mapping' }).click()
  const result = testResult(sheet)
  await expect(result.getByText('Found 2 values in “groups”')).toBeVisible()
  await expect(result.getByText('2 entries were ignored (not text, or empty).')).toBeVisible()
  await expect(result.getByRole('list', { name: 'Values found' })).toContainText(
    `e2e/${run}/pilots`,
  )
  const rows = result.getByRole('list', { name: 'Groups' }).getByRole('listitem')
  await expect(rows).toHaveCount(1)
  await expect(rows.first()).toContainText('Joins')
  await expect(rows.first()).toContainText(group.name)
  await expect(
    result
      .getByRole('list', { name: 'Project roles after signing in' })
      .getByRole('listitem')
      .filter({ hasText: project.name }),
  ).toContainText(`via ${group.name}`)

  // Nothing was stored: no member, no audit entry for a test.
  expect((await alice.group(group.id)).member_count).toBe(0)
  expect(await alice.audit({ target_id: group.id, action: 'group.member_add' })).toEqual([])
})

test('AG-03: a manual member gets the group’s project role, and leaves it with the group', async ({
  page,
  api,
}) => {
  const alice = await api('alice')
  const run = uniqueSuffix()
  const group = await alice.createGroup({ name: `Reviewers ${run}` })
  const project = await createTeamProject(alice, 'Grants', {})
  const kenji = await userOf(alice.baseURL, 'kenji')

  // Add Kenji by hand on the group page (with Undo after a removal).
  await signIn(page, 'alice')
  await openGroup(page, group.id, group.name)
  await page.getByRole('combobox', { name: 'Add a person by hand' }).click()
  await page.getByPlaceholder('Search by name or email…').fill('kenji')
  await page.getByRole('option', { name: /Kenji Watanabe/ }).click()
  await page.getByRole('button', { name: 'Add', exact: true }).click()
  await expect(toast(page, `Kenji Watanabe added to ${group.name}`)).toBeVisible()
  const members = page.getByRole('list', { name: 'Members' })
  const kenjiRow = members.getByRole('listitem').filter({ hasText: 'Kenji Watanabe' })
  await expect(kenjiRow).toContainText('Manual')
  await kenjiRow.getByRole('button', { name: 'Remove Kenji Watanabe' }).click()
  await expect(kenjiRow).toHaveCount(0)
  await toast(page, `Kenji Watanabe removed from ${group.name}`)
    .getByRole('button', { name: 'Undo' })
    .click()
  await expect(members.getByRole('listitem').filter({ hasText: 'Kenji Watanabe' })).toBeVisible()

  // The project's Members tab: give the group a role; Kenji has access through it.
  await page.goto(`/p/${project.slug}/settings?tab=members`)
  await settled(page)
  await page.getByRole('radio', { name: 'Group' }).click()
  await page.getByRole('combobox', { name: 'Add a group' }).click()
  await page.getByPlaceholder('Search groups by name…').fill(run)
  await page.getByRole('option', { name: new RegExp(group.name) }).click()
  await page.getByRole('combobox', { name: 'Role', exact: true }).click()
  await page.getByRole('option', { name: 'Viewer' }).click()
  await page.getByRole('button', { name: 'Add', exact: true }).click()
  await expect(toast(page, `${group.name} added as viewer`)).toBeVisible()
  // "Everyone with access" is folded away while groups have a role.
  // Unfolded already when nobody has a direct role (it is then the only list of people).
  const showAccess = page.getByRole('button', { name: /^Everyone with access/ })
  await expect(showAccess).toBeVisible()
  if ((await showAccess.getAttribute('aria-expanded')) !== 'true') await showAccess.click()
  const access = page.getByRole('list', { name: 'Everyone with access' })
  await expect(access.getByRole('listitem').filter({ hasText: 'Kenji Watanabe' })).toContainText(
    `via ${group.name}`,
  )

  // Roles are evaluated live: Kenji sees it now, and not once he leaves the group.
  const kenjiApi = await api('kenji')
  expect((await kenjiApi.raw('GET', `/projects/${project.slug}`)).status()).toBe(200)
  await alice.send('DELETE', `/admin/groups/${group.id}/members/${kenji.id}`, undefined, 204)
  expect((await kenjiApi.raw('GET', `/projects/${project.slug}`)).status()).toBe(404)
})

test.describe('with SSO', { tag: '@sso' }, () => {
  test('AG-04: “Test mapping” for a synced member shows them leaving a managed group, staying in an additive one', async ({
    page,
    browser,
    api,
  }) => {
    await requireSso()
    const alice = await api('alice')
    const run = uniqueSuffix()
    const managed = await alice.createGroup({
      name: `Tools ${run}`,
      idp_values: ['/tools/members'],
    })
    const additive = await alice.createGroup({
      name: `Tools archive ${run}`,
      sync_mode: 'additive',
      idp_values: ['/tools/members'],
    })
    // Dave signs in with Keycloak: synced into both.
    const context = await browser.newContext()
    await ssoSignInAs(await context.newPage(), 'dave')
    await context.close()

    await signIn(page, 'alice')
    await openGroup(page, managed.id, managed.name)
    const members = page.getByRole('list', { name: 'Members' })
    const daveRow = members.getByRole('listitem').filter({ hasText: 'Dave Davies' })
    await expect(daveRow).toContainText('Synced')
    // Synced rows are read-only (sync owns them).
    await expect(daveRow.getByRole('button', { name: 'Remove Dave Davies' })).toHaveCount(0)

    // Test mapping opens as a sheet from the identity-provider section.
    await page.getByRole('button', { name: 'Test mapping' }).click()
    const panel = page.getByRole('dialog', { name: 'Test mapping' })
    await panel.getByRole('textbox', { name: 'Claims' }).fill('{ "groups": ["/viewers"] }')
    await panel.getByRole('combobox', { name: /Person/ }).click()
    await page.getByPlaceholder('Search by name or email…').fill('dave')
    await page.getByRole('option', { name: /Dave Davies/ }).click()
    await panel.getByRole('button', { name: 'Test mapping' }).click()
    const rows = testResult(panel).getByRole('list', { name: 'Groups' }).getByRole('listitem')
    const row = (name: string) => rows.filter({ hasText: name })
    await expect(row(managed.name)).toContainText('Leaves')
    await expect(row(managed.name)).toContainText('This group')
    await expect(row(managed.name)).toContainText(
      'No longer matches, so they leave this managed group.',
    )
    await expect(row(additive.name)).toContainText('Stays')
  })
})
