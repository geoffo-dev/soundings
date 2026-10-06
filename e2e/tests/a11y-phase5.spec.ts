import type { Page } from '@playwright/test'

import { Api, createTeamProject, uniqueSuffix, type Person } from './support/api'
import { expect, seriousViolations, settled, signIn, test } from './support/fixtures'
import { KeyClient } from './support/mcp'

/**
 * axe (WCAG 2.2 AA rules) on the Phase 5 screens against the real app, light and dark:
 * Settings → API keys (the list, the create dialog, the key shown once, the revoke
 * confirm), Admin settings → API keys (and its revoke confirm) and the proposal editor
 * with a pending suggestion from an MCP client (the changes and the suggested text).
 * Then the same at 390 px (no sideways scrolling, dialogs fill the screen) and creating
 * a key with the keyboard only. Test plan: A11Y5-*, MO5-*, K5-*.
 */

const baseURL = () => test.info().project.use.baseURL ?? ''

interface Prepared {
  run: string
  projectName: string
  proposalKey: string
}
let prepared: Promise<Prepared> | undefined

/** Once per worker: Carol's keys (one used), a proposal with Carol's MCP suggestion. */
function prepare(): Promise<Prepared> {
  prepared ??= (async () => {
    const run = uniqueSuffix()
    const alice = await Api.as(baseURL(), 'alice')
    const bob = await Api.as(baseURL(), 'bob')
    const carol = await Api.as(baseURL(), 'carol')
    try {
      const project = await createTeamProject(alice, 'A11y keys', {
        bob: 'member',
        carol: 'member',
      })
      await carol.createApiKey({
        name: `Claude Desktop ${run}`,
        scopes: ['read', 'evaluate', 'mcp'],
        project_ids: [project.id],
      })
      const used = await carol.createApiKey({
        name: `Weekly report ${run}`,
        scopes: ['read', 'write', 'mcp'],
        project_ids: [project.id],
        expires_at: new Date(Date.now() + 30 * 86_400_000).toISOString(),
      })
      await bob.createApiKey({ name: `Jira sync ${run}`, scopes: ['read'] })

      const idea = await alice.createIdea(project.slug, {
        title: 'Refill stations for cleaning products',
        summary: 'Customers bring their own bottles.',
      })
      await alice.setOwner(idea.key, 'bob')
      await alice.changeStatus(idea.key, 'shortlisted')
      await bob.startProposal(idea.key)
      await bob.writeSections(idea.key, {
        summary: 'Refill stations in ten stores.\n\nCustomers bring their own bottles.',
        problem: 'Single-use bottles are most of our plastic waste.',
      })
      const client = await KeyClient.open(baseURL(), used.secret)
      try {
        await client.ok('propose_proposal_section', {
          idea: idea.key,
          section_key: 'summary',
          body_md:
            'Refill stations in **all 40 stores** by December.\n\nCustomers bring their own bottles, or buy one at the station.',
        })
      } finally {
        await client.dispose()
      }
      return { run, projectName: project.name, proposalKey: idea.key }
    } finally {
      await alice.dispose()
      await bob.dispose()
      await carol.dispose()
    }
  })()
  return prepared
}

async function openKeys(page: Page) {
  await page.goto('/settings/api-keys')
  await expect(page.getByRole('heading', { level: 2, name: 'API keys' })).toBeVisible()
  await settled(page)
}

async function openCreate(page: Page, data: Prepared) {
  await openKeys(page)
  await page.getByRole('button', { name: 'Create key' }).first().click()
  const dialog = page.getByRole('dialog', { name: 'Create API key' })
  await dialog.getByLabel('Name').fill(`Axe ${data.run}`)
  await dialog.getByRole('button', { name: 'Evaluate with an assistant' }).click()
  await dialog.getByText('Only these projects').click()
  await dialog.getByRole('checkbox', { name: data.projectName }).click()
  return dialog
}

/** Revokes the keys a screen created (`Axe <run>…`), so the run stays under 25 keys. */
async function revokeAxeKeys(data: Prepared) {
  const carol = await Api.as(baseURL(), 'carol')
  try {
    for (const key of (await carol.apiKeys()).items) {
      if (key.name.startsWith(`Axe ${data.run}`)) await carol.revokeApiKey(key.id)
    }
  } finally {
    await carol.dispose()
  }
}

interface Screen {
  name: string
  as: Person
  open: (page: Page, data: Prepared) => Promise<void>
}

const SCREENS: Screen[] = [
  {
    name: 'Settings → API keys',
    as: 'carol',
    open: async (page, data) => {
      await openKeys(page)
      await expect(
        page.getByRole('row').filter({ hasText: `Weekly report ${data.run}` }),
      ).toBeVisible()
    },
  },
  {
    name: 'the create key dialog',
    as: 'carol',
    open: async (page, data) => {
      await openCreate(page, data)
    },
  },
  {
    name: 'the new key, shown once',
    as: 'carol',
    open: async (page, data) => {
      const dialog = await openCreate(page, data)
      await dialog.getByLabel('Name').fill(`Axe ${data.run} ${uniqueSuffix()}`)
      await dialog.getByRole('button', { name: /^Create key/ }).click()
      await expect(page.getByRole('dialog', { name: 'Copy your new key' })).toBeVisible()
      await revokeAxeKeys(data) // the dialog stays; the key is no use to anyone
    },
  },
  {
    name: 'the revoke confirm',
    as: 'carol',
    open: async (page, data) => {
      await openKeys(page)
      const name = `Weekly report ${data.run}`
      await page.getByRole('button', { name: `Revoke ${name}` }).click()
      await expect(page.getByRole('alertdialog', { name: `Revoke “${name}”?` })).toBeVisible()
    },
  },
  {
    name: 'Admin settings → API keys',
    as: 'alice',
    open: async (page, data) => {
      await page.goto(`/settings/all-api-keys?q=${data.run}`)
      await expect(page.getByRole('heading', { level: 2, name: 'All API keys' })).toBeVisible()
      await expect(page.getByText('3 keys', { exact: true })).toBeVisible()
    },
  },
  {
    name: 'the admin revoke confirm',
    as: 'alice',
    open: async (page, data) => {
      await page.goto(`/settings/all-api-keys?q=${data.run}`)
      const name = `Jira sync ${data.run}`
      await page.getByRole('button', { name: `Revoke Bob Brown’s key ${name}` }).click()
      await expect(page.getByRole('alertdialog')).toBeVisible()
    },
  },
  {
    name: 'a pending suggestion in the proposal editor (owner, changes)',
    as: 'bob',
    open: async (page, data) => {
      await page.goto(`/ideas/${data.proposalKey}?tab=proposal`)
      await expect(page.getByRole('heading', { name: '1 suggestion for Summary' })).toBeVisible()
      await expect(page.getByText('via assistant')).toBeVisible()
    },
  },
  {
    name: 'a pending suggestion in the proposal editor (owner, suggested text)',
    as: 'bob',
    open: async (page, data) => {
      await page.goto(`/ideas/${data.proposalKey}?tab=proposal`)
      await page.getByRole('radio', { name: 'Suggested text' }).click()
      await expect(page.locator('article strong', { hasText: 'all 40 stores' })).toBeVisible()
    },
  },
]

for (const colorScheme of ['light', 'dark'] as const) {
  test.describe(`${colorScheme} theme`, () => {
    test.use({ colorScheme })

    for (const screen of SCREENS) {
      test(`A11Y5: ${screen.name} has no serious or critical violations`, async ({ page }) => {
        const data = await prepare()
        await signIn(page, screen.as)
        await screen.open(page, data)
        await settled(page)
        await expect(page.locator('html')).toHaveClass(
          colorScheme === 'dark' ? /\bdark\b/ : /^(?!.*\bdark\b)/,
        )
        await page.waitForTimeout(300) // enter animations: axe sees final colours
        expect(await seriousViolations(page)).toEqual([])
      })
    }
  })
}

test.describe('on a phone (390 px)', () => {
  test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true })

  test('MO5-01: the Phase 5 screens fit without sideways scrolling; dialogs fill the screen', async ({
    page,
  }) => {
    test.setTimeout(120_000)
    const data = await prepare()
    const overflow = () =>
      page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      )
    for (const screen of SCREENS) {
      await test.step(screen.name, async () => {
        await page.context().clearCookies()
        await signIn(page, screen.as)
        await screen.open(page, data)
        await page.waitForTimeout(200)
        expect(await overflow(), screen.name).toBe(0)
        const dialog = page.getByRole('dialog').first()
        if (await dialog.isVisible()) {
          expect((await dialog.boundingBox())?.width ?? 0, screen.name).toBeGreaterThan(385)
        }
      })
    }
  })
})

test('K5-01: a key can be created, copied and closed with the keyboard only', async ({ page }) => {
  const data = await prepare()
  await signIn(page, 'carol')
  await openKeys(page)
  await page.getByRole('button', { name: 'Create key' }).first().focus()
  await page.keyboard.press('Enter')
  const dialog = page.getByRole('dialog', { name: 'Create API key' })
  await expect(dialog.getByLabel('Name')).toBeFocused()
  const name = `Axe ${data.run} keyboard`
  await page.keyboard.type(name)
  await page.keyboard.press('ControlOrMeta+Enter')
  const reveal = page.getByRole('dialog', { name: 'Copy your new key' })
  await expect(reveal.getByRole('button', { name: 'Copy key' })).toBeFocused()
  // Not copied: the first Esc asks (focus on its Copy key), the second closes.
  await page.keyboard.press('Escape')
  await expect(reveal.getByRole('alert')).toContainText('You haven’t copied the key')
  await expect(reveal.getByRole('button', { name: 'Copy key' }).last()).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(reveal).toHaveCount(0)
  await expect(
    page.getByRole('row').filter({ hasText: name }).locator('[data-row-id]'),
  ).toBeFocused()
  await revokeAxeKeys(data)
})
