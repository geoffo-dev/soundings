import { mkdirSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import type { Browser, Page } from '@playwright/test'

import { Api, uniqueSuffix, type Person } from '../tests/support/api'
import { disposePeople, links, Mailpit, signInAs, type Message } from '../tests/support/email'
import { expect, settled, signIn, test } from '../tests/support/fixtures'
import {
  conversation,
  messagesPart,
  messagesSheet,
  messagingTeam,
  sendPublicIdea,
  sendTeamMessage,
  trackedMessages,
  type MessagingTeam,
  type PublicIdea,
} from '../tests/support/messages'
import { fillPublicForm, humanCheckDone, Visitor } from '../tests/support/public'

/**
 * Review screenshots of the Phase 11 screens (talking to public submitters) from the real
 * app (API, worker, Mailpit) with the demo data. Not a regression test.
 *
 * `npm run screenshots:phase11` → docs/screenshots/phase-11/ (`SCREENSHOT_DIR` overrides):
 *
 * - <screen>-<1440-light|1440-dark|390-light>.png: the seeded CUST-21 (priya, Customer
 *   Innovation's admin, wrote to its sender, Sam Okafor, who replied): the submission
 *   panel's Messages, the conversation sheet with a message being written, and priya's
 *   inbox with "The submitter replied"; and, on a project of their own ("Home Delivery",
 *   HOME, archived afterwards; Nora Quinn, a new person, owns its ideas): the
 *   sheet for an unconfirmed address ("They won't get an email"), the tracking page
 *   with the conversation and the reply box, the receipt of an idea sent with an address,
 *   and the confirm page after a first confirmation ("We've emailed you a private link").
 * - emails/<type>-<desktop-light|desktop-dark|390-light>.png: the three new emails as
 *   Mailpit received them: the tracking link (`submission-link`), a message from the team
 *   (`submission-message`) and "The submitter replied" (`submitter-replied`).
 *
 * Needs freshly seeded data (the local stack reseeds on start) and SMTP (Mailpit).
 */

const here = dirname(fileURLToPath(import.meta.url))
const outDir = resolve(process.env.SCREENSHOT_DIR ?? join(here, '../../docs/screenshots/phase-11'))
const emailDir = join(outDir, 'emails')
mkdirSync(emailDir, { recursive: true })

const baseURL = () => test.info().project.use.baseURL ?? ''

test.describe.configure({ mode: 'serial' })

interface Arranged {
  alice: Api
  team: MessagingTeam
  visitor: Visitor
  confirmed: PublicIdea
  unconfirmed: PublicIdea
}

let arranged: Promise<Arranged> | undefined

async function arrange(): Promise<Arranged> {
  const alice = await Api.as(baseURL(), 'alice')
  const team = await messagingTeam(alice, 'Home Delivery', { exact: { key: 'HOME' } })
  const visitor = await Visitor.open(baseURL())
  const confirmed = await sendPublicIdea(alice, team, visitor, {
    title: 'Reusable delivery boxes with a deposit',
    summary:
      'Sturdy boxes the driver collects on the next delivery, with a small deposit refunded to the customer.',
    name: 'Sam Okafor',
    email: `sam.${uniqueSuffix()}@example.org`,
    confirm: true,
  })
  await sendTeamMessage(
    team.owner.api,
    confirmed.key,
    'Thanks, Sam! Which of our stores did you have in mind?\nWe’d like to try it in two first.',
  )
  await visitor.replied(
    confirmed.token,
    'The two in the city centre see the most deliveries. Happy to help with the trial.',
  )
  await sendTeamMessage(
    team.owner.api,
    confirmed.key,
    'Great, we’ll start there in November. Could you send us a photo of the boxes you use?',
  )
  const unconfirmed = await sendPublicIdea(alice, team, visitor, {
    title: 'A refill station for cleaning products',
    summary: 'Bring your own bottle and fill it with washing-up liquid or detergent by weight.',
    name: 'Ana Silva',
    email: `ana.${uniqueSuffix()}@example.org`,
  })
  await sendTeamMessage(team.owner.api, unconfirmed.key, 'Thanks, Ana! Where would it go?')
  return { alice, team, visitor, confirmed, unconfirmed }
}

function setUp(): Promise<Arranged> {
  arranged ??= arrange()
  return arranged
}

test.afterAll(async () => {
  if (!arranged) return
  const { alice, team, visitor } = await arranged
  await visitor.dispose()
  await disposePeople({ nora: team.owner, theo: team.member })
  await alice.archiveCreated()
  await alice.dispose()
})

interface Shot {
  name: string
  as?: Person
  open: (page: Page, phone: boolean) => Promise<void>
  fullPage?: boolean
}

const SHOTS: Shot[] = [
  {
    name: 'submission-panel-messages',
    as: 'priya',
    open: async (page, phone) => {
      await page.goto('/ideas/CUST-21')
      if (phone) await page.getByRole('button', { name: 'Details' }).click()
      await expect(messagesPart(page)).toContainText(/2 messages · They replied/)
      await messagesPart(page).scrollIntoViewIfNeeded()
    },
  },
  {
    name: 'messages-sheet-composer',
    as: 'priya',
    open: async (page) => {
      await page.goto('/ideas/CUST-21?submission=1')
      const sheet = messagesSheet(page, 'Sam Okafor')
      await expect(conversation(sheet)).toHaveCount(2)
      await sheet
        .getByRole('textbox', { name: 'Message to Sam Okafor' })
        .fill('Lovely, thank you. We’ll start in those two stores in November.')
    },
  },
  {
    name: 'inbox-submitter-replied',
    as: 'priya',
    open: async (page) => {
      await page.goto('/notifications')
      await expect(
        page.getByRole('link', {
          name: /The person who sent CUST-21 through the public form replied to the team/,
        }),
      ).toBeVisible()
    },
  },
  {
    name: 'messages-sheet-tracking-page-only',
    open: async (page) => {
      const { team, unconfirmed } = await setUp()
      await signInAs(page, team.owner)
      await page.goto(`/ideas/${unconfirmed.key}?submission=1`)
      const sheet = messagesSheet(page, 'Ana Silva')
      await expect(sheet).toContainText('They won’t get an email')
      await expect(conversation(sheet)).toHaveCount(1)
    },
  },
  {
    name: 'tracking-page-messages',
    fullPage: true,
    open: async (page) => {
      const { confirmed } = await setUp()
      await page.goto(`/track#${confirmed.token}`)
      const section = trackedMessages(page)
      await expect(conversation(section)).toHaveCount(3)
      await section
        .getByRole('textbox', { name: 'Reply to the team' })
        .fill('Of course, I’ll send one this evening.')
    },
  },
  {
    // The receipt for an idea sent with an address: the link follows the confirmation
    // (QA P11-QA-V4: Phase 4's receipt shot is sent without one).
    name: 'public-receipt-with-address',
    open: async (page) => {
      const { team } = await setUp()
      await page.goto(`/${team.project.slug}/submit`)
      await fillPublicForm(page, {
        title: 'Gift wrapping at the till',
        summary: 'Wrap presents in recycled paper while customers wait.',
        name: 'Finn',
        email: `finn.${uniqueSuffix()}@example.org`,
      })
      await humanCheckDone(page)
      await page.getByRole('button', { name: 'Send idea' }).click()
      await expect(page.getByText('Open the link we’ve just emailed you')).toBeVisible({
        timeout: 15_000,
      })
    },
  },
  {
    name: 'public-verify-link-emailed',
    open: async (page) => {
      const { team, visitor } = await setUp()
      const since = new Date()
      const email = `finn.${uniqueSuffix()}@example.org`
      await visitor.submitted(team.project.slug, {
        title: `A tote bag library ${uniqueSuffix()}`,
        summary: 'Borrow a bag at the till, bring it back next time.',
        email,
      })
      const message = await new Mailpit().waitForMessage(email, {
        since,
        subject: `Confirm your idea for ${team.project.name}`,
      })
      const link = links(message).find((href) => href.includes('/verify#'))
      if (!link) throw new Error('no confirmation link')
      await page.goto(link)
      await page.getByRole('button', { name: 'Confirm my email address' }).click()
      await expect(
        page.getByText('We’ve emailed you a private link to follow your idea.'),
      ).toBeVisible()
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
        test.setTimeout(90_000)
        if (shot.as) await signIn(page, shot.as)
        await shot.open(page, variant.phone)
        await shoot(page, join(outDir, `${shot.name}-${variant.suffix}.png`), shot.fullPage)
      })
    }
  })
}

async function shootEmail(browser: Browser, message: Message, name: string) {
  for (const variant of [
    { suffix: 'desktop-light', viewport: { width: 1000, height: 900 }, colorScheme: 'light' },
    { suffix: 'desktop-dark', viewport: { width: 1000, height: 900 }, colorScheme: 'dark' },
    { suffix: '390-light', viewport: { width: 390, height: 844 }, colorScheme: 'light' },
  ] as const) {
    const context = await browser.newContext({
      viewport: variant.viewport,
      colorScheme: variant.colorScheme,
      isMobile: variant.suffix.startsWith('390'),
    })
    const page = await context.newPage()
    await page.setContent(message.HTML, { waitUntil: 'load' })
    await page.screenshot({ path: join(emailDir, `${name}-${variant.suffix}.png`), fullPage: true })
    await context.close()
  }
}

test('emails: the tracking link, a message from the team and “The submitter replied”', async ({
  browser,
}) => {
  test.setTimeout(180_000)
  const alice = await Api.as(baseURL(), 'alice')
  try {
    test.skip(!(await alice.notificationSummary()).email_available, 'needs SMTP')
    test.skip(!(await new Mailpit().isUp()), 'needs the stack’s Mailpit')
  } finally {
    await alice.dispose()
  }
  const { team, confirmed } = await setUp()
  const mailpit = new Mailpit()
  const email = confirmed.email ?? ''
  const link = await mailpit.waitForMessage(email, {
    subject: `Your link to follow your idea for ${team.project.name}`,
  })
  await shootEmail(browser, link, 'submission-link')
  const message = await mailpit.waitForMessage(email, {
    subject: `A message about your idea for ${team.project.name}`,
  })
  await shootEmail(browser, message, 'submission-message')
  const replied = await mailpit.waitForMessage(team.owner.email, {
    subject: `[${confirmed.key}] The submitter replied`,
  })
  await shootEmail(browser, replied, 'submitter-replied')
})
