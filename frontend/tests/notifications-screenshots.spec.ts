import { mkdirSync } from 'node:fs'
import path from 'node:path'

import type { Page } from '@playwright/test'

import { expect, test, USERS } from './support'

/**
 * Phase 3 review screenshots against the MSW mock (not a regression test): the
 * bell and inbox, email preferences, the unsubscribe page, Admin → Email, the
 * admin banner and the mention picker.
 *   SCREENSHOTS=1 npx playwright test notifications-screenshots   # → ../docs/screenshots/phase-3/mock/
 *   SCREENSHOT_DIR=… to write elsewhere
 */
test.skip(!process.env.SCREENSHOTS, 'Set SCREENSHOTS=1 (npm run screenshots) to capture')

const outDir = path.resolve(process.env.SCREENSHOT_DIR ?? '../docs/screenshots/phase-3/mock')
if (process.env.SCREENSHOTS) mkdirSync(outDir, { recursive: true })

const VIEWPORTS = {
  desktop: { width: 1440, height: 900 },
  phone: { width: 390, height: 844 },
} as const

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

interface Shot {
  name: string
  url: string
  user?: string | null
  knobs?: Record<string, string>
  ready: (page: Page) => Promise<void>
}

const SHOTS: Shot[] = [
  {
    name: 'p3-bell-inbox',
    url: '/',
    ready: async (page) => {
      await page.getByRole('button', { name: /^Notifications/ }).click()
      await expect(page.getByRole('dialog', { name: 'Notifications' })).toBeVisible()
    },
  },
  {
    name: 'p3-notifications-page',
    url: '/notifications',
    ready: (page) => expect(page.getByRole('heading', { level: 2, name: 'Today' })).toBeVisible(),
  },
  {
    name: 'p3-email-preferences',
    url: '/settings/notifications',
    ready: (page) => expect(page.getByRole('radiogroup')).toHaveCount(7),
  },
  {
    name: 'p3-unsubscribe',
    url: `/unsubscribe?token=${token(USERS.alice, 'evaluation_reminder')}`,
    user: null,
    ready: (page) =>
      expect(page.getByRole('button', { name: 'Unsubscribe', exact: true })).toBeVisible(),
  },
  {
    name: 'p3-admin-email',
    url: '/settings/email',
    user: USERS.priya,
    ready: (page) => expect(page.getByRole('table', { name: 'Outbox emails' })).toBeVisible(),
  },
  {
    name: 'p3-admin-email-smtp-down',
    url: '/settings/email',
    user: USERS.priya,
    knobs: { 'soundings-mock-email': 'failing' },
    ready: async (page) => {
      await page.getByRole('textbox', { name: 'Send to' }).fill('ops@example.com')
      await page.getByRole('button', { name: 'Send test email' }).click()
      await expect(page.getByText('The test email failed')).toBeVisible({ timeout: 10_000 })
    },
  },
  {
    name: 'p3-admin-banner-no-smtp',
    url: '/',
    user: USERS.priya,
    knobs: { 'soundings-mock-email': 'off' },
    ready: (page) => expect(page.getByTestId('email-banner')).toBeVisible(),
  },
  {
    name: 'p3-mention-picker',
    url: '/ideas/CUST-2',
    ready: async (page) => {
      await page.getByRole('textbox', { name: 'Write a comment' }).click()
      await page.keyboard.type('Thanks @ca')
      await expect(page.getByRole('option', { name: /Carol Díaz/ })).toBeVisible()
    },
  },
]

const VARIANTS = [
  ['1440-light', 'desktop', 'light'],
  ['1440-dark', 'desktop', 'dark'],
  ['390-mobile-light', 'phone', 'light'],
] as const

for (const shot of SHOTS) {
  test.describe(shot.name, () => {
    if (shot.user !== undefined) test.use({ signedInAs: shot.user })
    for (const [suffix, viewport, colorScheme] of VARIANTS) {
      test(suffix, async ({ page }) => {
        if (shot.knobs) {
          await page.addInitScript((knobs) => {
            for (const [key, value] of Object.entries(knobs)) localStorage.setItem(key, value)
          }, shot.knobs)
        }
        await page.emulateMedia({ colorScheme })
        await page.setViewportSize(VIEWPORTS[viewport])
        await page.goto(shot.url)
        await shot.ready(page)
        await expect(page.locator('[data-slot="skeleton"]')).toHaveCount(0)
        await page.evaluate(() => document.fonts.ready)
        await page.waitForTimeout(400)
        await page.screenshot({ path: path.join(outDir, `${shot.name}-${suffix}.png`) })
      })
    }
  })
}
