import { mkdirSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import type { Locator, Page } from '@playwright/test'

import { FakeAgent } from '../scripts/fake-agent'
import {
  type AiAgentList,
  type AiRunDetail,
  askAgent,
  type CreatedAiAgent,
  NAMESPACE,
  registerAgent,
  type RegisteredAgent,
  requestRun,
  retireAgents,
  waitRun,
} from '../tests/support/ai'
import { Api, type Person } from '../tests/support/api'
import { expect, settled, signIn, test } from '../tests/support/fixtures'

/**
 * Review screenshots of the Phase 6 screens (AI assistance) from the real app with the
 * demo data and Soundings' fake kagent agent. Not a regression test.
 *
 * `npm run screenshots:phase6` (E2E_AI=1) → docs/screenshots/phase-6/ (`SCREENSHOT_DIR`
 * overrides): <screen>-<1440-light|1440-dark|390-light>.png. CUST-12 ("Accessibility audit
 * of the checkout": Alice owns it, Bob and Carol scored, Farah and Mateo haven't) with the
 * stack's "Idea evaluator" (soundings/idea-evaluator): its evaluation (a rationale and two
 * sources per criterion, left out of the score) and research note, and "Market
 * researcher" (a `-slow` fake agent) working live; the AI menu; the include switch on and
 * the score it changes; Farah's blind view; CUST-6's proposal with an AI suggestion for
 * Risks; Admin settings → AI agents with the register sheet, a key shown once (the agent
 * is disabled straight after: its key opens nothing) and a test connection.
 *
 * Needs freshly seeded data (the local stack reseeds on start, and registers "Idea
 * evaluator"; without it this spec registers it).
 */

const here = dirname(fileURLToPath(import.meta.url))
const outDir = resolve(process.env.SCREENSHOT_DIR ?? join(here, '../../docs/screenshots/phase-6'))
mkdirSync(outDir, { recursive: true })

const baseURL = () => test.info().project.use.baseURL ?? ''

test.describe.configure({ mode: 'serial' })

const IDEA = 'CUST-12'
const PROPOSAL = 'CUST-6'
const RISKS =
  'Some customers may abandon the new checkout while they learn it. We roll it out to 10% of traffic first and keep the old flow one click away.'

interface Prepared {
  evaluator: string // agent id
  researcher: RegisteredAgent
  evaluationId: string
}
let ready: Promise<Prepared> | undefined

/** The stack's "Idea evaluator" (soundings/idea-evaluator), or one registered now. */
async function ideaEvaluator(alice: Api): Promise<string> {
  const listed = await alice.get<AiAgentList>('/admin/ai-agents')
  const found = listed.items.find(
    (agent) => agent.namespace === NAMESPACE && agent.name === 'idea-evaluator',
  )
  if (found?.enabled && found.key) return found.id
  const cust = await alice.project('customer-innovation')
  const created = await registerAgent(alice, {
    projectIds: [cust.id],
    name: 'idea-evaluator',
    displayName: 'Idea evaluator',
  })
  return created.agent.id
}

/**
 * Once per run: Idea evaluator's evaluation and research note on CUST-12, its suggestion
 * for CUST-6's Risks, and "Market researcher" (slow) registered for Customer Innovation.
 */
function prepare(): Promise<Prepared> {
  ready ??= (async () => {
    const alice = await Api.as(baseURL(), 'alice')
    try {
      const fake = new FakeAgent()
      expect(await fake.up(), `the fake kagent agent at ${fake.url} (E2E_AI=1)`).toBe(true)
      const evaluator = await ideaEvaluator(alice)
      const cust = await alice.project('customer-innovation')
      const researcher = await registerAgent(alice, {
        projectIds: [cust.id],
        purposes: ['research'],
        name: 'market-researcher-slow',
        displayName: 'Market researcher',
      })
      const evaluated = await waitRun(
        alice,
        IDEA,
        (await askAgent(alice, IDEA, 'evaluate', evaluator)).id,
      )
      expect(evaluated.status).toBe('succeeded')
      const researched = await waitRun(
        alice,
        IDEA,
        (await askAgent(alice, IDEA, 'research', evaluator)).id,
      )
      expect(researched.status).toBe('succeeded')

      if ((await alice.proposal(PROPOSAL)).proposal === null) await alice.startProposal(PROPOSAL)
      await alice.writeSections(PROPOSAL, { risks: RISKS })
      const drafted = await waitRun(
        alice,
        PROPOSAL,
        (await askAgent(alice, PROPOSAL, 'draft_section', evaluator, 'risks')).id,
      )
      expect(drafted.status).toBe('succeeded')
      return {
        evaluator,
        researcher,
        evaluationId: evaluated.result.evaluation_id ?? '',
      }
    } finally {
      await alice.dispose()
    }
  })()
  return ready
}

/** Market researcher at work on CUST-12 (asked again whenever its last run ended). */
async function liveResearch(data: Prepared): Promise<AiRunDetail> {
  const alice = await Api.as(baseURL(), 'alice')
  try {
    const response = await requestRun(alice, IDEA, 'research', data.researcher.agent.id)
    expect([200, 201]).toContain(response.status())
    const { id } = (await response.json()) as { id: string }
    return await waitRun(alice, IDEA, id, (r) =>
      r.events.some((e) => e.type === 'tool_called' && e.message === 'Read the idea'),
    )
  } finally {
    await alice.dispose()
  }
}

async function setIncluded(data: Prepared, include: boolean) {
  const alice = await Api.as(baseURL(), 'alice')
  try {
    await alice.send(
      'PUT',
      `/ideas/${IDEA}/evaluations/${data.evaluationId}/include-in-aggregate`,
      { include },
    )
  } finally {
    await alice.dispose()
  }
}

/** Scrolls `target` to the top of its scrolling container, below the sticky header. */
async function scrollTo(target: Locator, offset = 80) {
  await target.evaluate((element, gap) => {
    element.scrollIntoView({ block: 'start' })
    let parent = element.parentElement
    while (parent && parent.scrollTop === 0) parent = parent.parentElement
    if (parent) parent.scrollTop -= gap
  }, offset)
}

/** Scrolls every scrolled container (sheet bodies, the app's <main>) back to the top. */
async function scrollToTop(page: Page) {
  await page.evaluate(() => {
    for (const element of document.querySelectorAll<HTMLElement>('*')) {
      if (element.scrollTop > 0) element.scrollTop = 0
    }
  })
}

async function openIdea(page: Page, key: string, tab = '') {
  await page.goto(`/ideas/${key}${tab ? `?tab=${tab}` : ''}`)
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
}

async function openAgents(page: Page) {
  await page.goto('/settings/ai-agents')
  await expect(page.getByText('Settings in effect')).toBeVisible()
}

async function fillRegister(page: Page, name: string) {
  await openAgents(page)
  await page.getByRole('button', { name: 'Register agent' }).first().click()
  const sheet = page.getByRole('dialog', { name: 'Register agent' })
  await sheet.getByLabel('Display name').fill('Proposal drafter')
  await sheet
    .getByLabel('Description')
    .fill('Drafts proposal sections from the idea and its comments. Owned by the CX team.')
  await sheet.getByLabel('Namespace').fill(NAMESPACE)
  await sheet.getByLabel('Agent name').fill(name)
  await sheet.getByRole('checkbox', { name: 'Draft proposal sections' }).check()
  await sheet.getByRole('checkbox', { name: 'Customer Innovation' }).check()
  return sheet
}

interface Shot {
  name: string
  as: Person
  fullPage?: boolean
  open: (page: Page, phone: boolean, data: Prepared, variant: string) => Promise<void>
  after?: (data: Prepared) => Promise<void>
}

const SHOTS: Shot[] = [
  {
    name: 'ai-menu',
    as: 'alice',
    open: async (page, phone) => {
      const alice = await Api.as(baseURL(), 'alice')
      // Nothing active, so the menu and the evaluators' "Ask AI to evaluate again" show.
      const runs = await alice.get<{ items: { id: string; status: string }[] }>(
        `/ideas/${IDEA}/ai-runs`,
      )
      for (const run of runs.items.filter((r) => ['queued', 'running'].includes(r.status))) {
        await alice.send('POST', `/ideas/${IDEA}/ai-runs/${run.id}/cancel`)
        await waitRun(alice, IDEA, run.id)
      }
      await alice.dispose()
      await openIdea(page, IDEA)
      await page.getByRole('button', { name: 'AI actions' }).first().click()
      await expect(page.getByRole('menuitem', { name: /Research this/ })).toBeVisible()
      if (phone) await page.waitForTimeout(200)
    },
  },
  {
    name: 'run-live',
    as: 'alice',
    open: async (page, phone, data) => {
      await liveResearch(data)
      await openIdea(page, IDEA)
      const card = page.locator('article[id^="ai-run-"]').filter({ hasText: 'Market researcher' })
      await expect(card.getByText('Working', { exact: true })).toBeVisible()
      await scrollTo(page.getByRole('heading', { name: 'AI runs' }), phone ? 64 : 24)
    },
  },
  {
    name: 'ai-evaluation',
    as: 'alice',
    open: async (page, phone) => {
      await openIdea(page, IDEA, 'evaluations')
      const card = page
        .locator('article[id^="evaluation-card-"]')
        .filter({ hasText: 'Idea evaluator' })
      await expect(card).toContainText('Not in score')
      await scrollTo(card, phone ? 64 : 24)
    },
  },
  {
    name: 'ai-evaluation-included',
    as: 'alice',
    open: async (page, phone, data) => {
      await setIncluded(data, true)
      await openIdea(page, IDEA, 'evaluations')
      const card = page
        .locator('article[id^="evaluation-card-"]')
        .filter({ hasText: 'Idea evaluator' })
      await expect(card.getByRole('switch')).toBeChecked()
      // The score with it: on a phone it heads the tab; on a desktop the page is tall
      // enough for the sidebar's score, the comparison and the AI card at once.
      if (phone) await scrollTo(page.getByRole('heading', { name: /submitted of/ }), 64)
      else await page.setViewportSize({ width: 1440, height: 2100 })
    },
    after: (data) => setIncluded(data, false),
  },
  {
    name: 'research-note',
    as: 'alice',
    open: async (page, phone) => {
      await openIdea(page, IDEA)
      const note = page.locator('article[id^="research-note-"]')
      await expect(note).toBeVisible()
      await scrollTo(note, phone ? 64 : 24)
    },
  },
  {
    name: 'pending-evaluator',
    as: 'farah',
    open: async (page, phone) => {
      await openIdea(page, IDEA, 'evaluations')
      await expect(page.getByText('Hidden until you submit').first()).toBeVisible()
      if (phone) await page.waitForTimeout(100)
    },
  },
  {
    name: 'draft-with-ai',
    as: 'alice',
    open: async (page, phone) => {
      await openIdea(page, PROPOSAL, 'proposal')
      await expect(page.getByTestId('proposal-editor')).toBeVisible()
      const risks = page.locator('#proposal-section-risks')
      const suggestion = risks.locator('article[id^="proposal-suggestion-"]')
      await expect(suggestion).toContainText('Idea evaluator')
      await scrollTo(phone ? suggestion : risks.getByRole('heading', { level: 2 }), 72)
    },
  },
  {
    name: 'admin-agents',
    as: 'alice',
    fullPage: true,
    open: async (page) => {
      await openAgents(page)
      await expect(page.getByRole('row').filter({ hasText: 'Market researcher' })).toBeVisible()
    },
  },
  {
    name: 'admin-register-agent',
    as: 'alice',
    open: async (page, _phone, _data, variant) => {
      await fillRegister(page, `proposal-drafter-${variant}`)
      await scrollToTop(page) // the name and the namespace, not the end of the form
    },
  },
  {
    name: 'admin-key-reveal',
    as: 'alice',
    open: async (page, _phone, _data, variant) => {
      const sheet = await fillRegister(page, `proposal-drafter-${variant}`)
      const posted = page.waitForResponse(
        (r) => r.url().endsWith('/admin/ai-agents') && r.request().method() === 'POST',
      )
      await sheet.getByRole('button', { name: /^Register agent/ }).click()
      const created = (await (await posted).json()) as CreatedAiAgent
      await expect(page.getByRole('dialog', { name: 'Copy the agent’s key' })).toBeVisible()
      // The key on the screenshot opens nothing.
      const alice = await Api.as(baseURL(), 'alice')
      await retireAgents(alice, [{ agent: created.agent, secret: '', created }])
      await alice.dispose()
    },
  },
  {
    name: 'admin-test-connection',
    as: 'alice',
    open: async (page, phone) => {
      await openAgents(page)
      const name = 'Idea evaluator'
      const row = page.getByRole('row').filter({ hasText: `${NAMESPACE}/idea-evaluator` })
      if (phone) await row.getByRole('button', { name: 'Test', exact: true }).click()
      else {
        await row.getByRole('button', { name: `Actions for ${name}` }).click()
        await page.getByRole('menuitem', { name: 'Test connection' }).click()
      }
      await expect(page.getByRole('dialog', { name: `${name} answered` })).toBeVisible()
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

async function shoot(page: Page, path: string, fullPage = false) {
  await settled(page)
  await page.evaluate(() => document.fonts.ready)
  await page.waitForTimeout(500) // enter animations
  await page.screenshot({ path, animations: 'disabled', caret: 'hide', fullPage })
}

test.beforeAll(async () => {
  test.setTimeout(180_000)
  await prepare()
})

test.afterAll(async () => {
  const data = await ready?.catch(() => undefined)
  if (!data) return
  const alice = await Api.as(baseURL(), 'alice')
  try {
    // Market researcher stops; the stack's Idea evaluator stays for whoever looks next.
    await retireAgents(alice, [data.researcher])
  } finally {
    await alice.dispose()
  }
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
        test.setTimeout(120_000)
        const data = await prepare()
        await signIn(page, shot.as)
        try {
          await shot.open(page, variant.phone, data, variant.suffix)
          await shoot(page, join(outDir, `${shot.name}-${variant.suffix}.png`), shot.fullPage)
        } finally {
          await shot.after?.(data)
        }
      })
    }
  })
}
