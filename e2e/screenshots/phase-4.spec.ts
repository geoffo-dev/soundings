import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import type { Browser, Page } from '@playwright/test'

import { Api, uniqueSuffix, type Person } from '../tests/support/api'
import { links, Mailpit, type Message } from '../tests/support/email'
import { expect, settled, signIn, test } from '../tests/support/fixtures'
import { renderPdfPages } from '../tests/support/pdf'
import { fillPublicForm, fragmentToken, humanCheckDone, Visitor } from '../tests/support/public'

/**
 * Review screenshots of the Phase 4 screens from the real app (API, worker, Mailpit, the
 * PDF renderer) with the demo data. Not a regression test.
 *
 * `npm run screenshots:phase4` → docs/screenshots/phase-4/ (`SCREENSHOT_DIR` overrides):
 *
 * - <screen>-<1440-light|1440-dark|390-light>.png: the seeded Customer Innovation public
 *   form (its branding: green, IBM Plex Sans, its logo), the receipt after sending, the
 *   tracking page (a real submission, confirmed, approved and shortlisted), the address
 *   confirmation page, the proposal editor of CUST-6 with margin threads, its export
 *   menu, Settings → Branding with an unsaved change in the live preview, the project's
 *   Public form and Branding settings, the review queue and an idea waiting for review.
 * - pdf/CUST-6-proposal-page-<n>.png: the exported PDF's first pages, rendered by pdf.js.
 * - emails/mailpit-<subject>-<desktop-light|desktop-dark|390-light>.png: the branded
 *   submitter emails (confirmation, status change) as Mailpit received them.
 *
 * Needs freshly seeded data (the local stack reseeds on start) and SMTP (Mailpit).
 */

const here = dirname(fileURLToPath(import.meta.url))
const outDir = resolve(process.env.SCREENSHOT_DIR ?? join(here, '../../docs/screenshots/phase-4'))
const pdfDir = join(outDir, 'pdf')
const emailDir = join(outDir, 'emails')
mkdirSync(pdfDir, { recursive: true })
mkdirSync(emailDir, { recursive: true })

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
  cost: '| Work | Weeks |\n|---|---|\n| Billing changes | 3 |\n| Plan limits | 2 |\n| Pricing page and emails | 1 |',
  benefits:
    'At a 15% conversion: about 720 new teams and **£410k** in the first year, with a path into Team.',
  risks:
    'Some Team customers under ten seats may downgrade. We limit the tier to new accounts for the first two quarters.',
  next_steps:
    'Approve a two-quarter pilot in the UK and Ireland, with a go/no-go review at the end of Q2.',
}

interface Prepared {
  token: string
  heldKey: string
  mail: Message[]
}
let prepared: Prepared | undefined

/** Waits for an email and returns it with its full content. */
async function mailTo(address: string, subject: RegExp, since: Date): Promise<Message> {
  return new Mailpit().waitForMessage(address, { since, subject, timeoutMs: 60_000 })
}

/**
 * Once per run: CUST-6's proposal (written, with margin threads), a real public
 * submission to Customer Innovation that was confirmed, approved and shortlisted (its
 * tracking token and the two emails its sender got), and the PDF rendered to PNG.
 */
async function prepare(browser: Browser): Promise<Prepared> {
  if (prepared) return prepared
  const alice = await Api.as(baseURL(), 'alice')
  const bob = await Api.as(baseURL(), 'bob')
  const carol = await Api.as(baseURL(), 'carol')
  try {
    if ((await alice.proposal(PROPOSAL_KEY)).proposal === null) {
      await alice.startProposal(PROPOSAL_KEY)
      await alice.writeSections(PROPOSAL_KEY, SECTIONS)
      const pricing = await bob.startThread(
        PROPOSAL_KEY,
        'problem',
        'Is the 61% from the last two quarters or the whole year?',
      )
      await alice.reply(PROPOSAL_KEY, pricing.id, 'The last four quarters; I’ll add the source.')
      const weeks = await carol.startThread(
        PROPOSAL_KEY,
        'cost',
        'Billing might be more like four weeks with the tax changes.',
      )
      await alice.resolveThread(PROPOSAL_KEY, weeks.id)
      await carol.startThread(
        PROPOSAL_KEY,
        'risks',
        'Could we grandfather existing small Team customers instead?',
      )
    }

    // A submission through the form, followed to Shortlisted: tracking page and emails.
    const address = `jo.${uniqueSuffix()}@example.com`
    const since = new Date()
    const visitor = await Visitor.open(baseURL())
    const receipt = await visitor.submitted('customer-innovation', {
      title: 'Plastic-free packaging for online orders',
      summary: 'Ship online orders in paper and card only, and say so on the order page.',
      name: 'Jo Public',
      email: address,
      wants_updates: true,
    })
    const confirmation = await mailTo(address, /^Confirm your idea/, since)
    const verify = links(confirmation).find((href) => href.includes('/verify#'))
    await visitor.verify(fragmentToken(verify ?? ''))
    await visitor.dispose()
    const queue = await alice.moderationQueue('customer-innovation')
    const mine = queue.items.find((item) => item.title.startsWith('Plastic-free'))
    if (!mine) throw new Error('the submission is not in the queue')
    await alice.approve(mine.key)
    await alice.changeStatus(mine.key, 'evaluating')
    await alice.changeStatus(mine.key, 'shortlisted')
    const status = await mailTo(address, /is now Shortlisted/, since)
    const held = (await alice.moderationQueue('customer-innovation')).items[0]

    // The exported PDF, as the owner downloads it.
    const { body } = await alice.exportProposal(PROPOSAL_KEY, 'pdf')
    writeFileSync(join(pdfDir, `${PROPOSAL_KEY}-proposal.pdf`), body)
    await renderPdfPages(browser, body, [
      { page: 1, path: join(pdfDir, `${PROPOSAL_KEY}-proposal-page-1.png`) },
      { page: 2, path: join(pdfDir, `${PROPOSAL_KEY}-proposal-page-2.png`) },
      { page: 3, path: join(pdfDir, `${PROPOSAL_KEY}-proposal-page-3.png`) },
    ])
    prepared = {
      token: receipt.tracking_token,
      heldKey: held?.key ?? 'CUST-22',
      mail: [confirmation, status],
    }
    return prepared
  } finally {
    await alice.dispose()
    await bob.dispose()
    await carol.dispose()
  }
}

interface Shot {
  name: string
  as: Person | null
  /** Taller than the screen: the whole page. */
  fullPage?: boolean
  open: (page: Page, phone: boolean) => Promise<void>
}

const SHOTS: Shot[] = [
  {
    name: 'public-submit',
    as: null,
    fullPage: true,
    open: async (page) => {
      await page.goto('/customer-innovation/submit')
      await fillPublicForm(page, {
        title: 'Refill station for cleaning products',
        summary: 'Bring your own bottle and refill washing-up liquid and detergent in store.',
        name: 'Sam',
      })
      await humanCheckDone(page)
      await page.locator('main').evaluate((element) => element.scrollIntoView())
      await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur())
    },
  },
  {
    name: 'public-success',
    as: null,
    open: async (page) => {
      await page.goto('/customer-innovation/submit')
      const title = `Refill station for cleaning products ${uniqueSuffix()}`
      await fillPublicForm(page, {
        title,
        summary: 'Bring your own bottle and refill washing-up liquid and detergent in store.',
      })
      await humanCheckDone(page)
      await page.getByRole('button', { name: 'Send idea' }).click()
      await expect(
        page.getByRole('heading', { level: 1, name: 'Thanks! Your idea is in' }),
      ).toBeVisible()
      // Keep the seeded queue as it is: reject this one (it isn't shown again).
      const alice = await Api.as(baseURL(), 'alice')
      const sent = (await alice.moderationQueue('customer-innovation')).items.find(
        (item) => item.title === title,
      )
      if (sent) await alice.reject(sent.key)
      await alice.dispose()
    },
  },
  {
    name: 'public-tracking',
    as: null,
    fullPage: true,
    open: async (page) => {
      await page.goto(`/track#${prepared?.token}`)
      await expect(
        page.getByRole('heading', { level: 1, name: /^Plastic-free packaging/ }),
      ).toBeVisible()
      await expect(page.getByText('Shortlisted').first()).toBeVisible()
    },
  },
  {
    name: 'public-verify',
    as: null,
    open: async (page) => {
      await page.goto('/verify#eyJ2IjoxfQ.c2lnbmF0dXJl')
      await expect(
        page.getByRole('heading', { level: 1, name: 'Confirm your email address' }),
      ).toBeVisible()
    },
  },
  {
    name: 'proposal-editor',
    as: 'alice',
    open: async (page, phone) => {
      await page.goto(`/ideas/${PROPOSAL_KEY}?tab=proposal`)
      await expect(page.getByRole('heading', { level: 2, name: /Problem$/ })).toBeVisible()
      if (!phone) {
        await expect(page.getByText('Is the 61% from the last two quarters')).toBeVisible()
        // The Problem section and its thread in the middle, below the sticky editor bar.
        await page
          .getByRole('heading', { level: 2, name: /Problem$/ })
          .evaluate((element) => element.scrollIntoView({ block: 'center' }))
      }
    },
  },
  {
    name: 'proposal-export-menu',
    as: 'alice',
    open: async (page) => {
      await page.goto(`/ideas/${PROPOSAL_KEY}?tab=proposal`)
      await expect(page.getByRole('heading', { level: 2, name: /Problem$/ })).toBeVisible()
      await page.getByRole('button', { name: 'Export' }).click()
      await expect(page.getByRole('menuitem', { name: /PDF/ })).toBeVisible()
    },
  },
  {
    name: 'branding-settings',
    as: 'alice',
    open: async (page) => {
      await page.goto('/settings/branding')
      await expect(page.getByRole('heading', { level: 2, name: 'Branding' })).toBeVisible()
      // An unsaved change, so the live preview shows something the app doesn't yet.
      await page.getByLabel('App name').fill('Example Retail Ideas')
      await page.getByRole('button', { name: 'Plum (#7e22ce)' }).first().click()
      await expect(page.getByText('Unsaved changes')).toBeVisible()
      await scrollToTop(page)
    },
  },
  {
    name: 'project-public-form-settings',
    as: 'alice',
    open: async (page) => {
      await page.goto('/p/customer-innovation/settings?tab=public-form')
      await expect(
        page.getByRole('switch', { name: 'Accept ideas through the public form' }),
      ).toBeChecked()
    },
  },
  {
    name: 'project-branding-settings',
    as: 'alice',
    open: async (page) => {
      await page.goto('/p/customer-innovation/settings?tab=branding')
      await expect(
        page.getByRole('tabpanel', { name: 'Branding' }).getByTestId('branding-preview').first(),
      ).toBeVisible()
    },
  },
  {
    name: 'moderation-queue',
    as: 'alice',
    open: async (page) => {
      await page.goto('/p/customer-innovation/review')
      await expect(page.getByRole('list', { name: 'Ideas waiting for review' })).toBeVisible()
    },
  },
  {
    name: 'moderation-board-notice',
    as: 'alice',
    open: async (page) => {
      await page.goto('/p/customer-innovation?view=board')
      await expect(page.getByText(/ideas? from the public form (is|are) waiting/)).toBeVisible()
    },
  },
  {
    name: 'idea-held-for-review',
    as: 'alice',
    open: async (page) => {
      await page.goto(`/ideas/${prepared?.heldKey}`)
      await expect(page.getByRole('region', { name: 'Waiting for review' })).toBeVisible()
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

/** Scrolls every scrolled container (the app shell scrolls inside <main>) back to the top. */
async function scrollToTop(page: Page) {
  await page.evaluate(() => {
    for (const element of document.querySelectorAll<HTMLElement>('*')) {
      if (element.scrollTop > 0) element.scrollTop = 0
    }
    window.scrollTo(0, 0)
  })
}

async function shoot(page: Page, path: string, fullPage = false) {
  await settled(page)
  await page.evaluate(() => document.fonts.ready)
  await page.waitForTimeout(500) // enter animations
  await page.screenshot({ path, animations: 'disabled', caret: 'hide', fullPage })
}

test.beforeAll(async ({ browser }) => {
  test.setTimeout(240_000)
  const alice = await Api.as(baseURL(), 'alice')
  const email = (await alice.notificationSummary()).email_available
  await alice.dispose()
  test.skip(!email, 'needs SMTP (Mailpit) for the submitter’s emails')
  await prepare(browser)
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
        if (shot.as) await signIn(page, shot.as)
        await shot.open(page, variant.phone)
        await shoot(page, join(outDir, `${shot.name}-${variant.suffix}.png`), shot.fullPage)
      })
    }
  })
}

// --- Emails, as Mailpit received them -------------------------------------------------------
const EMAIL_VARIANTS = [
  { suffix: 'desktop-light', viewport: { width: 1024, height: 900 }, colorScheme: 'light' },
  { suffix: 'desktop-dark', viewport: { width: 1024, height: 900 }, colorScheme: 'dark' },
  { suffix: '390-light', viewport: { width: 390, height: 844 }, colorScheme: 'light' },
] as const

test('emails: the branded submitter emails from Mailpit', async ({ browser }) => {
  const slug = (subject: string) =>
    subject
      .toLowerCase()
      .replace(/"[^"]*"/g, '')
      .replace(/[^a-z]+/g, '-')
      .replace(/^-|-$/g, '')
      .slice(0, 60)
  for (const message of prepared?.mail ?? []) {
    for (const variant of EMAIL_VARIANTS) {
      const context = await browser.newContext({
        viewport: variant.viewport,
        colorScheme: variant.colorScheme,
        isMobile: variant.suffix.startsWith('390'),
      })
      const page = await context.newPage()
      await page.setContent(message.HTML, { waitUntil: 'load' })
      await page.screenshot({
        path: join(emailDir, `mailpit-${slug(message.Subject)}-${variant.suffix}.png`),
        fullPage: true,
      })
      await context.close()
    }
  }
})
