import type { Page } from '@playwright/test'

import { expect, seriousViolations, test, USERS } from './support'

/**
 * Phase 3 screens (contract-phase3): no serious or critical axe violations in
 * light and dark, and every one fits a 390px phone without sideways scrolling.
 */

/** A mock unsubscribe token (src/mocks/notifications.ts `unsubscribeToken`). */
function token(userId: string, scope: string): string {
  const b64 = (text: string) =>
    Buffer.from(text, 'binary')
      .toString('base64')
      .replace(/\+/g, '-')
      .replace(/\//g, '_')
      .replace(/=+$/, '')
  const payload = b64(JSON.stringify({ v: 1, u: userId, s: scope }))
  let hash = 0x811c9dc5
  for (const char of `soundings/unsubscribe/v1:${payload}`) {
    hash ^= char.charCodeAt(0)
    hash = Math.imul(hash, 0x01000193) >>> 0
  }
  return `${payload}.${b64(`mock-${hash.toString(16)}`)}`
}

interface Target {
  name: string
  path: string
  user?: string | null
  ready: (page: Page) => Promise<void>
  /** localStorage knobs set before the page loads. */
  knobs?: Record<string, string>
}

const TARGETS: Target[] = [
  {
    name: 'bell popover',
    path: '/',
    ready: async (page) => {
      await page.getByRole('button', { name: /^Notifications/ }).click()
      await expect(page.getByRole('dialog', { name: 'Notifications' })).toBeVisible()
    },
  },
  {
    name: 'inbox page',
    path: '/notifications',
    ready: (page) => expect(page.getByRole('heading', { level: 2, name: 'Today' })).toBeVisible(),
  },
  {
    name: 'inbox page, nothing unread',
    path: '/notifications?unread=1',
    user: USERS.ivan,
    ready: (page) =>
      expect(page.getByRole('heading', { name: 'You’re all caught up' })).toBeVisible(),
  },
  {
    name: 'email preferences',
    path: '/settings/notifications',
    ready: (page) => expect(page.getByRole('radiogroup')).toHaveCount(7),
  },
  {
    name: 'email preferences without SMTP',
    path: '/settings/notifications',
    knobs: { 'soundings-mock-email': 'off' },
    ready: (page) => expect(page.getByText('Email isn’t set up on this server yet')).toBeVisible(),
  },
  {
    name: 'unsubscribe',
    path: `/unsubscribe?token=${token(USERS.alice, 'digest')}`,
    user: null,
    ready: (page) =>
      expect(page.getByRole('heading', { name: 'Stop the daily digest?' })).toBeVisible(),
  },
  {
    name: 'unsubscribe, done',
    path: `/unsubscribe?token=${token(USERS.alice, 'mention')}`,
    user: null,
    ready: async (page) => {
      await page.getByRole('button', { name: 'Unsubscribe', exact: true }).click()
      await expect(page.getByRole('heading', { name: 'You’re unsubscribed' })).toBeVisible()
    },
  },
  {
    name: 'unsubscribe, broken link',
    path: '/unsubscribe?token=not-a-real-token-at-all',
    user: null,
    ready: (page) =>
      expect(
        page.getByRole('heading', { name: 'This unsubscribe link doesn’t work' }),
      ).toBeVisible(),
  },
  {
    name: 'admin email',
    path: '/settings/email',
    user: USERS.priya,
    ready: (page) => expect(page.getByRole('table', { name: 'Outbox emails' })).toBeVisible(),
  },
  {
    name: 'admin email, SMTP down, test failed',
    path: '/settings/email?status=all',
    user: USERS.priya,
    knobs: { 'soundings-mock-email': 'failing' },
    ready: async (page) => {
      await page.getByRole('button', { name: 'Send test email' }).click()
      await expect(page.getByText('The test email failed')).toBeVisible({ timeout: 10_000 })
    },
  },
  {
    name: 'admin email without SMTP, with the banner',
    path: '/settings/sso',
    user: USERS.priya,
    knobs: { 'soundings-mock-email': 'off' },
    ready: (page) => expect(page.getByTestId('email-banner')).toBeVisible(),
  },
  {
    name: 'mention picker',
    path: '/ideas/CUST-2',
    ready: async (page) => {
      await page.getByRole('textbox', { name: 'Write a comment' }).click()
      await page.keyboard.type('@')
      await expect(page.getByRole('option').first()).toBeVisible()
    },
  },
]

async function visit(page: Page, target: Target) {
  if (target.knobs) {
    await page.addInitScript((knobs) => {
      for (const [key, value] of Object.entries(knobs)) localStorage.setItem(key, value)
    }, target.knobs)
  }
  await page.goto(target.path)
  await target.ready(page)
  await expect(page.locator('[data-slot="skeleton"]')).toHaveCount(0)
  // Let open/close animations settle before axe reads colours.
  await page.waitForTimeout(300)
}

for (const colorScheme of ['light', 'dark'] as const) {
  test.describe(`${colorScheme} mode`, () => {
    test.use({ colorScheme })
    for (const target of TARGETS) {
      test.describe(target.name, () => {
        if (target.user !== undefined) test.use({ signedInAs: target.user })
        test('has no serious accessibility violations', async ({ page }) => {
          await visit(page, target)
          expect(await seriousViolations(page)).toEqual([])
        })
      })
    }
  })
}

test.describe('on a phone (390px)', () => {
  test.use({ viewport: { width: 390, height: 844 } })

  for (const target of TARGETS) {
    test.describe(target.name, () => {
      if (target.user !== undefined) test.use({ signedInAs: target.user })
      test('fits without sideways scrolling', async ({ page }) => {
        await visit(page, target)
        const overflow = await page.evaluate(() => {
          const main = document.getElementById('main')
          return {
            page: document.documentElement.scrollWidth - window.innerWidth,
            main: main ? main.scrollWidth - main.clientWidth : 0,
          }
        })
        expect(overflow.page).toBeLessThanOrEqual(0)
        expect(overflow.main).toBeLessThanOrEqual(0)
      })
    })
  }
})
