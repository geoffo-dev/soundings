import type { Page } from '@playwright/test'

import { Api, uniqueSuffix, type Person } from './support/api'
import { disposePeople, links, Mailpit, requireEmail } from './support/email'
import {
  bestPracticeViolations,
  expect,
  seriousViolations,
  settled,
  signIn,
  test,
} from './support/fixtures'
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
} from './support/messages'
import { Visitor } from './support/public'

/**
 * axe (WCAG 2.2 AA rules, serious and critical) on the screens Phase 11 changed, against
 * the real app, light and dark: the submission panel's Messages and the conversation sheet
 * as priya (Customer Innovation's admin, who wrote to the sender of the seeded CUST-21),
 * her inbox with "The submitter replied"; the public form's email help, the tracking page
 * with the conversation and the reply box, an unconfirmed address's line, the "Remove my
 * email address" dialog and the confirm page's new line, on a project of their own (Nora,
 * a new person, owns its ideas; nobody replies, so nobody seeded is notified). axe's
 * best-practice rules on the screens without overlays, in light; the same screens at
 * 390 px without sideways scrolling; the reply with the keyboard only. Test plan: A11Y11-*,
 * MO11-*, K11-*.
 */

interface Arranged {
  alice: Api
  team: MessagingTeam
  visitor: Visitor
  confirmed: PublicIdea
  unconfirmed: PublicIdea
}

let arranged: Promise<Arranged> | undefined

async function arrange(baseURL: string): Promise<Arranged> {
  const alice = await Api.as(baseURL, 'alice')
  const team = await messagingTeam(alice, 'Customer Innovation')
  const visitor = await Visitor.open(baseURL)
  const confirmed = await sendPublicIdea(alice, team, visitor, {
    title: `Reusable delivery boxes ${team.project.key}`,
    email: `sam.${uniqueSuffix()}@example.org`,
    confirm: true,
  })
  await sendTeamMessage(
    team.owner.api,
    confirmed.key,
    'Thanks, Sam! Which of our stores did you have in mind?\nWe’d like to try it in two first.',
  )
  const unconfirmed = await sendPublicIdea(alice, team, visitor, {
    title: `Refill station ${team.project.key}`,
    email: `ana.${uniqueSuffix()}@example.org`,
  })
  await sendTeamMessage(team.owner.api, unconfirmed.key, 'Thanks, Ana! Where would it go?')
  return { alice, team, visitor, confirmed, unconfirmed }
}

function setUp(): Promise<Arranged> {
  arranged ??= arrange(test.info().project.use.baseURL ?? '')
  return arranged
}

test.afterAll(async () => {
  if (!arranged) return
  const { alice, team, visitor } = await arranged
  await visitor.dispose()
  await disposePeople({ nora: team.owner, theo: team.member })
  await alice.archiveCreated()
  await alice.dispose()
  arranged = undefined
})

interface Screen {
  name: string
  /** Signed in as (null: signed out). */
  as: Person | null
  needsEmail?: boolean
  overlay?: boolean
  open: (page: Page) => Promise<void>
}

const SCREENS: Screen[] = [
  {
    name: 'the submission panel’s Messages (priya, CUST-21)',
    as: 'priya',
    open: async (page) => {
      await page.goto('/ideas/CUST-21')
      // On a phone the submission panel is in the Details sheet.
      if ((page.viewportSize()?.width ?? 1440) < 768) {
        await page.getByRole('button', { name: 'Details' }).click()
      }
      await expect(messagesPart(page)).toContainText(/2 messages · They replied/)
    },
  },
  {
    name: 'the conversation sheet with the composer',
    as: 'priya',
    overlay: true,
    open: async (page) => {
      await page.goto('/ideas/CUST-21?submission=1')
      const sheet = messagesSheet(page, 'Sam Okafor')
      await expect(conversation(sheet)).toHaveCount(2)
      await expect(sheet.getByRole('textbox', { name: 'Message to Sam Okafor' })).toBeVisible()
    },
  },
  {
    name: 'the inbox with “The submitter replied”',
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
    name: 'the public form with the email help',
    as: null,
    needsEmail: true,
    open: async (page) => {
      const { team } = await setUp()
      await page.goto(`/${team.project.slug}/submit`)
      await expect(page.getByText(/Only the team’s admins can see your address\./)).toBeVisible()
    },
  },
  {
    name: 'the tracking page with the conversation and the reply box',
    as: null,
    needsEmail: true,
    open: async (page) => {
      const { confirmed } = await setUp()
      await page.goto(`/track#${confirmed.token}`)
      await expect(conversation(trackedMessages(page)).first()).toBeVisible()
      await expect(
        trackedMessages(page).getByRole('textbox', { name: 'Reply to the team' }),
      ).toBeVisible()
    },
  },
  {
    name: 'the tracking page of an unconfirmed address',
    as: null,
    needsEmail: true,
    open: async (page) => {
      const { unconfirmed } = await setUp()
      await page.goto(`/track#${unconfirmed.token}`)
      await expect(trackedMessages(page)).toContainText('confirm your email address')
    },
  },
  {
    name: 'the “Remove my email address” dialog',
    as: null,
    needsEmail: true,
    overlay: true,
    open: async (page) => {
      const { confirmed } = await setUp()
      await page.goto(`/track#${confirmed.token}`)
      await page.getByRole('button', { name: 'Remove my email address' }).click()
      await expect(
        page.getByRole('alertdialog', { name: 'Remove your email address?' }),
      ).toBeVisible()
    },
  },
  {
    name: 'the confirm page after the first confirmation',
    as: null,
    needsEmail: true,
    open: async (page) => {
      const { team, visitor } = await setUp()
      const since = new Date()
      const email = `finn.${uniqueSuffix()}@example.org`
      await visitor.submitted(team.project.slug, {
        title: `Tote bags ${uniqueSuffix()}`,
        summary: 'Borrow a bag, bring it back.',
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

async function prepare(page: Page, screen: Screen) {
  if (screen.needsEmail) {
    const alice = await Api.as(test.info().project.use.baseURL ?? '', 'alice')
    try {
      await requireEmail(alice)
    } finally {
      await alice.dispose()
    }
  }
  if (screen.as) await signIn(page, screen.as)
  await screen.open(page)
  await settled(page)
}

for (const colorScheme of ['light', 'dark'] as const) {
  test.describe(`${colorScheme} theme`, () => {
    test.use({ colorScheme })

    for (const screen of SCREENS) {
      test(`A11Y11: ${screen.name} has no serious or critical violations`, async ({ page }) => {
        test.setTimeout(90_000)
        await prepare(page, screen)
        await expect(page.locator('html')).toHaveClass(
          colorScheme === 'dark' ? /\bdark\b/ : /^(?!.*\bdark\b)/,
        )
        await page.waitForTimeout(300) // enter animations: axe sees final colours
        expect(await seriousViolations(page)).toEqual([])
        if (!screen.overlay && colorScheme === 'light') {
          expect(await bestPracticeViolations(page)).toEqual([])
        }
      })
    }
  })
}

test.describe('on a phone (390 px)', () => {
  test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true })

  test('MO11-01: the Phase 11 screens fit without sideways scrolling', async ({ page }) => {
    test.setTimeout(240_000)
    const overflow = () =>
      page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      )
    for (const screen of SCREENS) {
      await prepare(page, screen)
      expect(await overflow(), screen.name).toBeLessThanOrEqual(0)
      expect(await seriousViolations(page), screen.name).toEqual([])
      await page.context().clearCookies()
    }
  })

  test('MO11-02: on a phone, Details → Open messages opens the conversation over the page', async ({
    page,
  }) => {
    await signIn(page, 'priya')
    await page.goto('/ideas/CUST-21')
    await page.getByRole('button', { name: 'Details' }).click()
    await page
      .getByRole('dialog', { name: 'Details' })
      .getByRole('button', { name: 'Open messages' })
      .click()
    const sheet = messagesSheet(page, 'Sam Okafor')
    await expect(sheet).toBeVisible()
    await expect(conversation(sheet)).toHaveCount(2)
    // Touch: the sheet itself takes focus, so the on-screen keyboard doesn't hide it.
    await expect(sheet.getByRole('textbox')).not.toBeFocused()
    // Closing goes back to Details, on its Open messages button (UX review p8).
    await page.keyboard.press('Escape')
    await expect(sheet).toBeHidden()
    const details = page.getByRole('dialog', { name: 'Details' })
    await expect(details.getByRole('button', { name: 'Open messages' })).toBeFocused()
  })
})

test('K11-01: the reply with the keyboard only: Tab to the box, Ctrl+Enter sends, focus stays', async ({
  page,
}) => {
  test.setTimeout(120_000)
  const alice = await Api.as(test.info().project.use.baseURL ?? '', 'alice')
  try {
    await requireEmail(alice)
  } finally {
    await alice.dispose()
  }
  const { confirmed, team } = await setUp()
  await page.goto(`/track#${confirmed.token}`)
  const section = trackedMessages(page)
  const box = section.getByRole('textbox', { name: 'Reply to the team' })
  await expect(box).toBeVisible()
  for (let tab = 0; tab < 40; tab += 1) {
    await page.keyboard.press('Tab')
    if (await box.evaluate((node) => node === document.activeElement)) break
  }
  await expect(box).toBeFocused()
  const before = await conversation(section).count()
  await page.keyboard.type('The two in the city centre.')
  await page.keyboard.press('Control+Enter')
  await expect(conversation(section)).toHaveCount(before + 1)
  await expect(box).toBeFocused()
  await expect(box).toHaveValue('')
  await expect(page.getByRole('status').filter({ hasText: 'Reply sent' })).toHaveCount(1)
  // The owner (a new person) is the one told, nobody seeded.
  await expect
    .poll(async () =>
      (await team.owner.api.notifications()).filter((item) => item.type === 'submitter_replied'),
    )
    .not.toHaveLength(0)
})
