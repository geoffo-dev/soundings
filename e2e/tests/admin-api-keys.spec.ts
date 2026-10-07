import type { Page } from '@playwright/test'

import { Api, createTeamProject, uniqueSuffix, type CurrentUser } from './support/api'
import { expect, settled, signIn, test, toast } from './support/fixtures'
import { expectRefusedKey, KeyClient } from './support/mcp'

/**
 * Admin settings → API keys against the real stack, as Alice (platform admin in the
 * seed; contract-phase5 §2, §3.1, §3.10): every key that isn't revoked, search by name,
 * owner or a pasted whole key (cut to its prefix in the browser), revoking anyone's key
 * (it stops at once), the link from a user's admin page, "Sign out everywhere" leaving
 * keys working, and deactivation revoking them. Keys of people other specs use are
 * created per run with unique names; the sign-out and deactivation tests use people of
 * their own. Test plan: AAK-*.
 */

const baseURL = () => test.info().project.use.baseURL ?? ''
const table = (page: Page) => page.getByRole('table', { name: 'API keys' })
const keyRow = (page: Page, name: string) => table(page).getByRole('row').filter({ hasText: name })
const search = (page: Page) => page.getByRole('searchbox', { name: 'Search API keys' })

async function openAdminKeys(page: Page, query = '') {
  // The Phase 5 address still works: since Phase 7 it is "Everyone's keys" on Settings →
  // API keys, with its filters.
  await page.goto(`/settings/all-api-keys${query}`)
  await expect(page.getByRole('heading', { level: 2, name: 'API keys' })).toBeVisible()
  await expect(page.getByRole('radio', { name: 'Everyone’s keys' })).toBeChecked()
  await settled(page)
}

/** A person of this test's own (dev login), so ending their sessions disturbs no one. */
async function newPerson(alice: Api, label: string): Promise<Api> {
  const run = uniqueSuffix()
  const user = await alice.createUser({
    email: `${label.toLowerCase()}-${run}@example.com`,
    display_name: `${label} ${run}`,
  })
  return Api.asUser(baseURL(), user as unknown as CurrentUser)
}

test('AAK-01: lists everyone’s keys; a pasted whole key is searched by its prefix only', async ({
  page,
  api,
}) => {
  const alice = await api('alice')
  const run = uniqueSuffix()
  const bob = await api('bob')
  const carol = await api('carol')
  const project = await createTeamProject(alice, 'Admin keys', { carol: 'member' })
  const bobKey = await bob.createApiKey({ name: `Jira sync ${run}`, scopes: ['read'] })
  const carolKey = await carol.createApiKey({
    name: `Claude ${run}`,
    scopes: ['read', 'mcp'],
    project_ids: [project.id],
  })
  try {
    await signIn(page, 'alice')
    await openAdminKeys(page)
    await search(page).fill(run)
    await expect(page).toHaveURL(new RegExp(`q=${run}`))
    await expect(table(page).getByRole('row')).toHaveCount(3) // header + 2
    await expect(page.getByText('2 keys', { exact: true })).toBeVisible()
    const bobRow = keyRow(page, `Jira sync ${run}`)
    await expect(bobRow).toContainText('Bob Brown')
    await expect(bobRow).toContainText(bobKey.key.prefix)
    await expect(bobRow).toContainText('All projects')
    await expect(bobRow).toContainText('Never used')
    const carolRow = keyRow(page, `Claude ${run}`)
    await expect(carolRow).toContainText('Carol Chen')
    await expect(carolRow).toContainText('MCP')
    await expect(carolRow).toContainText(project.name)

    // Someone reports a leaked key: paste it whole. Only the prefix goes anywhere.
    const requests: string[] = []
    page.on('request', (request) => requests.push(request.url()))
    await search(page).fill(`Bearer ${bobKey.secret}`)
    await expect(page).toHaveURL(new RegExp(`q=${bobKey.key.prefix}(&|$)`))
    await expect(search(page)).toHaveValue(bobKey.key.prefix)
    await expect(
      page.getByRole('status').filter({ hasText: 'You pasted a whole key' }),
    ).toBeVisible()
    await expect(table(page).getByRole('row')).toHaveCount(2)
    await expect(keyRow(page, `Jira sync ${run}`)).toBeVisible()
    const secretPart = bobKey.secret.slice(17)
    expect(page.url()).not.toContain(secretPart)
    expect(requests.some((url) => url.includes(secretPart))).toBe(false)
    // The API finds it by prefix or lookup id, exactly; a near miss finds nothing.
    const byLookup = await alice.adminApiKeys({ q: bobKey.key.prefix.slice(4) })
    expect(byLookup.items.map((key) => key.id)).toEqual([bobKey.key.id])
    expect((await alice.adminApiKeys({ q: bobKey.key.prefix.slice(0, -1) })).items).toEqual([])

    // The owner links to their admin page.
    await search(page).fill(run)
    await keyRow(page, `Claude ${run}`).getByRole('link', { name: 'Carol Chen' }).click()
    await expect(page.getByRole('dialog', { name: /Carol Chen/ })).toBeVisible()
  } finally {
    await bob.revokeApiKey(bobKey.key.id)
    await carol.revokeApiKey(carolKey.key.id)
  }
})

test('AAK-02: an admin revokes someone’s key after a confirm; it stops at once and is audited', async ({
  page,
  api,
}) => {
  const alice = await api('alice')
  const bob = await api('bob')
  const name = `Spreadsheet ${uniqueSuffix()}`
  const key = await bob.createApiKey({ name, scopes: ['read', 'mcp'] })
  const client = await KeyClient.open(baseURL(), key.secret)
  try {
    expect((await client.rest('GET', '/auth/me')).status()).toBe(200)
    await signIn(page, 'alice')
    await openAdminKeys(page, `?q=${encodeURIComponent(name)}`)
    await keyRow(page, name)
      .getByRole('button', { name: `Revoke Bob Brown’s key ${name}` })
      .click()
    const confirm = page.getByRole('alertdialog', { name: `Revoke Bob Brown’s key “${name}”?` })
    await expect(confirm).toContainText('stops working immediately')
    await expect(confirm).toContainText(key.key.prefix)
    await confirm.getByRole('button', { name: 'Revoke key' }).click()
    await expect(toast(page, `Bob Brown’s key “${name}” revoked`)).toBeVisible()
    await expect(page.getByRole('heading', { name: 'No keys match' })).toBeVisible()

    await expectRefusedKey(await client.rest('GET', '/auth/me'))
    await expectRefusedKey(await client.rpc('tools/list'))
    expect((await bob.apiKeys()).items.map((item) => item.id)).not.toContain(key.key.id)
    const entry = (await alice.audit({ action: 'api_key.revoke', target_id: bob.me.id })).find(
      (item) => item.details.key_id === key.key.id,
    )
    expect(entry?.actor?.display_name).toBe('Alice Anders')
    expect(entry?.details.rule).toBe('api_key.manage_any')
    await page.goto(`/settings/audit?target=user:${bob.me.id}&action=api_keys`)
    await expect(
      page
        .getByRole('region', { name: 'Audit entries' })
        .getByText(`Alice Anders revoked API key ${key.key.prefix} of Bob Brown`),
    ).toBeVisible()
    // Idempotent.
    expect((await alice.raw('DELETE', `/admin/api-keys/${key.key.id}`)).status()).toBe(204)
  } finally {
    await client.dispose()
  }
})

test('AAK-03: “Sign out everywhere” ends sessions but not keys, and links to that person’s keys', async ({
  page,
  api,
}) => {
  const alice = await api('alice')
  const person = await newPerson(alice, 'Signout')
  const key = await person.createApiKey({ name: 'Nightly export', scopes: ['read'] })
  const client = await KeyClient.open(baseURL(), key.secret)
  try {
    await signIn(page, 'alice')
    await page.goto(`/settings/users/${person.me.id}`)
    const sheet = page.getByRole('dialog', { name: new RegExp(person.me.display_name) })
    await sheet.getByRole('button', { name: 'Sign out everywhere' }).click()
    const confirm = page.getByRole('alertdialog', {
      name: `Sign ${person.me.display_name} out everywhere?`,
    })
    await expect(confirm).toContainText('API keys keep working')
    await confirm.getByRole('button', { name: 'Sign out everywhere' }).click()
    // The confirmation closes once the sessions are gone (while it is open the sheet is
    // hidden from the accessibility tree, so its button "isn't there" before then too).
    await expect(confirm).toBeHidden()
    await expect(sheet.getByText('Not signed in anywhere.')).toBeVisible()
    await expect(sheet.getByRole('button', { name: 'Sign out everywhere' })).toHaveCount(0)
    // The session is gone; the key still works.
    expect((await person.raw('GET', '/auth/me')).status()).toBe(401)
    expect((await client.rest('GET', '/auth/me')).status()).toBe(200)

    // The sheet's "API keys" link filters the admin list by owner.
    await sheet.getByRole('link', { name: 'API keys' }).click()
    await expect(page).toHaveURL(
      new RegExp(`/settings/api-keys\\?everyone=1&user_id=${person.me.id}$`),
    )
    await expect(page.getByText('1 key', { exact: true })).toBeVisible()
    await expect(keyRow(page, 'Nightly export')).toContainText(person.me.display_name)
    await expect(page.locator('[data-slot="filter-value-chip"]')).toContainText(
      person.me.display_name,
    )
  } finally {
    await client.dispose()
    await person.dispose()
  }
})

test('AAK-04: deactivating someone revokes their keys for good', async ({ page, api }) => {
  // Contract-phase5 §2: `update_admin_user` with is_active false revokes every key of
  // the user (audited, reason deactivated): a reactivated account doesn't get it back.
  const alice = await api('alice')
  const person = await newPerson(alice, 'Leaver')
  const key = await person.createApiKey({ name: 'Old laptop', scopes: ['read'] })
  const client = await KeyClient.open(baseURL(), key.secret)
  try {
    await signIn(page, 'alice')
    await page.goto(`/settings/users/${person.me.id}`)
    const sheet = page.getByRole('dialog', { name: new RegExp(person.me.display_name) })
    await sheet.getByRole('button', { name: 'Deactivate…' }).click()
    const confirm = page.getByRole('alertdialog', { name: `Deactivate ${person.me.display_name}?` })
    await expect(confirm).toContainText('Their API keys are revoked for good')
    await confirm.getByRole('button', { name: 'Deactivate' }).click()
    await expect(toast(page, `${person.me.display_name} deactivated`)).toBeVisible()
    await expectRefusedKey(await client.rest('GET', '/auth/me'))
    await alice.updateUser(person.me.id, { is_active: true })
    // Back again, the key stays revoked and unlisted.
    await expectRefusedKey(await client.rest('GET', '/auth/me'))
    expect((await alice.adminApiKeys({ user_id: person.me.id })).items).toEqual([])
    const revoked = await alice.audit({ action: 'api_key.revoke', target_id: person.me.id })
    expect(revoked.map((entry) => entry.details.reason)).toEqual(['deactivated'])
  } finally {
    await client.dispose()
    await person.dispose()
    await alice.updateUser(person.me.id, { is_active: true })
  }
})

test('AAK-05: only platform admins, and only in a session', async ({ page, api }) => {
  // Carol isn't a platform admin: a plain 404 page, 403 from the API.
  await signIn(page, 'carol')
  await page.goto('/settings/all-api-keys')
  await expect(page.getByRole('heading', { name: 'We couldn’t find that page' })).toBeVisible()
  expect((await page.request.get('/api/v1/admin/api-keys')).status()).toBe(403)
  // Alice is, but her key isn't a session: key routes are session only.
  const alice = await api('alice')
  const key = await alice.createApiKey({
    name: `Admin script ${uniqueSuffix()}`,
    scopes: ['read', 'write', 'evaluate', 'mcp'],
  })
  const client = await KeyClient.open(baseURL(), key.secret)
  try {
    for (const [method, path] of [
      ['GET', '/admin/api-keys'],
      ['DELETE', `/admin/api-keys/${key.key.id}`],
      ['GET', '/admin/users'],
      ['GET', '/admin/audit'],
    ] as const) {
      const response = await client.rest(method, path)
      expect(response.status(), `${method} ${path}`).toBe(403)
      expect(((await response.json()) as { code: string }).code).toBe('insufficient_scope')
    }
    expect((await client.rest('GET', '/auth/me')).status()).toBe(200)
  } finally {
    await client.dispose()
    await alice.revokeApiKey(key.key.id)
  }
})

test('AAK-06: a project the owner can no longer open is counted for them and struck through here', async ({
  page,
  api,
}) => {
  // UX m1 (contract-phase5 §3.1): the key keeps the project's id but no longer reaches
  // it; the owner's list counts it, this list names it as unavailable.
  const alice = await api('alice')
  const carol = await api('carol')
  const run = uniqueSuffix()
  const kept = await createTeamProject(alice, 'Kept', { carol: 'member' })
  const left = await createTeamProject(alice, 'Left', { carol: 'member' })
  const key = await carol.createApiKey({
    name: `Two projects ${run}`,
    scopes: ['read'],
    project_ids: [kept.id, left.id],
  })
  try {
    await alice.send('DELETE', `/projects/${left.slug}/members/${carol.me.id}`, undefined, 204)
    const mine = (await carol.apiKeys()).items.find((item) => item.id === key.key.id)
    expect(mine?.projects.map((project) => project.name)).toEqual([kept.name])
    expect(mine?.unavailable_project_count).toBe(1)

    await signIn(page, 'carol')
    await page.goto('/settings/api-keys')
    const own = page.getByRole('row').filter({ hasText: `Two projects ${run}` })
    await expect(own).toContainText(kept.name)
    await expect(own).not.toContainText(left.name)
    await expect(own).toContainText('+1 project you can no longer open')

    await signIn(page, 'alice')
    await openAdminKeys(page, `?q=${run}`)
    const row = keyRow(page, `Two projects ${run}`)
    await expect(row).toContainText(kept.name)
    await expect(row).toContainText(`${left.name} (the owner can no longer open it)`)
    await expect(row).toContainText('Owner can’t open 1')
    const listed = await alice.adminApiKeys({ q: run })
    expect(listed.items[0]?.projects.map((project) => project.owner_can_view).sort()).toEqual([
      false,
      true,
    ])
  } finally {
    await carol.revokeApiKey(key.key.id)
  }
})
