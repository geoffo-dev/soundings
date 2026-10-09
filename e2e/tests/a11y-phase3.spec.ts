import type { Page } from '@playwright/test'

import { Api, daysFromNow } from './support/api'
import { emailTo, newPeople, projectWithIdea, unsubscribeLink, Mailpit } from './support/email'
import { expect, heading, seriousViolations, settled, signIn, test } from './support/fixtures'

/**
 * axe (WCAG 2.2 AA rules) on the Phase 3 screens against the real app, light and dark:
 * no serious or critical violations. Then the same screens at 390 px: no sideways
 * scrolling, and the bell opens a full-height sheet. Read-only on the seeded story
 * (Alice's inbox, Customer Innovation); the unsubscribe page uses a real link from an
 * email to a new person. Test plan: A11Y3-* and MO3-*.
 */

const baseURL = () => test.info().project.use.baseURL ?? ''
const h2 = (page: Page, name: string) => page.getByRole('heading', { level: 2, name })

let unsubscribeUrl: Promise<string | null> | undefined

/** A real unsubscribe link (an invitation to a new person), once per worker; null without email. */
function realUnsubscribeLink(): Promise<string | null> {
  unsubscribeUrl ??= (async () => {
    const alice = await Api.as(baseURL(), 'alice')
    try {
      const email = await alice.notificationSummary()
      if (!email.email_available || !(await new Mailpit().isUp())) return null
      const { theo } = await newPeople(alice, ['theo'])
      const { key } = await projectWithIdea(alice, 'A11y unsubscribe', [theo])
      const since = new Date()
      await alice.inviteUsers(key, [theo.user], daysFromNow(3))
      const mail = await emailTo(theo, /Please evaluate/, since)
      await theo.api.dispose()
      await alice.archiveCreated()
      return new URL(unsubscribeLink(mail)).pathname + new URL(unsubscribeLink(mail)).search
    } finally {
      await alice.dispose()
    }
  })()
  return unsubscribeUrl
}

interface Screen {
  name: string
  signedIn: boolean
  open: (page: Page) => Promise<void>
}

const SCREENS: Screen[] = [
  {
    name: 'notifications: the inbox page',
    signedIn: true,
    open: async (page) => {
      await page.goto('/notifications')
      await expect(heading(page, 'Notifications')).toBeVisible()
      await expect(
        page
          .locator('main')
          .getByRole('link', { name: /CUST-|TOOLS-|GREEN-/ })
          .first(),
      ).toBeVisible()
    },
  },
  {
    name: 'notifications: the bell’s popover',
    signedIn: true,
    open: async (page) => {
      await page.goto('/')
      await expect(heading(page, 'My work')).toBeVisible()
      await page.getByRole('button', { name: /^Notifications/ }).click()
      const panel = page.getByRole('dialog', { name: 'Notifications' })
      await expect(panel.getByRole('link', { name: /CUST-|TOOLS-|GREEN-/ }).first()).toBeVisible()
    },
  },
  {
    name: 'settings: notifications (email preferences)',
    signedIn: true,
    open: async (page) => {
      await page.goto('/settings/notifications')
      await expect(h2(page, 'Notifications')).toBeVisible()
      await expect(page.getByRole('radiogroup')).toHaveCount(9)
    },
  },
  {
    name: 'settings: email (admin) with the whole outbox',
    signedIn: true,
    open: async (page) => {
      await page.goto('/settings/email?status=all')
      await expect(h2(page, 'Email')).toBeVisible()
      await settled(page)
    },
  },
  {
    name: 'idea page: the mention picker open',
    signedIn: true,
    open: async (page) => {
      // (Not openIdea: on a phone the details sidebar is folded away.)
      await page.goto('/ideas/CUST-2')
      await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
      await settled(page)
      await page.getByRole('textbox', { name: 'Write a comment' }).click()
      await page.keyboard.type('Thanks @')
      await expect(
        page.getByRole('listbox', { name: 'People to mention' }).getByRole('option').first(),
      ).toBeVisible()
    },
  },
  {
    name: 'unsubscribe: a real link from an email',
    signedIn: false,
    open: async (page) => {
      const link = await realUnsubscribeLink()
      test.skip(!link, 'needs email (E2E_SMTP=1) to get a real link')
      await page.goto(link ?? '')
      await expect(page.getByRole('button', { name: 'Unsubscribe', exact: true })).toBeVisible()
    },
  },
  {
    name: 'unsubscribe: a link that doesn’t work',
    signedIn: false,
    open: async (page) => {
      await page.goto('/unsubscribe?token=this-link-was-cut-short')
      await expect(
        page.getByRole('heading', { level: 1, name: 'This unsubscribe link doesn’t work' }),
      ).toBeVisible()
    },
  },
]

for (const colorScheme of ['light', 'dark'] as const) {
  test.describe(`${colorScheme} theme`, () => {
    test.use({ colorScheme })

    for (const screen of SCREENS) {
      test(`A11Y3: ${screen.name} has no serious or critical violations`, async ({ page }) => {
        if (screen.signedIn) await signIn(page, 'alice')
        await screen.open(page)
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

  test('MO3-01: the Phase 3 screens fit without sideways scrolling', async ({ page }) => {
    const overflow = () =>
      page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      )
    for (const screen of SCREENS) {
      if (screen.name.includes('popover')) continue // a sheet on phones: MO3-02
      await test.step(screen.name, async () => {
        await page.context().clearCookies()
        if (screen.name.startsWith('unsubscribe: a real') && !(await realUnsubscribeLink())) return
        if (screen.signedIn) await signIn(page, 'alice')
        await screen.open(page)
        await page.waitForTimeout(200)
        expect(await overflow(), screen.name).toBe(0)
      })
    }
  })

  test('MO3-02: the bell opens a full-height sheet; “See all” leads to the inbox page', async ({
    page,
  }) => {
    await signIn(page, 'alice')
    await page.goto('/')
    await expect(heading(page, 'My work')).toBeVisible()
    await page.getByRole('button', { name: /^Notifications/ }).click()
    const sheet = page.getByRole('dialog', { name: 'Notifications' })
    await expect(sheet).toBeVisible()
    expect((await sheet.boundingBox())?.height ?? 0).toBeGreaterThan(780)
    expect(await seriousViolations(page)).toEqual([])
    await sheet.getByRole('link', { name: 'See all notifications' }).click()
    await expect(page).toHaveURL(/\/notifications$/)
    await expect(sheet).toBeHidden()
  })
})
