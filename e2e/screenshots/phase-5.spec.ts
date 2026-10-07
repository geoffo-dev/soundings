import { mkdirSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import type { Page } from '@playwright/test'

import { Api, type Person, uniqueKey, uniqueSuffix } from '../tests/support/api'
import { expect, settled, signIn, test } from '../tests/support/fixtures'
import { KeyClient } from '../tests/support/mcp'

/**
 * Review screenshots of the Phase 5 screens from the real app with the demo data. Not a
 * regression test.
 *
 * `npm run screenshots:phase5` → docs/screenshots/phase-5/ (`SCREENSHOT_DIR` overrides):
 * <screen>-<1440-light|1440-dark|390-light>.png for Settings → API keys (Carol's three
 * keys, one used a moment ago by an MCP client, one restricted to a project she has since
 * left: "+1 project you can no longer open") and its "For developers and AI assistants"
 * section opened, the create dialog filled in ("Evaluate with an assistant", one
 * project), the key shown once (revoked straight after: it opens nothing), Admin settings
 * → API keys (Alice: everyone's keys; the project Carol left struck through), the
 * proposal editor of CUST-6 with two pending suggestions (Carol's through MCP, Bob's
 * through the API) and the audit log's "API keys and MCP" entries.
 *
 * Needs freshly seeded data (the local stack reseeds on start).
 */

const here = dirname(fileURLToPath(import.meta.url))
const outDir = resolve(process.env.SCREENSHOT_DIR ?? join(here, '../../docs/screenshots/phase-5'))
mkdirSync(outDir, { recursive: true })

const baseURL = () => test.info().project.use.baseURL ?? ''

test.describe.configure({ mode: 'serial' })

const PROPOSAL_KEY = 'CUST-6'
const SECTIONS = {
  summary:
    'Add a **Starter** tier for teams of up to ten people, billed by active seats each month instead of the annual Team plan.',
  problem:
    'Small teams trial the product and leave at the paywall: the Team plan is annual and starts at 25 seats.\n\n- 61% of trials from teams under ten don’t convert\n- Sales spends a third of its calls on discount requests from small teams',
  solution:
    'A monthly Starter tier:\n\n1. Pay for the seats used in the month, from 2 to 10\n2. The same features as Team, without SSO and audit export\n3. One click to move to Team when they grow',
  market:
    'About 4,800 small teams trial us each year. Competitors with a monthly tier convert 18–24% of them.',
  risks:
    'Some Team customers under ten seats may downgrade. We limit the tier to new accounts for the first two quarters.',
}
const SUGGESTED_SUMMARY =
  'Add a monthly **Starter** tier for teams of two to ten people, billed by the seats they use, so small teams can start without the annual Team plan.\n\nWe expect about 720 new teams in the first year.'
const SUGGESTED_RISKS =
  'Some Team customers under ten seats may downgrade. We limit the tier to new accounts for the first two quarters, and review downgrades monthly.'

let ready: Promise<void> | undefined

/**
 * Once per run: Carol's keys ("Claude Desktop" used through MCP just now, "Weekly report
 * script" with an expiry, restricted to two projects and "Partner pilots", a private
 * project she then leaves (archived afterwards, so no sidebar shows it), "Old laptop" for
 * all projects), keys of Bob and Priya, and CUST-6's proposal with Carol's MCP suggestion
 * for Summary and Bob's REST one for Risks.
 */
function prepare(): Promise<void> {
  ready ??= (async () => {
    const alice = await Api.as(baseURL(), 'alice')
    const bob = await Api.as(baseURL(), 'bob')
    const carol = await Api.as(baseURL(), 'carol')
    const priya = await Api.as(baseURL(), 'priya')
    try {
      const cust = await carol.project('customer-innovation')
      const tools = await carol.project('internal-tools')
      const pilots = await alice.createProject({
        name: 'Partner pilots',
        slug: `partner-pilots-${uniqueSuffix()}`,
        key: uniqueKey('PL'),
        visibility: 'private',
      })
      await alice.addMember(pilots.slug, 'carol', 'member')
      await carol.createApiKey({
        name: 'Old laptop',
        scopes: ['read'],
      })
      await carol.createApiKey({
        name: 'Weekly report script',
        scopes: ['read'],
        project_ids: [cust.id, tools.id, pilots.id],
        expires_at: new Date(Date.now() + 90 * 86_400_000).toISOString(),
      })
      // Carol leaves the pilot: the key keeps its id but no longer reaches it (UX m1).
      await alice.send('DELETE', `/projects/${pilots.slug}/members/${carol.me.id}`, undefined, 204)
      await alice.archiveCreated()
      const claude = await carol.createApiKey({
        name: 'Claude Desktop',
        scopes: ['read', 'write', 'evaluate', 'mcp'],
        project_ids: [cust.id],
      })
      await bob.createApiKey({ name: 'Jira sync', scopes: ['read', 'write'] })
      await priya.createApiKey({
        name: 'Board report',
        scopes: ['read'],
        expires_at: new Date(Date.now() + 30 * 86_400_000).toISOString(),
      })

      if ((await alice.proposal(PROPOSAL_KEY)).proposal === null) {
        await alice.startProposal(PROPOSAL_KEY)
      }
      await alice.writeSections(PROPOSAL_KEY, SECTIONS)
      const client = await KeyClient.open(baseURL(), claude.secret)
      try {
        await client.connect()
        await client.ok('search_ideas', { awaiting_my_evaluation: true })
        await client.ok('get_proposal', { idea: PROPOSAL_KEY })
        await client.ok('propose_proposal_section', {
          idea: PROPOSAL_KEY,
          section_key: 'summary',
          body_md: SUGGESTED_SUMMARY,
        })
        await client.fails('get_idea', { idea: 'TOOLS-2' })
      } finally {
        await client.dispose()
      }
      await bob.send(
        'POST',
        `/ideas/${PROPOSAL_KEY}/proposal/suggestions`,
        { section_key: 'risks', body_md: SUGGESTED_RISKS },
        201,
      )
    } finally {
      for (const api of [alice, bob, carol, priya]) await api.dispose()
    }
  })()
  return ready
}

async function openKeys(page: Page) {
  await page.goto('/settings/api-keys')
  await expect(page.getByRole('heading', { level: 2, name: 'API keys' })).toBeVisible()
  await expect(page.getByRole('row').filter({ hasText: 'Claude Desktop' })).toBeVisible()
}

async function openCreate(page: Page) {
  await openKeys(page)
  await page.getByRole('button', { name: 'Create key' }).first().click()
  const dialog = page.getByRole('dialog', { name: 'Create API key' })
  await dialog.getByLabel('Name').fill('Claude Code')
  await dialog.getByRole('button', { name: /^Evaluate with an assistant/ }).click()
  await dialog.getByRole('radio', { name: '30 days' }).click()
  await dialog.getByText('Only these projects').click()
  await dialog.getByRole('checkbox', { name: 'Customer Innovation' }).click()
  return dialog
}

interface Shot {
  name: string
  as: Person
  fullPage?: boolean
  open: (page: Page, phone: boolean) => Promise<void>
}

const SHOTS: Shot[] = [
  // First, so the log shows the story's own entries, not the keys this run shows once.
  {
    name: 'audit-api-keys-and-mcp',
    as: 'alice',
    open: async (page) => {
      await page.goto('/settings/audit?action=api_keys')
      await expect(page.getByRole('heading', { level: 2, name: 'Audit log' })).toBeVisible()
      await expect(page.getByText(/Carol Chen’s key called/).first()).toBeVisible()
    },
  },
  {
    name: 'api-keys',
    as: 'carol',
    open: openKeys,
  },
  {
    name: 'api-keys-connect-mcp',
    as: 'carol',
    open: async (page) => {
      await openKeys(page)
      await page.getByRole('button', { name: 'For developers and AI assistants' }).click()
      await page
        .getByRole('region', { name: 'For developers and AI assistants' })
        .evaluate((element) => element.scrollIntoView({ block: 'start' }))
    },
  },
  {
    name: 'api-keys-create-dialog',
    as: 'carol',
    open: async (page) => {
      await openCreate(page)
      await scrollToTop(page) // the name and the presets, not the end of the form
    },
  },
  {
    name: 'api-keys-secret-reveal',
    as: 'carol',
    open: async (page, phone) => {
      const dialog = await openCreate(page)
      await dialog.getByLabel('Name').fill(phone ? 'Claude Code (phone)' : 'Claude Code')
      const created = page.waitForResponse(
        (response) =>
          response.url().endsWith('/me/api-keys') && response.request().method() === 'POST',
      )
      await dialog.getByRole('button', { name: /^Create key/ }).click()
      const { key } = (await (await created).json()) as { key: { id: string } }
      await expect(page.getByRole('dialog', { name: 'Copy your new key' })).toBeVisible()
      // The key on the screenshot opens nothing.
      const carol = await Api.as(baseURL(), 'carol')
      await carol.revokeApiKey(key.id)
      await carol.dispose()
    },
  },
  {
    name: 'admin-api-keys',
    as: 'alice',
    open: async (page) => {
      await page.goto('/settings/api-keys?everyone=1')
      await expect(page.getByRole('heading', { level: 2, name: 'API keys' })).toBeVisible()
      await expect(page.getByRole('radio', { name: 'Everyone’s keys' })).toBeChecked()
      await expect(page.getByRole('row').filter({ hasText: 'Board report' })).toBeVisible()
    },
  },
  {
    name: 'proposal-pending-suggestions',
    as: 'alice',
    open: async (page, phone) => {
      await page.goto(`/ideas/${PROPOSAL_KEY}?tab=proposal`)
      await expect(page.getByRole('heading', { name: '1 suggestion for Summary' })).toBeVisible()
      // The Summary section from its heading, just below the sticky editor bar.
      const target = phone
        ? page.locator('article[id^="proposal-suggestion-"]').first()
        : page.getByRole('heading', { level: 2, name: /Summary$/ })
      await target.evaluate((element) => {
        element.scrollIntoView({ block: 'start' })
        let parent = element.parentElement
        while (parent && parent.scrollTop === 0) parent = parent.parentElement
        if (parent) parent.scrollTop -= 72
      })
    },
  },
]

const VARIANTS = [
  {
    suffix: '1440-light',
    viewport: { width: 1440, height: 900 },
    colorScheme: 'light',
    phone: false,
  },
  {
    suffix: '1440-dark',
    viewport: { width: 1440, height: 900 },
    colorScheme: 'dark',
    phone: false,
  },
  { suffix: '390-light', viewport: { width: 390, height: 844 }, colorScheme: 'light', phone: true },
] as const

/** Scrolls every scrolled container (dialog bodies, the app's <main>) back to the top. */
async function scrollToTop(page: Page) {
  await page.evaluate(() => {
    for (const element of document.querySelectorAll<HTMLElement>('*')) {
      if (element.scrollTop > 0) element.scrollTop = 0
    }
  })
}

async function shoot(page: Page, path: string, fullPage = false) {
  await settled(page)
  await page.evaluate(() => document.fonts.ready)
  await page.waitForTimeout(500) // enter animations
  await page.screenshot({ path, animations: 'disabled', caret: 'hide', fullPage })
}

test.beforeAll(async () => {
  test.setTimeout(120_000)
  await prepare()
})

for (const variant of VARIANTS) {
  test.describe(variant.suffix, () => {
    test.use({
      viewport: variant.viewport,
      colorScheme: variant.colorScheme,
      isMobile: variant.phone,
      hasTouch: variant.phone,
    })

    for (const shot of SHOTS) {
      test(`${shot.name}-${variant.suffix}`, async ({ page }) => {
        await signIn(page, shot.as)
        await shot.open(page, variant.phone)
        await shoot(page, join(outDir, `${shot.name}-${variant.suffix}.png`), shot.fullPage)
      })
    }
  })
}
