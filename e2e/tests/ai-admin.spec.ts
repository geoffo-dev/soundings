import type { Page } from '@playwright/test'

import {
  agentName,
  aiTeam,
  type AiAgent,
  type AiAgentList,
  type AiRunList,
  askAgent,
  type CreatedAiAgent,
  NAMESPACE,
  registerAgent,
  retireAgents,
  skipWithoutAi,
  waitRun,
} from './support/ai'
import { type AdminApiKeyPage, uniqueSuffix } from './support/api'
import { expect, signIn, test, toast } from './support/fixtures'
import { expectRefusedKey, KeyClient } from './support/mcp'
import { FakeAgent } from '../scripts/fake-agent'

/**
 * Admin settings → AI agents (contract-phase6 §3.1–3.2, §3.15): a platform admin
 * registers a kagent agent (namespace and name, purposes, projects); Soundings creates its
 * service account (a member of those projects) and one key, shown once with the Secret and
 * RemoteMCPServer manifests; the A2A URL is built from the controller in effect, never
 * typed; Test connection reads the agent card through it; rotating revokes the old key at
 * once; disabling stops runs and revokes the key; enabling needs a rotation. Session only,
 * platform admins only. Test plan: AA6-*.
 */

const baseURL = () => test.info().project.use.baseURL ?? ''

async function openAgents(page: Page) {
  await page.goto('/settings/ai-agents')
  await expect(page.getByRole('heading', { name: 'AI agents', exact: true }).first()).toBeVisible()
}

const rowOf = (page: Page, displayName: string) =>
  page.getByRole('row').filter({ hasText: displayName })

async function rowAction(page: Page, displayName: string, action: string | RegExp) {
  await rowOf(page, displayName)
    .getByRole('button', { name: `Actions for ${displayName}` })
    .click()
  await page.getByRole('menuitem', { name: action }).click()
}

/** Closes the key dialog the way an admin who copied it would. */
async function closeKeyDialog(page: Page, title: string) {
  const dialog = page.getByRole('dialog', { name: title })
  await dialog.getByRole('button', { name: 'I’ve copied it' }).click()
  const anyway = dialog.getByRole('button', { name: 'Close without copying' })
  if (await anyway.isVisible().catch(() => false)) await anyway.click()
  await expect(dialog).toHaveCount(0)
}

test.describe('@ai Admin settings → AI agents', () => {
  test.beforeEach(skipWithoutAi)

  test('AA6-01 an admin registers an agent: its service account and key, shown once; Test connection', async ({
    page,
    context,
    api,
  }) => {
    const alice = await api('alice')
    const team = await aiTeam(alice, 'AI admin')
    const name = agentName()
    const displayName = `Evaluator ${uniqueSuffix()}`
    const { settings } = await alice.get<AiAgentList>('/admin/ai-agents')
    let created: CreatedAiAgent | undefined
    try {
      await context.grantPermissions(['clipboard-read', 'clipboard-write'])
      await signIn(page, 'alice')
      await openAgents(page)
      await expect(page.getByText('Settings in effect')).toBeVisible()
      await expect(page.getByRole('main')).toContainText(settings.kagent_url)
      await expect(page.getByRole('main')).toContainText(settings.mcp_url)

      await page.getByRole('button', { name: 'Register agent' }).first().click()
      const sheet = page.getByRole('dialog', { name: 'Register agent' })
      await sheet.getByLabel('Display name').fill(displayName)
      await sheet.getByLabel('Description').fill('Scores ideas against the rubric (e2e).')
      await sheet.getByLabel('Namespace').fill('Soundings')
      await sheet.getByLabel('Agent name').fill('idea.evaluator')
      await expect(sheet.getByLabel('Namespace')).toHaveValue('soundings') // lower-cased as typed
      await sheet.getByRole('button', { name: /^Register agent/ }).click()
      // Kubernetes names only: nothing that could change the URL's host or path.
      await expect(sheet.getByText(/Use lower-case letters, digits and hyphens/)).toHaveCount(1)
      await sheet.getByLabel('Namespace').fill(NAMESPACE)
      await sheet.getByLabel('Agent name').fill(name)
      // The A2A URL is built from the controller in effect.
      await expect(sheet).toContainText(`${settings.kagent_url}/api/a2a/${NAMESPACE}/${name}/`)
      await sheet.getByRole('checkbox', { name: 'Evaluate ideas' }).check()
      await sheet.getByRole('checkbox', { name: 'Research ideas' }).check()
      await sheet.getByRole('checkbox', { name: team.project.name }).check()
      const posted = page.waitForResponse(
        (response) =>
          response.url().endsWith('/api/v1/admin/ai-agents') &&
          response.request().method() === 'POST',
      )
      await sheet.getByRole('button', { name: /^Register agent/ }).click()
      const response = await posted
      expect(response.status()).toBe(201)
      expect(response.headers()['cache-control']).toBe('no-store')
      created = (await response.json()) as CreatedAiAgent
      const secret = created.key.secret

      // The key, once: with its Secret and RemoteMCPServer, "you won't see it again".
      const dialog = page.getByRole('dialog', { name: 'Copy the agent’s key' })
      await expect(dialog).toContainText(secret)
      await expect(dialog).toContainText('You won’t see it again')
      await expect(dialog).toContainText(`authorization: "Bearer ${secret}"`)
      await expect(dialog).toContainText(`name: soundings-agent-${name}`)
      await expect(dialog).toContainText('kind: RemoteMCPServer')
      await expect(dialog).toContainText(settings.mcp_url)
      await dialog.getByRole('button', { name: 'Copy the agent’s key' }).click()
      expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(secret)
      await closeKeyDialog(page, 'Copy the agent’s key')

      // ...and then nowhere: not on the page, in the URL, in storage or in the list.
      await expect(page.locator('body')).not.toContainText(secret)
      expect(page.url()).not.toContain(secret.slice(16))
      const stored = await page.evaluate(() =>
        JSON.stringify([{ ...localStorage }, { ...sessionStorage }]),
      )
      expect(stored).not.toContain(secret.slice(16))
      const listed = await alice.raw('GET', '/admin/ai-agents')
      expect(await listed.text()).not.toContain(secret.slice(16))

      const row = rowOf(page, displayName)
      await expect(row).toContainText(`${NAMESPACE}/${name}`)
      await expect(row).toContainText('Enabled')
      await expect(row).toContainText('Not used yet')
      await expect(row).toContainText(team.project.name)

      // Its service account: a member of the project, never signing in; its key listed.
      const agent = created.agent
      const users = await alice.adminUsers(displayName)
      const account = users.find((user) => user.id === agent.service_account.id)
      expect([account?.is_service_account, account?.is_active]).toEqual([true, true])
      const members = await alice.get<{ user: { id: string }; role: string }[]>(
        `/projects/${team.project.slug}/members`,
      )
      expect(members.find((member) => member.user.id === agent.service_account.id)?.role).toBe(
        'member',
      )
      const keys = await alice.get<AdminApiKeyPage>(
        `/admin/api-keys?user_id=${agent.service_account.id}`,
      )
      expect(keys.items.map((key) => [key.prefix, key.scopes.slice().sort()])).toEqual([
        [secret.slice(0, 16), ['evaluate', 'mcp', 'read', 'write']],
      ])

      // The operator gives the agent its key; Test connection reads its card.
      new FakeAgent().giveKey(NAMESPACE, name, secret)
      await rowAction(page, displayName, 'Test connection')
      const tested = page.getByRole('dialog', { name: `${displayName} answered` })
      await expect(tested).toContainText(`${agent.card_url}`)
      await expect(tested).toContainText('200')
      await expect(tested).toContainText('Yes') // streaming
      await expect(tested).toContainText('0.3')
      await tested.getByRole('button', { name: 'Done' }).click()

      // Registering the same namespace and name again: refused, said in plain words.
      await page.getByRole('button', { name: 'Register agent' }).first().click()
      const again = page.getByRole('dialog', { name: 'Register agent' })
      await again.getByLabel('Display name').fill(`${displayName} twice`)
      await again.getByLabel('Namespace').fill(NAMESPACE)
      await again.getByLabel('Agent name').fill(name)
      await again.getByRole('checkbox', { name: 'Evaluate ideas' }).check()
      await again.getByRole('checkbox', { name: team.project.name }).check()
      await again.getByRole('button', { name: /^Register agent/ }).click()
      await expect(
        again.getByText('An agent with this namespace and name is already registered.'),
      ).toBeVisible()
      await expect(again.getByLabel('Agent name')).toHaveAttribute('aria-invalid', 'true')
      await again.getByRole('button', { name: 'Cancel' }).click()
    } finally {
      if (created) await retireAgents(alice, [{ agent: created.agent, secret: '', created }])
    }
  })

  test('AA6-02 a test connection that fails says so; rotating revokes the old key at once', async ({
    page,
    api,
  }) => {
    const alice = await api('alice')
    const team = await aiTeam(alice, 'AI rotate')
    const key = await team.idea({ title: 'Recycling points in every store' })
    const registered = await registerAgent(alice, {
      projectIds: [team.project.id],
      purposes: ['research'],
      displayName: `Rotating ${uniqueSuffix()}`,
    })
    const { agent } = registered
    const fake = new FakeAgent()
    try {
      await signIn(page, 'alice')
      await openAgents(page)
      // Without its key the agent doesn't exist for kagent: 404, in Soundings' words.
      fake.removeKey(agent.namespace, agent.name)
      await rowAction(page, agent.display_name, 'Test connection')
      const failed = page.getByRole('dialog', { name: `${agent.display_name} didn’t answer` })
      await expect(failed).toContainText("Couldn't reach the agent. (HTTP 404)")
      await expect(failed).toContainText('What to check')
      await failed.getByRole('button', { name: 'Done' }).click()

      // Rotate: confirm, the new key once; the old one is dead on the next call.
      await rowAction(page, agent.display_name, 'Rotate key…')
      const confirm = page.getByRole('alertdialog', { name: `Rotate ${agent.display_name}’s key?` })
      await expect(confirm).toContainText('the agent stops until its Secret holds the new key')
      const rotated = page.waitForResponse(
        (response) =>
          response.url().endsWith(`/admin/ai-agents/${agent.id}/key`) &&
          response.request().method() === 'POST',
      )
      await confirm.getByRole('button', { name: 'Rotate key' }).click()
      const response = await rotated
      expect(response.status()).toBe(201)
      expect(response.headers()['cache-control']).toBe('no-store')
      const body = (await response.json()) as { key: { secret: string }; revoked_key_id: string }
      expect(body.revoked_key_id).toBe(registered.created.key.key.id)
      await expect(page.getByRole('dialog', { name: 'Copy the agent’s new key' })).toContainText(
        body.key.secret,
      )
      await closeKeyDialog(page, 'Copy the agent’s new key')
      const old = await KeyClient.open(baseURL(), registered.secret)
      try {
        await expectRefusedKey(await old.rpc('tools/list'))
      } finally {
        await old.dispose()
      }
      // With the new key in its Secret the agent works again.
      fake.giveKey(agent.namespace, agent.name, body.key.secret)
      const run = await askAgent(team.owner, key, 'research', agent.id)
      expect((await waitRun(alice, key, run.id)).status).toBe('succeeded')
      const used = await alice.get<AiAgent>(`/admin/ai-agents/${agent.id}`)
      expect(used.key?.last_used_at).not.toBeNull()
      await page.reload()
      await expect(rowOf(page, agent.display_name)).not.toContainText('Not used yet')
    } finally {
      await retireAgents(alice, [registered])
      await team.dispose()
    }
  })

  test('AA6-03 disabling stops the agent and revokes its key; enabling needs a rotation', async ({
    page,
    api,
  }) => {
    const alice = await api('alice')
    const team = await aiTeam(alice, 'AI disable')
    const key = await team.idea({ title: 'Evening opening hours' })
    const slow = await registerAgent(alice, {
      projectIds: [team.project.id],
      purposes: ['evaluate'],
      name: agentName('slow'),
      displayName: `Disabled ${uniqueSuffix()}`,
    })
    const { agent } = slow
    try {
      const working = await askAgent(team.owner, key, 'evaluate', agent.id)
      await waitRun(alice, key, working.id, (r) => r.events.some((e) => e.type === 'tool_called'))

      await signIn(page, 'alice')
      await openAgents(page)
      await expect(rowOf(page, agent.display_name)).toContainText('1 run active')
      await rowAction(page, agent.display_name, 'Disable…')
      const confirm = page.getByRole('alertdialog', { name: `Disable ${agent.display_name}?` })
      await expect(confirm).toContainText('Its runs stop and its key is revoked')
      await confirm.getByRole('button', { name: 'Disable agent' }).click()
      await expect(toast(page, `${agent.display_name} is disabled`)).toBeVisible()
      await expect(rowOf(page, agent.display_name)).toContainText('Disabled')

      // Its run stopped, its key is dead, nobody can ask it.
      expect((await waitRun(alice, key, working.id)).status).toBe('cancelled')
      const revoked = await KeyClient.open(baseURL(), slow.secret)
      try {
        await expectRefusedKey(await revoked.rpc('tools/list'))
      } finally {
        await revoked.dispose()
      }
      const runs = await alice.get<AiRunList>(`/ideas/${key}/ai-runs`)
      expect(runs.agents).toEqual([])
      expect(runs.permissions.request_evaluation_blocked_by).toBe('no_agent')

      // Enabling it again: still no key until a rotation (the toast offers one).
      await rowAction(page, agent.display_name, 'Enable')
      const enabled = toast(page, `${agent.display_name} is enabled`)
      await expect(enabled).toBeVisible()
      await expect(enabled.getByRole('button', { name: 'Rotate key' })).toBeVisible()
      await expect(rowOf(page, agent.display_name)).toContainText('Enabled')
      const listed = await alice.get<AiAgent>(`/admin/ai-agents/${agent.id}`)
      expect([listed.enabled, listed.key]).toEqual([true, null])
      expect((await alice.get<AiRunList>(`/ideas/${key}/ai-runs`)).agents).toEqual([])
    } finally {
      await retireAgents(alice, [slow])
      await team.dispose()
    }
  })

  test('AA6-04 only platform admins, in a session, manage agents', async ({ page, api }) => {
    const bob = await api('bob')
    const denied = await bob.raw('GET', '/admin/ai-agents')
    expect(denied.status()).toBe(403)
    await signIn(page, 'bob')
    await page.goto('/settings/ai-agents')
    await expect(page.getByRole('button', { name: 'Register agent' })).toHaveCount(0)
    // A platform admin's own API key can't either (session only).
    const alice = await api('alice')
    const key = await alice.createApiKey({
      name: `Admin script ${uniqueSuffix()}`,
      scopes: ['read', 'write'],
    })
    const client = await KeyClient.open(baseURL(), key.secret)
    try {
      const response = await client.rest('GET', '/admin/ai-agents')
      expect(response.status()).toBe(403)
      expect(((await response.json()) as { code: string }).code).toBe('insufficient_scope')
    } finally {
      await client.dispose()
      await alice.revokeApiKey(key.key.id)
    }
  })
})
