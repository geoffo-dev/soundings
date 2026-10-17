import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import type { Browser, Locator, Page } from '@playwright/test'

import { FakeAgent } from '../scripts/fake-agent'
import { type AiAgentList, askAgent, NAMESPACE, registerAgent, waitRun } from '../tests/support/ai'
import { Api, daysFromNow, uniqueSuffix, type Person } from '../tests/support/api'
import { emailTo, Mailpit, newPeople, projectWithIdea, type Message } from '../tests/support/email'
import { expect, heading, settled, signIn, test } from '../tests/support/fixtures'
import { renderPdfPages } from '../tests/support/pdf'
import {
  confirmationToken,
  conversation,
  messagesSheet,
  sendTeamMessage,
  trackedMessages,
} from '../tests/support/messages'
import { fillPublicForm, humanCheckDone, Visitor } from '../tests/support/public'

/**
 * The product tour: twenty-two hero screenshots that tell Soundings' story in order, from the
 * real app with the demo data (for the root README and the release notes). Not a
 * regression test. 07-08 show Internal Tools' own proposal template (TOOLS-3), 13-16 its
 * research step: the Research column, the checklist with similar ideas, the gate and an
 * outside researcher (bob on TOOLS-12, who has no role in the private project), 18-20
 * TOOLS-3's call for bids (Phase 10): the comparison as kenji (its owner), the rejected
 * bid without its insurance certificate, and alice's blind assessment beside the bid's
 * documents; 21-22 talking to a public submitter (Phase 11): priya's conversation with
 * CUST-21's sender, and a sender's tracking page with the team's messages and the reply box
 * (an idea sent through Customer Innovation's form at the end of the run, then deleted).
 *
 * `npm run screenshots:tour` (E2E_SSO=1 E2E_AI=1: the sign-in page with single sign-on,
 * and the fake kagent agent for the AI evaluation) → docs/screenshots/tour/
 * (`SCREENSHOT_DIR` overrides): NN-<screen>-<1440-light|1440-dark|390-light>.png, every
 * screen at 1440 light, some also dark or at 390 px; 08-proposal-pdf.png is the exported
 * PDF's first page (pdf.js) and 10-email-*.png an email as Mailpit received it.
 *
 * Needs freshly seeded data (the local stack reseeds on start) and SMTP (Mailpit).
 */

const here = dirname(fileURLToPath(import.meta.url))
const outDir = resolve(process.env.SCREENSHOT_DIR ?? join(here, '../../docs/screenshots/tour'))
mkdirSync(outDir, { recursive: true })

const baseURL = () => test.info().project.use.baseURL ?? ''

test.describe.configure({ mode: 'serial' })

const IDEA = 'CUST-12'
// Internal Tools' six-section template (Summary, Problem, Solution, Effort & rollout,
// Risks, The ask), seeded with text and the research appendix; the tour adds "The ask"
// and two margin threads.
const PROPOSAL = 'TOOLS-3'
const THE_ASK =
  'Two developers for six weeks from the next sprint, with QA and payments as the first users. We review the scenarios with QA after the first month.'

interface Prepared {
  /** The invitation's HTML, the run-unique project shown under a plain name. */
  email: string | null
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
 * Once per run: TOOLS-3's proposal with "The ask" and margin threads, and its PDF; Idea evaluator's
 * evaluation of CUST-12 (left out of the score), and an invitation email to a new person
 * in a project that is archived again (so the seeded story looks as seeded).
 */
function prepare(browser: Browser): Promise<Prepared> {
  ready ??= (async () => {
    const alice = await Api.as(baseURL(), 'alice')
    const kenji = await Api.as(baseURL(), 'kenji')
    const carol = await Api.as(baseURL(), 'carol')
    const dave = await Api.as(baseURL(), 'dave')
    try {
      if ((await kenji.threads(PROPOSAL)).length === 0) {
        await kenji.writeSections(PROPOSAL, { the_ask: THE_ASK })
        const sprint = await carol.startThread(
          PROPOSAL,
          'problem',
          'Is the day a sprint only QA’s, or the payments team’s copies too?',
        )
        await kenji.reply(
          PROPOSAL,
          sprint.id,
          'Only QA’s. Payments spend about two days a month on top; I’ll add it.',
        )
        await dave.startThread(
          PROPOSAL,
          'effort_rollout',
          'Could the platform team host it, so you don’t run another service?',
        )
      }
      const { body } = await kenji.exportProposal(PROPOSAL, 'pdf')
      writeFileSync(join(outDir, '08-proposal.pdf'), body)
      await renderPdfPages(browser, body, [{ page: 1, path: join(outDir, '08-proposal-pdf.png') }])

      const fake = new FakeAgent()
      expect(await fake.up(), `the fake kagent agent at ${fake.url} (E2E_AI=1)`).toBe(true)
      const evaluator = await ideaEvaluator(alice)
      const evaluations = await alice.get<{ items: { is_ai: boolean }[] }>(
        `/ideas/${IDEA}/evaluations`,
      )
      if (!evaluations.items.some((e) => e.is_ai)) {
        const run = await waitRun(
          alice,
          IDEA,
          (await askAgent(alice, IDEA, 'evaluate', evaluator)).id,
        )
        expect(run.status).toBe('succeeded')
      }

      let email: string | null = null
      if ((await alice.notificationSummary()).email_available && (await new Mailpit().isUp())) {
        const { theo } = await newPeople(alice, ['theo'])
        const { project, key } = await projectWithIdea(alice, 'Customer Care', [theo], {
          title: 'Gift returns without a receipt',
        })
        const since = new Date()
        await alice.inviteUsers(key, [theo.user], daysFromNow(6))
        const message: Message = await emailTo(theo, /Please evaluate/, since)
        await theo.api.dispose()
        await alice.archiveCreated()
        // The email exactly as sent, except that the project's run-unique name and key
        // ("Customer Care QX7KD2", QX7KD2-1) read as a real project's would.
        email = message.HTML.replaceAll(project.name, 'Customer Care').replaceAll(
          `${project.key}-`,
          'CARE-',
        )
      }
      return { email }
    } finally {
      await alice.dispose()
      await kenji.dispose()
      await carol.dispose()
      await dave.dispose()
    }
  })()
  return ready
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

type Variant = '1440-light' | '1440-dark' | '390-light'

interface Shot {
  name: string
  as: Person | null
  variants: Variant[]
  open: (page: Page, phone: boolean) => Promise<void>
}

const SHOTS: Shot[] = [
  {
    name: '01-sign-in',
    as: null,
    variants: ['1440-light', '390-light'],
    open: async (page) => {
      await page.goto('/login')
      await expect(page.getByRole('button', { name: /Alice Anders/ })).toBeVisible()
    },
  },
  {
    name: '02-my-work',
    as: 'alice',
    variants: ['1440-light', '1440-dark', '390-light'],
    open: async (page) => {
      await page.goto('/')
      await expect(page.locator('#evaluations').getByRole('listitem').first()).toBeVisible()
    },
  },
  {
    name: '03-board',
    as: 'alice',
    variants: ['1440-light', '1440-dark', '390-light'],
    open: async (page) => {
      await page.goto('/p/customer-innovation?view=board')
      await expect(page.getByRole('link', { name: /\(CUST-11\)$/ })).toBeVisible()
    },
  },
  {
    // Alice owns CUST-12: two evaluations in, two to come, and an AI evaluation.
    name: '04-idea-page',
    as: 'alice',
    variants: ['1440-light', '1440-dark', '390-light'],
    open: async (page) => {
      await page.goto(`/ideas/${IDEA}`)
      await expect(heading(page, 'Accessibility audit of the checkout')).toBeVisible()
    },
  },
  {
    // Alice's saved draft on TOOLS-9: blind, nobody else's scores in sight.
    name: '05-evaluate-sheet',
    as: 'alice',
    variants: ['1440-light', '390-light'],
    open: async (page) => {
      await page.goto('/ideas/TOOLS-9?evaluate=1')
      await expect(page.getByRole('dialog', { name: 'Evaluate' })).toBeVisible()
      await expect(page.getByText(/^Draft saved/)).toBeVisible()
    },
  },
  {
    // Alice submitted on TOOLS-6: now she sees everyone's scores.
    name: '06-evaluate-reveal',
    as: 'alice',
    variants: ['1440-light', '1440-dark', '390-light'],
    open: async (page) => {
      await page.goto('/ideas/TOOLS-6?evaluate=1')
      await expect(page.getByRole('dialog', { name: 'Your evaluation' })).toBeVisible()
      await expect(page.getByRole('region', { name: 'Everyone’s scores' })).toBeVisible()
    },
  },
  {
    // TOOLS-3 in Internal Tools' own template, with a margin thread on Problem.
    name: '07-proposal',
    as: 'kenji',
    variants: ['1440-light', '1440-dark'],
    open: async (page) => {
      await page.goto(`/ideas/${PROPOSAL}?tab=proposal`)
      await expect(page.getByRole('heading', { level: 2, name: /Problem$/ })).toBeVisible()
      await expect(page.getByText('Is the day a sprint only QA')).toBeVisible()
      // The tabs at the top edge: the outline, Summary and Problem's margin thread in view.
      await page
        .getByRole('tablist')
        .first()
        .evaluate((element) => element.scrollIntoView({ block: 'start' }))
    },
  },
  {
    name: '09-public-form',
    as: null,
    variants: ['1440-light', '390-light'],
    open: async (page) => {
      await page.goto('/customer-innovation/submit')
      await fillPublicForm(page, {
        title: 'Refill station for cleaning products',
        summary: 'Bring your own bottle and refill washing-up liquid and detergent in store.',
        name: 'Sam',
      })
      await humanCheckDone(page)
      await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur())
      await page.evaluate(() => window.scrollTo(0, 0))
    },
  },
  {
    name: '10-notifications',
    as: 'alice',
    variants: ['1440-light', '390-light'],
    open: async (page) => {
      await page.goto('/notifications')
      await expect(heading(page, 'Notifications')).toBeVisible()
      await expect(page.getByRole('link', { name: /CUST-|TOOLS-|GREEN-/ }).first()).toBeVisible()
    },
  },
  {
    name: '11-admin',
    as: 'alice',
    variants: ['1440-light', '1440-dark'],
    open: async (page) => {
      await page.goto('/settings/users')
      await expect(page.getByRole('table', { name: 'Users' }).getByRole('row').nth(1)).toBeVisible()
    },
  },
  {
    // Idea evaluator's evaluation of CUST-12: a rationale and sources per criterion, left
    // out of the score until the owner includes it.
    name: '12-ai-evaluation',
    as: 'alice',
    variants: ['1440-light', '1440-dark', '390-light'],
    open: async (page, phone) => {
      await page.goto(`/ideas/${IDEA}?tab=evaluations`)
      const card = page
        .locator('article[id^="evaluation-card-"]')
        .filter({ hasText: 'Idea evaluator' })
      await expect(card).toContainText('Not in score')
      await scrollTo(card, phone ? 64 : 24)
    },
  },
  {
    // Phase 8: Internal Tools checks ideas before evaluation: the Research column, each
    // card with its checklist progress and, on TOOLS-12, its researcher.
    name: '13-research-column',
    as: 'sven',
    variants: ['1440-light', '1440-dark', '390-light'],
    open: async (page, phone) => {
      await page.goto('/p/internal-tools?view=board')
      const column = page.getByRole('region', { name: /^Research\b/ })
      await expect(column.getByRole('link', { name: /\(TOOLS-12\)$/ })).toBeVisible()
      if (phone) await column.evaluate((node) => node.scrollIntoView({ inline: 'start' }))
    },
  },
  {
    // TOOLS-11's checklist is complete, and "Similar ideas" found Customer Innovation's
    // status page.
    name: '14-research-checklist',
    as: 'carol',
    variants: ['1440-light', '1440-dark', '390-light'],
    open: async (page, phone) => {
      await page.goto('/ideas/TOOLS-11')
      const panel = page.getByRole('region', { name: 'Research' })
      await expect(panel.getByRole('link', { name: /CUST-14/ })).toBeVisible()
      await scrollTo(panel, phone ? 64 : 24)
    },
  },
  {
    // The gate: dave (the project admin) drags TOOLS-12 on to Evaluating while one required
    // item is open; nothing is saved (the dialog is the shot).
    name: '15-research-gate',
    as: 'dave',
    variants: ['1440-light', '1440-dark', '390-light'],
    open: async (page) => {
      await page.goto('/p/internal-tools?view=board')
      const card = page.getByRole('link', { name: /\(TOOLS-12\)$/ })
      await expect(card).toBeVisible()
      await settled(page)
      const announcer = page.locator('[id^="DndLiveRegion"]')
      await card.focus()
      await page.keyboard.press('Space')
      await expect(announcer).toContainText('Picked up TOOLS-12')
      await page.keyboard.press('ArrowRight')
      await expect(announcer).toContainText('TOOLS-12 is over')
      await page.keyboard.press('Space')
      await expect(page.getByRole('dialog', { name: 'Finish the research first' })).toBeVisible()
    },
  },
  {
    // Phase 8b: bob has no role in the private Internal Tools; he researches TOOLS-12 as its
    // guest and sees that one idea only.
    name: '16-outside-researcher',
    as: 'bob',
    variants: ['1440-light', '1440-dark', '390-light'],
    open: async (page) => {
      await page.goto('/ideas/TOOLS-12')
      await expect(
        page.getByText('You can see this idea because you’re researching it.'),
      ).toBeVisible()
      // The guest's own line says "You" (no "not in this project" about yourself).
      await expect(page.getByTestId('researcher-line')).toContainText('You')
    },
  },
  {
    // Phase 8: Internal Tools' own proposal template, as its admin edits it.
    name: '17-proposal-template',
    as: 'dave',
    variants: ['1440-light', '1440-dark'],
    open: async (page) => {
      await page.goto('/p/internal-tools/settings?tab=proposal-template')
      await expect(page.getByRole('list', { name: 'Sections' }).getByRole('listitem')).toHaveCount(
        6,
      )
    },
  },
]

// Phase 10: TOOLS-3's call for bids "Data platform build", being assessed.
const BID_CALL = 'Data platform build'

async function bidsTab(page: Page) {
  await page.goto(`/ideas/${PROPOSAL}?tab=bids`)
  await expect(page.getByRole('heading', { level: 2, name: BID_CALL })).toBeVisible({
    timeout: 15_000,
  })
}

SHOTS.push(
  {
    // The comparison: ranks, section scores, the disagreement on Tessellate's Technical
    // score, the AI's assessment left out of the totals, the rejected bid apart.
    name: '18-bid-comparison',
    as: 'kenji',
    variants: ['1440-light', '1440-dark', '390-light'],
    open: async (page, phone) => {
      await bidsTab(page)
      const comparison = page.getByRole('region', { name: 'Comparison' })
      await expect(comparison.getByText('Northwind Data Ltd').first()).toBeVisible()
      await scrollTo(comparison, phone ? 64 : 24)
    },
  },
  {
    // Quillfield Systems sent no insurance certificate: flagged at once, rejected in one
    // click with a reason (and reversible until the award).
    name: '19-bid-must-haves',
    as: 'kenji',
    variants: ['1440-light', '1440-dark', '390-light'],
    open: async (page) => {
      await bidsTab(page)
      await page
        .getByRole('region', { name: 'Bids', exact: true })
        .getByRole('button', { name: 'Quillfield Systems', exact: true })
        .click()
      const sheet = page.getByRole('dialog', { name: 'Quillfield Systems' })
      await expect(sheet.getByRole('heading', { name: 'Documents' })).toBeVisible()
      await expect(sheet.getByText('No insurance certificate provided.')).toBeVisible()
    },
  },
  {
    // Alice assesses Delivery: blind (nobody's scores in sight), the bid's documents
    // beside the questions on a wide screen.
    name: '20-bid-assessment',
    as: 'alice',
    variants: ['1440-light', '390-light'],
    open: async (page, phone) => {
      await bidsTab(page)
      await page
        .getByRole('region', { name: 'Your assessments' })
        .getByRole('button', { name: 'Assess: Northwind Data Ltd, Delivery' })
        .click()
      const sheet = page.getByRole('dialog', { name: /Delivery · Northwind/ })
      await expect(sheet.getByRole('radiogroup').first()).toBeVisible()
      if (!phone) {
        const beside = sheet.getByRole('complementary', { name: 'The bid’s documents' })
        await expect(beside).toBeVisible()
        const pick = beside.getByRole('combobox', { name: 'Document to read' })
        if (await pick.isVisible()) {
          await pick.click()
          await page.getByRole('option', { name: /technical-proposal/ }).click()
        }
        await expect(beside).toContainText(/Northwind/)
      }
    },
  },
  {
    // Phase 11: priya (Customer Innovation's admin) wrote to the person who sent CUST-21
    // through the public form; Sam replied on his tracking page.
    name: '21-submitter-messages',
    as: 'priya',
    variants: ['1440-light', '1440-dark', '390-light'],
    open: async (page) => {
      await page.goto('/ideas/CUST-21?submission=1')
      const sheet = messagesSheet(page, 'Sam Okafor')
      await expect(conversation(sheet)).toHaveCount(2)
      await sheet
        .getByRole('textbox', { name: 'Message to Sam Okafor' })
        .fill('Lovely, thank you. We’ll start in those two stores in November.')
    },
  },
)

const VARIANTS = {
  '1440-light': { viewport: { width: 1440, height: 900 }, colorScheme: 'light', phone: false },
  '1440-dark': { viewport: { width: 1440, height: 900 }, colorScheme: 'dark', phone: false },
  '390-light': { viewport: { width: 390, height: 844 }, colorScheme: 'light', phone: true },
} as const

async function shoot(page: Page, path: string) {
  await settled(page)
  await page.evaluate(() => document.fonts.ready)
  await page.waitForTimeout(500) // enter animations
  await page.screenshot({ path, animations: 'disabled', caret: 'hide' })
}

test.beforeAll(async ({ browser }) => {
  test.setTimeout(240_000)
  await prepare(browser)
})

for (const [suffix, variant] of Object.entries(VARIANTS) as [
  Variant,
  (typeof VARIANTS)[Variant],
][]) {
  test.describe(suffix, () => {
    test.use({
      viewport: variant.viewport,
      colorScheme: variant.colorScheme,
      isMobile: variant.phone,
      hasTouch: variant.phone,
    })

    for (const shot of SHOTS.filter((s) => s.variants.includes(suffix))) {
      test(`${shot.name}-${suffix}`, async ({ page }) => {
        if (shot.as) await signIn(page, shot.as)
        await shot.open(page, variant.phone)
        await shoot(page, join(outDir, `${shot.name}-${suffix}.png`))
      })
    }
  })
}

// --- An email, as Mailpit received it ----------------------------------------------------
test('10-email: an invitation to evaluate, as Mailpit received it', async ({ browser }) => {
  const { email } = await prepare(browser)
  test.skip(!email, 'needs SMTP (Mailpit)')
  for (const variant of [
    { suffix: '1440-light', viewport: { width: 1024, height: 900 }, phone: false },
    { suffix: '390-light', viewport: { width: 390, height: 844 }, phone: true },
  ]) {
    const context = await browser.newContext({
      viewport: variant.viewport,
      colorScheme: 'light',
      isMobile: variant.phone,
    })
    const page = await context.newPage()
    await page.setContent(email ?? '', { waitUntil: 'load' })
    await page.screenshot({ path: join(outDir, `10-email-${variant.suffix}.png`), fullPage: true })
    await context.close()
  }
})

// --- A sender's tracking page (Phase 11), last: it sends an idea through the form --------
test('22-tracking-page: a sender’s tracking page with the team’s messages', async ({ browser }) => {
  test.setTimeout(180_000)
  const slug = 'customer-innovation'
  const title = 'Refill station for cleaning products'
  const priya = await Api.as(baseURL(), 'priya')
  const visitor = await Visitor.open(baseURL())
  let key: string | undefined
  try {
    const mail = (await priya.notificationSummary()).email_available && (await new Mailpit().isUp())
    const email = mail ? `ana.${uniqueSuffix()}@example.org` : null
    const since = new Date()
    const receipt = await visitor.submitted(slug, {
      title,
      summary: 'Bring your own bottle and refill washing-up liquid and detergent in store.',
      name: 'Ana Silva',
      email,
      wants_updates: false,
    })
    // Customer Innovation reviews public ideas first: priya approves this one.
    key = (await priya.moderationQueue(slug)).items.find((item) => item.title === title)?.key
    if (!key) throw new Error(`"${title}" isn't in the review queue`)
    await priya.approve(key)
    if (email) await visitor.verify(await confirmationToken(email, 'Customer Innovation', since))
    await sendTeamMessage(
      priya,
      key,
      'Thanks, Ana! Which store do you use most? We’d like to try it in one first.',
    )
    await visitor.replied(receipt.tracking_token, 'The one on the high street, near the station.')
    await sendTeamMessage(
      priya,
      key,
      'Perfect, that’s on our list. Would you be happy to tell us how it goes after a month?',
    )
    for (const [suffix, variant] of Object.entries(VARIANTS) as [
      Variant,
      (typeof VARIANTS)[Variant],
    ][]) {
      const context = await browser.newContext({
        baseURL: baseURL(),
        viewport: variant.viewport,
        colorScheme: variant.colorScheme,
        isMobile: variant.phone,
        hasTouch: variant.phone,
      })
      const page = await context.newPage()
      await page.goto(`/track#${receipt.tracking_token}`)
      const section = trackedMessages(page)
      await expect(conversation(section)).toHaveCount(3)
      await section
        .getByRole('textbox', { name: 'Reply to the team' })
        .fill('Happy to. I’ll bring my own bottles.')
      await settled(page)
      await page.evaluate(() => document.fonts.ready)
      await page.waitForTimeout(500) // enter animations
      await page.screenshot({
        path: join(outDir, `22-tracking-page-${suffix}.png`),
        animations: 'disabled',
        caret: 'hide',
        fullPage: true,
      })
      await context.close()
    }
  } finally {
    // The demo story stays as seeded: the idea (and its conversation) goes again.
    if (key) await priya.send('DELETE', `/ideas/${key}`, undefined, 204)
    await visitor.dispose()
    await priya.dispose()
  }
})
