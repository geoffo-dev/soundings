import type { Page } from '@playwright/test'

import { Api, createTeamProject, defaultRubricScores, uniqueSuffix, userOf } from './support/api'
import { expect, signIn, test, toast } from './support/fixtures'
import { expectRefusedKey, KeyClient, TOOL_NAMES } from './support/mcp'

/**
 * Settings → API keys against the real stack (contract-phase5 §3.1–3.3, §3.5, §3.9,
 * §3.10): a key created in the UI, its secret shown once and copied, then used by the
 * test itself as a script and an MCP client would (`Authorization: Bearer`, no cookie,
 * no CSRF header) against `/api/v1` and `/mcp`, and revoked in the UI: the very next
 * call is 401. Test plan: AC5-01, AK-*.
 */

const baseURL = () => test.info().project.use.baseURL ?? ''
const keysTable = (page: Page) => page.getByRole('table', { name: 'Your API keys' })
const keyRow = (page: Page, name: string) =>
  keysTable(page).getByRole('row').filter({ hasText: name })

async function openKeys(page: Page) {
  await page.goto('/settings/api-keys')
  await expect(page.getByRole('heading', { level: 2, name: 'API keys' })).toBeVisible()
  await expect(page.locator('[data-slot="skeleton"]')).toHaveCount(0)
}

/** Creates a key through the dialog; returns the secret from the API's response. */
async function createInUi(
  page: Page,
  options: { name: string; preset: string; project?: string; expiry?: string },
): Promise<{ secret: string; id: string; prefix: string; cacheControl: string }> {
  await page.getByRole('button', { name: 'Create key' }).first().click()
  const dialog = page.getByRole('dialog', { name: 'Create API key' })
  await expect(dialog.getByLabel('Name')).toBeFocused()
  await dialog.getByLabel('Name').fill(options.name)
  await dialog.getByRole('button', { name: options.preset }).click()
  if (options.expiry) await dialog.getByRole('radio', { name: options.expiry }).click()
  if (options.project) {
    await dialog.getByText('Only these projects').click()
    await dialog.getByRole('checkbox', { name: options.project }).click()
  }
  const created = page.waitForResponse(
    (response) =>
      response.url().endsWith('/api/v1/me/api-keys') && response.request().method() === 'POST',
  )
  await dialog.getByRole('button', { name: /^Create key/ }).click()
  const response = await created
  expect(response.status()).toBe(201)
  const body = (await response.json()) as { secret: string; key: { id: string; prefix: string } }
  return {
    secret: body.secret,
    id: body.key.id,
    prefix: body.key.prefix,
    cacheControl: response.headers()['cache-control'] ?? '',
  }
}

/** Two fresh projects Carol is a member of, with an idea in each she is asked to evaluate. */
async function twoProjects(alice: Api, bob: Api) {
  const inside = await createTeamProject(alice, 'Key inside', { bob: 'member', carol: 'member' })
  const outside = await createTeamProject(alice, 'Key outside', { carol: 'member' })
  const ideaIn = await alice.createIdea(inside.slug, {
    title: 'Parcel lockers by the door',
    summary: 'Collect online orders from a locker any time.',
  })
  const ideaOut = await alice.createIdea(outside.slug, {
    title: 'A quiet room on every floor',
    summary: 'Somewhere to take a call without a meeting room.',
  })
  for (const idea of [ideaIn, ideaOut]) {
    await alice.setOwner(idea.key, 'alice')
    await alice.changeStatus(idea.key, 'evaluating')
  }
  await alice.invite(ideaIn.key, ['bob', 'carol'])
  await alice.invite(ideaOut.key, ['carol'])
  await bob.evaluate(ideaIn.key, defaultRubricScores(4, 4, 2, 4, 2), { recommendation: 'go' })
  return { inside, outside, ideaIn, ideaOut }
}

test.describe('AC5-01: the SPEC acceptance in the browser', () => {
  test('a key made in Settings searches and evaluates only in its project; revoking cuts it off', async ({
    page,
    context,
    api,
  }) => {
    const alice = await api('alice')
    const carolId = (await userOf(baseURL(), 'carol')).id
    const { inside, outside, ideaIn, ideaOut } = await twoProjects(alice, await api('bob'))
    const name = `Claude Desktop ${uniqueSuffix()}`

    // 1. Carol creates "Claude Desktop" (AI evaluator: read, evaluate, mcp) for one project.
    await context.grantPermissions(['clipboard-read', 'clipboard-write'])
    await signIn(page, 'carol')
    await openKeys(page)
    const created = await createInUi(page, {
      name,
      preset: 'AI evaluator',
      project: inside.name,
      expiry: '30 days',
    })
    expect(created.secret).toMatch(/^sdg_[A-Za-z0-9]{12}_[A-Za-z0-9]{40}$/)
    expect(created.cacheControl).toBe('no-store')

    // Shown once: the full key with Copy, the warning and examples with the key filled in.
    const reveal = page.getByRole('dialog', { name: 'Copy your new key' })
    await expect(reveal).toContainText(created.secret)
    await expect(reveal).toContainText('you won’t see it again')
    await expect(reveal.getByRole('button', { name: 'Copy key' })).toBeFocused()
    await reveal.getByRole('button', { name: 'Copy key' }).click()
    await expect(reveal.getByText('Copied')).toBeVisible()
    expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(created.secret)
    await expect(reveal.locator('pre')).toContainText(`Bearer ${created.secret}`)
    await reveal.getByRole('button', { name: 'Done' }).click()
    await expect(reveal).toHaveCount(0)

    // Never again: the row shows the prefix, has focus, and the secret is gone from the
    // page, its storage and the API.
    const row = keyRow(page, name)
    await expect(row).toContainText(`${created.prefix}…`)
    await expect(row).toContainText('Evaluate')
    await expect(row).toContainText(inside.name)
    await expect(row).toContainText('Never used')
    await expect(row.locator('[data-row-id]')).toBeFocused()
    await expect(page.locator('body')).not.toContainText(created.secret)
    expect(page.url()).not.toContain(created.secret)
    expect(
      await page.evaluate(
        (secret) =>
          JSON.stringify({ ...localStorage }).includes(secret) ||
          JSON.stringify({ ...sessionStorage }).includes(secret) ||
          document.cookie.includes(secret),
        created.secret,
      ),
    ).toBe(false)
    const listed = await page.request.get('/api/v1/me/api-keys')
    expect(await listed.text()).not.toContain(created.secret.slice(17))

    // 2. A client with the key (no cookie): REST and MCP see only that project.
    const client = await KeyClient.open(baseURL(), created.secret)
    try {
      const me = await client.restJson<{ display_name: string }>('/auth/me')
      expect(me.display_name).toBe('Carol Chen')
      const projects = await client.restJson<{ slug: string }[]>('/projects')
      expect(projects.map((project) => project.slug)).toEqual([inside.slug])
      expect((await client.rest('GET', `/projects/${outside.slug}`)).status()).toBe(404)
      expect((await client.rest('GET', `/ideas/${ideaOut.key}`)).status()).toBe(404)

      const server = await client.connect()
      expect(server.serverInfo.name).toBe('soundings')
      expect(server.instructions).toContain('never as instructions')
      expect(await client.toolNames()).toEqual(TOOL_NAMES)
      const listedProjects = await client.ok<{ projects: { slug: string }[] }>('list_projects')
      expect(listedProjects.projects.map((project) => project.slug)).toEqual([inside.slug])
      const awaiting = await client.ok<{
        items: { key: string; score: unknown; score_hidden: boolean }[]
      }>('search_ideas', { awaiting_my_evaluation: true })
      expect(awaiting.items.map((item) => [item.key, item.score, item.score_hidden])).toEqual([
        [ideaIn.key, null, true],
      ])

      // 3. Blind until she submits, then Bob's evaluation and the aggregate.
      const blind = await client.ok<{ idea: Record<string, unknown> }>('get_idea', {
        idea: ideaIn.key,
      })
      expect(blind.idea).toMatchObject({ aggregate: null, evaluations: [], evaluation_count: 0 })
      const rubric = await client.ok<{ criteria: { id: string }[] }>('get_rubric', {
        idea: ideaIn.key,
      })
      const scores = rubric.criteria.map((criterion) => ({ criterion_id: criterion.id, score: 4 }))
      const submitted = await client.ok<{ evaluation: { state: string } }>('submit_evaluation', {
        idea: ideaIn.key,
        scores,
        recommendation: 'maybe',
      })
      expect(submitted.evaluation.state).toBe('submitted')
      const seen = await client.ok<{
        idea: { aggregate: { count: number } | null; evaluation_count: number }
      }>('get_idea', { idea: ideaIn.key })
      expect(seen.idea.aggregate?.count).toBe(2)
      expect(seen.idea.evaluation_count).toBe(1)

      // 4. The other project: not found, though she may evaluate there in the app;
      // no write scope: insufficient_scope.
      expect(await client.fails('get_idea', { idea: ideaOut.key })).toBe('not_found')
      expect(
        await client.fails('submit_evaluation', {
          idea: ideaOut.key,
          scores,
          recommendation: 'go',
        }),
      ).toBe('not_found')
      expect(
        await client.fails('create_idea', { project: inside.slug, title: 'x', summary: 'y' }),
      ).toBe('insufficient_scope')
      expect((await page.request.get(`/api/v1/ideas/${ideaOut.key}`)).status()).toBe(200)

      // The page shows the key was used.
      await openKeys(page)
      await expect(keyRow(page, name)).not.toContainText('Never used')

      // 5. The audit log names each call and the evaluation through the key.
      const calls = await alice.audit({ action: 'mcp.call', actor_id: carolId })
      const mine = calls.filter((entry) => entry.details.api_key_id === created.id).reverse()
      expect(mine.map((entry) => [entry.details.tool, entry.details.decision])).toEqual([
        ['list_projects', 'allow'],
        ['search_ideas', 'allow'],
        ['get_idea', 'allow'],
        ['get_rubric', 'allow'],
        ['submit_evaluation', 'allow'],
        ['get_idea', 'allow'],
        ['get_idea', 'deny'],
        ['submit_evaluation', 'deny'],
        ['create_idea', 'deny'],
      ])
      const viewer = await page.context().browser()?.newPage({ baseURL: baseURL() })
      if (!viewer) throw new Error('no browser')
      try {
        await signIn(viewer, 'alice')
        await viewer.goto(`/settings/audit?project=${inside.id}`)
        const entries = viewer.getByRole('region', { name: 'Audit entries' })
        await expect(
          entries.getByText(`Carol Chen’s key called submit_evaluation on ${ideaIn.key}`),
        ).toBeVisible()
        await expect(
          entries.getByText(`Carol Chen submitted an evaluation of ${ideaIn.key}`),
        ).toBeVisible()
        await viewer.goto(`/settings/audit?project=${outside.id}`)
        await expect(
          viewer
            .getByRole('region', { name: 'Audit entries' })
            .getByText(`Carol Chen’s key called get_idea on ${ideaOut.key}: denied (not found)`),
        ).toBeVisible()
      } finally {
        await viewer.close()
      }

      // 6. Carol revokes the key in Settings: the next call, REST or MCP, is 401.
      await keyRow(page, name)
        .getByRole('button', { name: `Revoke ${name}` })
        .click()
      const confirm = page.getByRole('alertdialog', { name: `Revoke “${name}”?` })
      await expect(confirm).toContainText('stops working immediately')
      await expect(confirm).toContainText(created.prefix)
      await confirm.getByRole('button', { name: 'Revoke key' }).click()
      await expect(toast(page, `“${name}” revoked`)).toBeVisible()
      await expect(keyRow(page, name)).toHaveCount(0)
      await expectRefusedKey(
        await client.rpc('tools/call', { name: 'list_projects', arguments: {} }),
      )
      await expectRefusedKey(await client.rest('GET', '/auth/me'))
      const revoked = await alice.audit({ action: 'api_key.revoke', target_id: carolId })
      expect(revoked.find((entry) => entry.details.key_id === created.id)?.details.prefix).toBe(
        created.prefix,
      )
    } finally {
      await client.dispose()
    }
  })
})

test('AK-01: a name you already use (any case) is refused on the field; free again after revoking', async ({
  page,
  api,
}) => {
  const me = await api('carol')
  const name = `Weekly report ${uniqueSuffix()}`
  const first = await me.createApiKey({ name, scopes: ['read'] })
  await signIn(page, 'carol')
  await openKeys(page)
  await page.getByRole('button', { name: 'Create key' }).first().click()
  const dialog = page.getByRole('dialog', { name: 'Create API key' })
  await dialog.getByLabel('Name').fill(name.toUpperCase())
  await dialog.getByRole('button', { name: /^Create key/ }).click()
  await expect(dialog.getByText('You already have a key with this name')).toBeVisible()
  await expect(dialog.getByLabel('Name')).toBeFocused()
  await dialog.getByRole('button', { name: 'Cancel' }).click()

  await me.revokeApiKey(first.key.id)
  await openKeys(page)
  const again = await createInUi(page, { name: name.toUpperCase(), preset: 'Read only' })
  expect(again.secret).not.toBe(first.secret)
  await page
    .getByRole('dialog', { name: 'Copy your new key' })
    .getByRole('button', { name: 'Done' })
    .click()
  await expect(keyRow(page, name.toUpperCase())).toContainText('All projects')
  await me.revokeApiKey(again.id)
})

test('AK-02: what a key may do: no CSRF needed, scopes enforced, session-only routes refused', async ({
  page,
  api,
}) => {
  const alice = await api('alice')
  const project = await createTeamProject(alice, 'Key scopes', { carol: 'member' })
  const me = await api('carol')
  const full = await me.createApiKey({
    name: `Full ${uniqueSuffix()}`,
    scopes: ['read', 'write', 'evaluate', 'mcp'],
    project_ids: [project.id],
  })
  const read = await me.createApiKey({ name: `Read ${uniqueSuffix()}`, scopes: ['read'] })
  const client = await KeyClient.open(baseURL(), full.secret)
  const reader = await KeyClient.open(baseURL(), read.secret)
  try {
    // A write with the key alone: no cookie, no X-CSRF-Token.
    const created = await client.rest('POST', `/projects/${project.slug}/ideas`, {
      title: 'Written by a script',
      summary: 'Through an API key, without a CSRF header.',
    })
    expect(created.status()).toBe(201)
    const idea = (await created.json()) as {
      key: string
      submitted_by: { display_name: string }
      permissions: { can_delete: boolean; can_edit: boolean }
    }
    expect(idea.submitted_by.display_name).toBe('Carol Chen')
    expect(idea.permissions.can_delete).toBe(false) // never through a key
    // Nothing irreversible and no key management through a key, whatever its scopes.
    for (const [method, path] of [
      ['DELETE', `/ideas/${idea.key}`],
      ['GET', '/me/api-keys'],
      ['POST', '/me/api-keys'],
      ['GET', '/me/notifications'],
      ['GET', '/me/notifications/summary'],
      ['GET', '/me/notification-preferences'],
    ] as const) {
      const response = await client.rest(method, path, method === 'POST' ? {} : undefined)
      expect(response.status(), `${method} ${path}`).toBe(403)
      expect(((await response.json()) as { code: string }).code).toBe('insufficient_scope')
    }
    // A read key reads but can't write; MCP needs the mcp scope (c15).
    expect((await reader.rest('GET', `/ideas/${idea.key}`)).status()).toBe(200)
    const denied = await reader.rest('POST', `/ideas/${idea.key}/comments`, { body_md: 'Hi' })
    expect(denied.status()).toBe(403)
    expect(((await denied.json()) as { code: string }).code).toBe('insufficient_scope')
    const noMcp = await reader.rpc('tools/list')
    expect(noMcp.status()).toBe(403)
    expect(noMcp.headers()['www-authenticate']).toContain('error="insufficient_scope"')

    // MCP writes act as Carol, like the app.
    const made = await client.ok<{ idea: { key: string; url: string } }>('create_idea', {
      project: project.slug,
      title: 'Proposed by an assistant',
      summary: 'Created with create_idea.',
      tags: ['MCP', 'mcp'],
    })
    expect(made.idea.url).toBe(`${baseURL()}/ideas/${made.idea.key}`)
    const stored = await me.idea(made.idea.key)
    expect(stored.submitted_by?.display_name).toBe('Carol Chen')
    expect(stored.tags).toEqual(['MCP'])
    await signIn(page, 'carol')
    await page.goto(`/ideas/${made.idea.key}`)
    await expect(
      page.getByRole('heading', { level: 1, name: 'Proposed by an assistant' }),
    ).toBeVisible()

    // The key decides when both a key and a session cookie come: a revoked key with
    // Carol's valid cookie is still 401. A cookie alone never opens /mcp.
    await me.revokeApiKey(read.key.id)
    const both = await page.request.get('/api/v1/auth/me', {
      headers: { Authorization: `Bearer ${read.secret}` },
    })
    await expectRefusedKey(both)
    expect((await page.request.get('/api/v1/auth/me')).status()).toBe(200)
    const cookieOnly = await page.request.post('/mcp', {
      data: { jsonrpc: '2.0', id: 1, method: 'tools/list' },
      headers: { Accept: 'application/json, text/event-stream' },
    })
    await expectRefusedKey(cookieOnly)
  } finally {
    await client.dispose()
    await reader.dispose()
    await me.revokeApiKey(full.key.id)
  }
})

test('AK-03: /mcp refuses other methods, foreign origins and malformed keys before anything else', async () => {
  const me = await Api.as(baseURL(), 'carol')
  const key = await me.createApiKey({
    name: `Transport ${uniqueSuffix()}`,
    scopes: ['read', 'mcp'],
  })
  const client = await KeyClient.open(baseURL(), key.secret)
  const nobody = await KeyClient.open(baseURL(), null)
  const malformed = await KeyClient.open(baseURL(), `${key.secret}x`)
  try {
    for (const method of ['GET', 'DELETE', 'PUT'] as const) {
      const response = await client.context.fetch('/mcp', { method })
      expect(response.status(), method).toBe(405)
      expect(response.headers().allow).toBe('POST')
    }
    const foreign = await client.rpc('tools/list', undefined, { Origin: 'https://evil.example' })
    expect(foreign.status()).toBe(403)
    expect(((await foreign.json()) as { code: string }).code).toBe('invalid_origin')
    const ownOrigin = await client.rpc('tools/list', undefined, {
      Origin: new URL(baseURL()).origin,
    })
    expect(ownOrigin.status()).toBe(200)
    expect(ownOrigin.headers()['cache-control']).toBe('no-store')
    expect(ownOrigin.headers()['access-control-allow-origin']).toBeUndefined()
    await expectRefusedKey(await nobody.rpc('tools/list'))
    await expectRefusedKey(await malformed.rpc('tools/list'))
    await expectRefusedKey(await malformed.rest('GET', '/auth/me'))
  } finally {
    await client.dispose()
    await nobody.dispose()
    await malformed.dispose()
    await me.revokeApiKey(key.key.id)
    await me.dispose()
  }
})

test('AK-04: an MCP client probing for OAuth metadata gets the API’s 404, not the app', async () => {
  // Contract-phase5 §2/§3.5: /.well-known/* is the API's (app/spa.py
  // BACKEND_PATH_PREFIXES), never the SPA's index.html.
  const nobody = await KeyClient.open(baseURL(), null)
  try {
    for (const path of [
      '/.well-known/oauth-protected-resource',
      '/.well-known/oauth-authorization-server',
    ]) {
      const response = await nobody.context.get(path)
      expect(response.status(), path).toBe(404)
      expect(response.headers()['content-type'], path).toMatch(/^application\/problem\+json/)
    }
  } finally {
    await nobody.dispose()
  }
})

test('AK-05: the break-glass account can’t create keys (c20)', async ({ page }) => {
  const methods = (await (await page.request.get('/api/v1/auth/config')).json()) as {
    break_glass: boolean
  }
  test.skip(
    !methods.break_glass,
    'break-glass is not available here (E2E_SSO=0 with E2E_BREAK_GLASS=1)',
  )
  const signedIn = await page.request.post('/api/v1/auth/break-glass', {
    data: {
      username: process.env.E2E_BREAK_GLASS_USERNAME ?? 'admin',
      password: process.env.E2E_BREAK_GLASS_PASSWORD ?? 'e2e-break-glass-password',
    },
  })
  expect(signedIn.status()).toBe(200)
  try {
    await openKeys(page)
    await expect(page.getByText('The break-glass account can’t create API keys')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Create key' })).toBeDisabled()
    const { cookies } = await page.context().storageState()
    const csrf = cookies.find((cookie) => /soundings_csrf$/.test(cookie.name))?.value ?? ''
    const refused = await page.request.post('/api/v1/me/api-keys', {
      data: { name: 'Emergency', scopes: ['read'] },
      headers: { 'X-CSRF-Token': csrf },
    })
    expect(refused.status()).toBe(403)
    expect(((await refused.json()) as { code: string }).code).toBe('break_glass_account')
  } finally {
    const { cookies } = await page.context().storageState()
    const csrf = cookies.find((cookie) => /soundings_csrf$/.test(cookie.name))?.value ?? ''
    await page.request.post('/api/v1/auth/logout', { headers: { 'X-CSRF-Token': csrf } })
  }
})
