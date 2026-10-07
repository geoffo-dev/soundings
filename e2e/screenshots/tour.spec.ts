import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import type { Browser, Locator, Page } from '@playwright/test'

import { FakeAgent } from '../scripts/fake-agent'
import { type AiAgentList, askAgent, NAMESPACE, registerAgent, waitRun } from '../tests/support/ai'
import { Api, daysFromNow, type Person } from '../tests/support/api'
import { emailTo, Mailpit, newPeople, projectWithIdea, type Message } from '../tests/support/email'
import { expect, heading, settled, signIn, test } from '../tests/support/fixtures'
import { renderPdfPages } from '../tests/support/pdf'
import { fillPublicForm, humanCheckDone } from '../tests/support/public'

/**
 * The product tour: a dozen hero screenshots that tell Soundings' story in order, from the
 * real app with the demo data (for the root README and the release notes). Not a
 * regression test.
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
const PROPOSAL = 'CUST-6'
const SECTIONS = {
  summary:
    'Add a **Starter** tier for teams of up to ten people, billed by active seats each month instead of the annual Team plan.',
  problem:
    'Small teams trial the product and leave at the paywall: the Team plan is annual and starts at 25 seats.\n\n- 61% of trials from teams under ten don’t convert\n- Sales spends a third of its calls on discount requests from small teams',
  solution:
    'A monthly Starter tier:\n\n1. Pay for the seats used in the month, from 2 to 10\n2. The same features as Team, without SSO and audit export\n3. One click to move to Team when they grow',
  market:
    'About 4,800 small teams trial us each year. Competitors with a monthly tier convert 18–24% of them.',
  cost: '| Work | Weeks |\n|---|---|\n| Billing changes | 3 |\n| Plan limits | 2 |\n| Pricing page and emails | 1 |',
  benefits:
    'At a 15% conversion: about 720 new teams and **£410k** in the first year, with a path into Team.',
  risks:
    'Some Team customers under ten seats may downgrade. We limit the tier to new accounts for the first two quarters.',
  next_steps:
    'Approve a two-quarter pilot in the UK and Ireland, with a go/no-go review at the end of Q2.',
}

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
 * Once per run: CUST-6's proposal with margin threads and its PDF, Idea evaluator's
 * evaluation of CUST-12 (left out of the score), and an invitation email to a new person
 * in a project that is archived again (so the seeded story looks as seeded).
 */
function prepare(browser: Browser): Promise<Prepared> {
  ready ??= (async () => {
    const alice = await Api.as(baseURL(), 'alice')
    const bob = await Api.as(baseURL(), 'bob')
    const carol = await Api.as(baseURL(), 'carol')
    try {
      if ((await alice.proposal(PROPOSAL)).proposal === null) {
        await alice.startProposal(PROPOSAL)
        await alice.writeSections(PROPOSAL, SECTIONS)
        const pricing = await bob.startThread(
          PROPOSAL,
          'problem',
          'Is the 61% from the last two quarters or the whole year?',
        )
        await alice.reply(PROPOSAL, pricing.id, 'The last four quarters; I’ll add the source.')
        await carol.startThread(
          PROPOSAL,
          'risks',
          'Could we grandfather existing small Team customers instead?',
        )
      }
      const { body } = await alice.exportProposal(PROPOSAL, 'pdf')
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
      await bob.dispose()
      await carol.dispose()
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
    name: '07-proposal',
    as: 'alice',
    variants: ['1440-light', '1440-dark'],
    open: async (page) => {
      await page.goto(`/ideas/${PROPOSAL}?tab=proposal`)
      await expect(page.getByRole('heading', { level: 2, name: /Problem$/ })).toBeVisible()
      await expect(page.getByText('Is the 61% from the last two quarters')).toBeVisible()
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
]

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
