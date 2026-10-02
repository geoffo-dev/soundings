import { mkdirSync } from 'node:fs'
import path from 'node:path'

import type { Page } from '@playwright/test'

import { expect, test, USERS } from './support'

/**
 * Review screenshots of the public pages, branding settings and moderation
 * against the MSW mock (not a regression test). Run with `npm run screenshots`
 * (every *screenshots.spec.ts) or
 *   SCREENSHOTS=1 npx playwright test tests/public-screenshots.spec.ts
 * Writes to ../docs/screenshots/phase-4/mock/ (or SCREENSHOT_DIR).
 */
test.skip(!process.env.SCREENSHOTS, 'Set SCREENSHOTS=1 to capture')

const outDir = path.resolve(process.env.SCREENSHOT_DIR ?? '../docs/screenshots/phase-4/mock')

type Scheme = 'light' | 'dark'
interface Shot {
  name: string
  path: string
  width: number
  height?: number
  schemes?: Scheme[]
  /** null: signed out (the public pages). */
  user?: string | null
  /** Capture the whole page, not just the viewport. */
  fullPage?: boolean
  ready: (page: Page) => Promise<unknown>
  act?: (page: Page) => Promise<void>
}

/** Fixture tokens (src/mocks/phase4-fixtures.ts). */
const token = (name: string) => `track${name}`.padEnd(43, 'x')
const JO = token('JoMarshGreen9')
const UNCONFIRMED = token('ConfirmFirstGreen12')
const CONFIRM_LINK = 'v1.e0000000-0000-4000-8000-0000000f0004'

const h1 = (page: Page) => page.getByRole('heading', { level: 1 }).first().waitFor()

async function fillAndSend(page: Page) {
  await page.getByRole('textbox', { name: /^Title/ }).fill('Print-free returns')
  await page
    .getByRole('textbox', { name: /^Summary/ })
    .fill('Let people return parcels with a QR code instead of a printed label.')
  await page.getByRole('textbox', { name: /^Your email/ }).fill('jo@example.org')
  await page.getByRole('status').filter({ hasText: 'Verified you’re human' }).waitFor({
    timeout: 30_000,
  })
  await page.getByRole('button', { name: /Send idea/ }).click()
  await page.getByRole('heading', { name: 'Thanks! Your idea is in' }).waitFor()
}

const shots: Shot[] = [
  // --- The public form -------------------------------------------------------------
  {
    name: 'public-form-1440',
    path: '/sustainability/submit',
    width: 1440,
    height: 1100,
    schemes: ['light', 'dark'],
    user: null,
    fullPage: true,
    ready: h1,
  },
  {
    name: 'public-form-default-branding-1440',
    path: '/customer-innovation/submit',
    width: 1440,
    height: 1100,
    user: null,
    fullPage: true,
    ready: h1,
  },
  {
    name: 'public-form-390',
    path: '/sustainability/submit',
    width: 390,
    height: 844,
    schemes: ['light', 'dark'],
    user: null,
    fullPage: true,
    ready: h1,
  },
  {
    name: 'public-form-errors-390',
    path: '/sustainability/submit',
    width: 390,
    height: 844,
    user: null,
    ready: h1,
    act: async (page) => {
      await page.getByRole('textbox', { name: /^Summary/ }).fill('Only a summary')
      await page.getByRole('button', { name: /Send idea/ }).click()
    },
  },
  {
    name: 'public-form-verifying-390',
    path: '/customer-innovation/submit',
    width: 390,
    height: 844,
    user: null,
    ready: h1,
    act: async (page) => {
      await page.getByRole('textbox', { name: /^Title/ }).fill('Print-free returns')
      await page
        .getByRole('status')
        .filter({ hasText: /Verified|Checking/ })
        .waitFor()
      await page
        .getByRole('status')
        .filter({ hasText: /Verified/ })
        .scrollIntoViewIfNeeded()
    },
  },
  {
    name: 'public-receipt-1440',
    path: '/customer-innovation/submit',
    width: 1440,
    height: 900,
    schemes: ['light', 'dark'],
    user: null,
    ready: h1,
    act: fillAndSend,
  },
  {
    name: 'public-receipt-390',
    path: '/sustainability/submit',
    width: 390,
    height: 844,
    user: null,
    fullPage: true,
    ready: h1,
    act: async (page) => {
      await page.getByRole('textbox', { name: /^Title/ }).fill('Print-free returns')
      await page
        .getByRole('textbox', { name: /^Summary/ })
        .fill('Let people return parcels with a QR code instead of a printed label.')
      await page.getByRole('textbox', { name: /^Your email/ }).fill('jo@example.org')
      await page.getByRole('status').filter({ hasText: 'Verified you’re human' }).waitFor({
        timeout: 30_000,
      })
      await page.getByRole('button', { name: /Send idea/ }).click()
      await page.getByRole('textbox', { name: 'Your private link' }).waitFor()
    },
  },
  {
    name: 'public-form-unavailable-390',
    path: '/internal-tools/submit',
    width: 390,
    height: 844,
    user: null,
    ready: h1,
  },
  // --- Tracking and confirmation -----------------------------------------------------
  {
    name: 'track-1440',
    path: `/track#${JO}`,
    width: 1440,
    height: 1000,
    schemes: ['light', 'dark'],
    user: null,
    fullPage: true,
    ready: h1,
  },
  {
    name: 'track-390',
    path: `/track#${JO}`,
    width: 390,
    height: 844,
    schemes: ['light', 'dark'],
    user: null,
    fullPage: true,
    ready: h1,
  },
  {
    name: 'track-unconfirmed-390',
    path: `/track#${UNCONFIRMED}`,
    width: 390,
    height: 844,
    user: null,
    fullPage: true,
    ready: h1,
  },
  {
    name: 'track-delete-details-390',
    path: `/track#${JO}`,
    width: 390,
    height: 844,
    user: null,
    ready: h1,
    act: async (page) => {
      await page.getByRole('button', { name: 'Delete my details' }).click()
      await page.getByRole('alertdialog').waitFor()
    },
  },
  {
    name: 'track-not-found-390',
    path: `/track#${token('NoSuchSubmission')}`,
    width: 390,
    height: 844,
    user: null,
    ready: h1,
  },
  {
    name: 'verify-1440',
    path: `/verify#${CONFIRM_LINK}`,
    width: 1440,
    height: 800,
    schemes: ['light', 'dark'],
    user: null,
    ready: h1,
  },
  {
    name: 'verify-confirmed-390',
    path: `/verify#${CONFIRM_LINK}`,
    width: 390,
    height: 844,
    user: null,
    ready: h1,
    act: async (page) => {
      await page.getByRole('button', { name: 'Confirm my email address' }).click()
      await page.getByRole('heading', { name: 'Thanks, your address is confirmed' }).waitFor()
    },
  },
  // --- Branding settings --------------------------------------------------------------
  {
    name: 'branding-global-1440',
    path: '/settings/branding',
    width: 1440,
    height: 1200,
    schemes: ['light', 'dark'],
    user: USERS.priya,
    fullPage: true,
    ready: (page) => page.getByRole('button', { name: /Save branding/ }).waitFor(),
  },
  {
    name: 'branding-global-editing-1440',
    path: '/settings/branding',
    width: 1440,
    height: 1200,
    user: USERS.priya,
    fullPage: true,
    ready: (page) => page.getByRole('button', { name: /Save branding/ }).waitFor(),
    act: async (page) => {
      await page.getByLabel('App name').fill('Acme Ideas')
      await page.getByRole('button', { name: 'Amber (#b45309)' }).first().click()
      await page.getByRole('radio', { name: /IBM Plex Sans/ }).click()
      await page.getByLabel('Email footer').fill('Acme Ltd · 1 High Street · London')
    },
  },
  {
    name: 'branding-global-email-preview-1440',
    path: '/settings/branding',
    width: 1440,
    height: 1000,
    user: USERS.priya,
    ready: (page) => page.getByRole('button', { name: /Save branding/ }).waitFor(),
    act: async (page) => {
      await page.getByLabel('Email footer').fill('Acme Ltd · 1 High Street · London')
      await page.getByRole('tab', { name: 'Email' }).click()
    },
  },
  {
    name: 'branding-global-390',
    path: '/settings/branding',
    width: 390,
    height: 844,
    schemes: ['light', 'dark'],
    user: USERS.priya,
    fullPage: true,
    ready: (page) => page.getByRole('button', { name: /Save branding/ }).waitFor(),
  },
  {
    name: 'branding-project-1440',
    path: '/p/sustainability/settings?tab=branding',
    width: 1440,
    height: 1200,
    user: USERS.priya,
    fullPage: true,
    ready: (page) => page.getByRole('button', { name: /Save branding/ }).waitFor(),
  },
  {
    name: 'public-form-settings-1440',
    path: '/p/sustainability/settings?tab=public-form',
    width: 1440,
    height: 1000,
    schemes: ['light', 'dark'],
    user: USERS.priya,
    fullPage: true,
    ready: (page) => page.getByRole('switch', { name: /Accept ideas/ }).waitFor(),
  },
  {
    name: 'public-form-settings-390',
    path: '/p/sustainability/settings?tab=public-form',
    width: 390,
    height: 844,
    user: USERS.priya,
    fullPage: true,
    ready: (page) => page.getByRole('switch', { name: /Accept ideas/ }).waitFor(),
  },
  // --- Moderation ---------------------------------------------------------------------
  {
    name: 'moderation-board-notice-1440',
    path: '/p/sustainability',
    width: 1440,
    height: 900,
    user: USERS.priya,
    ready: (page) => page.getByText(/waiting for review/).waitFor(),
  },
  {
    name: 'moderation-queue-1440',
    path: '/p/sustainability/review',
    width: 1440,
    height: 900,
    schemes: ['light', 'dark'],
    user: USERS.priya,
    ready: (page) => page.getByRole('list', { name: 'Ideas waiting for review' }).waitFor(),
  },
  {
    name: 'moderation-queue-390',
    path: '/p/sustainability/review',
    width: 390,
    height: 844,
    schemes: ['light', 'dark'],
    user: USERS.priya,
    fullPage: true,
    ready: (page) => page.getByRole('list', { name: 'Ideas waiting for review' }).waitFor(),
  },
  {
    name: 'moderation-approved-undo-1440',
    path: '/p/sustainability/review',
    width: 1440,
    height: 900,
    user: USERS.priya,
    ready: (page) => page.getByRole('list', { name: 'Ideas waiting for review' }).waitFor(),
    act: async (page) => {
      await page
        .getByRole('button', { name: /^Approve GREEN-/ })
        .first()
        .click()
      await page.getByRole('button', { name: 'Undo' }).waitFor()
    },
  },
  {
    name: 'moderation-empty-1440',
    path: '/p/customer-innovation/review',
    width: 1440,
    height: 700,
    user: USERS.priya,
    ready: (page) =>
      page
        .getByRole('heading', { name: /Nothing waiting|waiting/ })
        .first()
        .waitFor(),
  },
  {
    name: 'idea-held-1440',
    path: '/ideas/GREEN-10',
    width: 1440,
    height: 900,
    schemes: ['light', 'dark'],
    user: USERS.priya,
    ready: (page) => page.getByRole('region', { name: 'Waiting for review' }).waitFor(),
  },
  {
    name: 'idea-held-390',
    path: '/ideas/GREEN-10',
    width: 390,
    height: 844,
    user: USERS.priya,
    ready: (page) => page.getByRole('region', { name: 'Waiting for review' }).waitFor(),
  },
  {
    name: 'idea-public-submission-1440',
    path: '/ideas/GREEN-9',
    width: 1440,
    height: 900,
    user: USERS.priya,
    ready: (page) => page.getByRole('heading', { name: 'Public form' }).waitFor(),
  },
  {
    name: 'idea-erase-submitter-1440',
    path: '/ideas/GREEN-9',
    width: 1440,
    height: 900,
    user: USERS.priya,
    ready: (page) => page.getByRole('heading', { name: 'Public form' }).waitFor(),
    act: async (page) => {
      await page.getByRole('button', { name: /Erase submitter details/ }).click()
      await page.getByRole('alertdialog').waitFor()
    },
  },
]

for (const shot of shots) {
  for (const scheme of shot.schemes ?? ['light']) {
    test.describe(`${shot.name} (${scheme})`, () => {
      test.use({
        viewport: { width: shot.width, height: shot.height ?? 900 },
        colorScheme: scheme,
        ...(shot.user !== undefined ? { signedInAs: shot.user } : {}),
      })
      test('capture', async ({ page }) => {
        test.setTimeout(90_000)
        mkdirSync(outDir, { recursive: true })
        await page.goto(shot.path)
        await shot.ready(page)
        await page.waitForLoadState('networkidle')
        await shot.act?.(page)
        await page.waitForTimeout(400)
        await expect(page.locator('body')).toBeVisible()
        await page.screenshot({
          path: path.join(outDir, `${shot.name}-${scheme}.png`),
          fullPage: shot.fullPage ?? false,
        })
      })
    })
  }
}
