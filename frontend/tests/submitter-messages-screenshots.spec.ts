import { mkdirSync } from 'node:fs'
import path from 'node:path'

import type { Page } from '@playwright/test'

import { expect, test, USERS } from './support'

/**
 * Review screenshots of the Phase 11 screens against the MSW mock (not a regression
 * test): the submission panel's Messages for the owner, the conversation sheet (emailed,
 * tracking page only, erased), the same idea for a member (nothing), the review queue's
 * "They replied", the inbox item, the tracking page with messages and the reply box,
 * "Remove my email address", the confirm page and Project settings → Public form. Run with
 *   SCREENSHOTS=1 npx playwright test tests/submitter-messages-screenshots.spec.ts
 * Writes to ../docs/screenshots/phase-11/mock/ (or SCREENSHOT_DIR).
 */
test.skip(!process.env.SCREENSHOTS, 'Set SCREENSHOTS=1 to capture')

const outDir = path.resolve(process.env.SCREENSHOT_DIR ?? '../docs/screenshots/phase-11/mock')
const token = (name: string) => `track${name}`.padEnd(43, 'x')

type Scheme = 'light' | 'dark'
interface Shot {
  name: string
  path: string
  user?: string | null
  ready: (page: Page) => Promise<void>
  act?: (page: Page) => Promise<void>
}

const noSkeletons = async (page: Page) => {
  await expect(page.locator('[data-slot="skeleton"]')).toHaveCount(0, { timeout: 15_000 })
}
const heading = (name: string) => async (page: Page) => {
  await expect(page.getByRole('heading', { name }).first()).toBeVisible({ timeout: 15_000 })
  await noSkeletons(page)
}
/** The idea's details: the sidebar, or on a phone the Details sheet. */
const details = (name: string) => async (page: Page) => {
  const width = page.viewportSize()?.width ?? 1440
  if (width < 1024) await page.getByRole('button', { name: 'Details' }).click()
  await expect(page.getByRole('heading', { name }).last()).toBeVisible()
}
const ideaReady = async (page: Page) => {
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible({ timeout: 15_000 })
  await noSkeletons(page)
}
const conversation = (title: string) => async (page: Page) => {
  await expect(page.getByRole('dialog', { name: title })).toBeVisible({ timeout: 15_000 })
  await noSkeletons(page)
}

const SHOTS: Shot[] = [
  {
    name: 'panel-owner',
    path: '/ideas/GREEN-13',
    user: USERS.grace,
    ready: ideaReady,
    act: details('Messages'),
  },
  {
    name: 'sheet-emailed',
    path: '/ideas/GREEN-13?submission=1',
    user: USERS.grace,
    ready: conversation('Messages with Sam Okafor'),
  },
  {
    name: 'sheet-tracking-page-only',
    path: '/ideas/GREEN-14?submission=1',
    user: USERS.carol,
    ready: conversation('Messages with Ana Ruiz'),
  },
  {
    name: 'sheet-erased',
    path: '/ideas/GREEN-15?submission=1',
    user: USERS.grace,
    ready: conversation('Messages with the submitter'),
  },
  {
    name: 'panel-member',
    path: '/ideas/GREEN-13',
    ready: ideaReady,
    act: details('Public form'),
  },
  {
    name: 'review-queue-replied',
    path: '/p/sustainability/review',
    user: USERS.carol,
    ready: heading('Review new ideas'),
  },
  {
    name: 'inbox-submitter-replied',
    path: '/notifications',
    user: USERS.carol,
    ready: heading('Notifications'),
  },
  {
    name: 'track-messages',
    path: `/track#${token('SamOkaforGreen13')}`,
    user: null,
    ready: heading('Messages'),
  },
  {
    name: 'track-messages-unconfirmed',
    path: `/track#${token('AnaRuizGreen14')}`,
    user: null,
    ready: heading('Messages'),
  },
  {
    name: 'track-remove-email',
    path: `/track#${token('SamOkaforGreen13')}`,
    user: null,
    ready: heading('Messages'),
    act: async (page) => {
      await page.getByRole('button', { name: 'Remove my email address' }).click()
      await expect(page.getByRole('alertdialog')).toBeVisible()
    },
  },
  {
    name: 'verify-link-emailed',
    path: '/sustainability/verify#v1.e0000000-0000-4000-8000-0000000f0004',
    user: null,
    ready: heading('Confirm your email address'),
    act: async (page) => {
      await page.getByRole('button', { name: 'Confirm my email address' }).click()
      await expect(page.getByRole('heading', { name: /address is confirmed/ })).toBeVisible()
    },
  },
  {
    name: 'settings-public-form',
    path: '/p/sustainability/settings?tab=public-form',
    user: USERS.carol,
    ready: heading('Public form'),
  },
  {
    name: 'preferences',
    path: '/settings/notifications',
    user: USERS.grace,
    ready: heading('Notifications'),
  },
]

const VARIANTS: { suffix: string; scheme: Scheme; width: number; height: number }[] = [
  { suffix: '1440-light', scheme: 'light', width: 1440, height: 1000 },
  { suffix: '1440-dark', scheme: 'dark', width: 1440, height: 1000 },
  { suffix: '390-light', scheme: 'light', width: 390, height: 844 },
]

test.describe.configure({ mode: 'parallel' })

for (const shot of SHOTS) {
  for (const variant of VARIANTS) {
    test.describe(`${shot.name} ${variant.suffix}`, () => {
      if (shot.user !== undefined) test.use({ signedInAs: shot.user })
      test('capture', async ({ page }) => {
        mkdirSync(outDir, { recursive: true })
        await page.emulateMedia({ colorScheme: variant.scheme })
        await page.setViewportSize({ width: variant.width, height: variant.height })
        await page.goto(shot.path)
        await shot.ready(page)
        await shot.act?.(page)
        await page.waitForTimeout(300)
        await page.screenshot({
          path: path.join(outDir, `${shot.name}-${variant.suffix}.png`),
          fullPage: !shot.path.includes('submission=1'),
        })
      })
    })
  }
}
