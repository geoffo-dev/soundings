import { mkdirSync } from 'node:fs'
import path from 'node:path'

import type { Page } from '@playwright/test'

import { expect, test } from './support'

/**
 * Review screenshots of the idea page and the evaluate sheet against the MSW mock
 * (not a regression test). Run with `npm run screenshots` (every
 * *screenshots.spec.ts) or
 *   SCREENSHOTS=1 npx playwright test tests/idea-screenshots.spec.ts
 * Writes to ../docs/screenshots/phase-1/mock/ (or SCREENSHOT_DIR).
 */
test.skip(!process.env.SCREENSHOTS, 'Set SCREENSHOTS=1 to capture')

const outDir = path.resolve(process.env.SCREENSHOT_DIR ?? '../docs/screenshots/phase-1/mock')

type Scheme = 'light' | 'dark'
interface Shot {
  name: string
  path: string
  width: number
  height: number
  scheme: Scheme
  /** Extra steps after the page is ready. */
  act?: (page: Page) => Promise<void>
}

const CRITERIA = ['Value', 'Feasibility', 'Effort', 'Strategic fit', 'Risk']

async function scoreAll(page: Page, scores: string[]) {
  const sheet = page.getByRole('dialog', { name: 'Evaluate' })
  for (const [index, name] of CRITERIA.entries()) {
    await sheet
      .getByRole('radiogroup', { name })
      .getByRole('radio', { name: scores[index] ?? '3' })
      .click()
  }
}

const shots: Shot[] = [
  { name: 'idea-owner-1440', path: '/ideas/CUST-2', width: 1440, height: 900, scheme: 'light' },
  { name: 'idea-owner-1440', path: '/ideas/CUST-2', width: 1440, height: 900, scheme: 'dark' },
  { name: 'idea-blind-1440', path: '/ideas/CUST-1', width: 1440, height: 900, scheme: 'light' },
  {
    name: 'idea-evaluations-tab-1440',
    path: '/ideas/CUST-2?tab=evaluations',
    width: 1440,
    height: 900,
    scheme: 'light',
  },
  {
    name: 'idea-evaluate-sheet-1440',
    path: '/ideas/CUST-1?evaluate=1',
    width: 1440,
    height: 900,
    scheme: 'light',
    act: async (page) => {
      const sheet = page.getByRole('dialog', { name: 'Evaluate' })
      await sheet
        .getByRole('radiogroup', { name: 'Value' })
        .getByRole('radio', { name: '4' })
        .click()
      await sheet.getByRole('button', { name: 'Add a comment on Value' }).click()
      await sheet
        .getByRole('textbox', { name: 'Comment on Value (optional)' })
        .fill('Customers ask for this every week.')
      await expect(sheet.getByText(/^Draft saved/)).toBeVisible()
    },
  },
  {
    name: 'idea-evaluate-sheet-1440',
    path: '/ideas/CUST-1?evaluate=1',
    width: 1440,
    height: 900,
    scheme: 'dark',
    act: async (page) => {
      const sheet = page.getByRole('dialog', { name: 'Evaluate' })
      await sheet
        .getByRole('radiogroup', { name: 'Value' })
        .getByRole('radio', { name: '4' })
        .click()
      await sheet.getByRole('button', { name: 'Submit' }).click()
    },
  },
  {
    name: 'idea-evaluate-reveal-1440',
    path: '/ideas/CUST-1?evaluate=1',
    width: 1440,
    height: 900,
    scheme: 'light',
    act: async (page) => {
      await scoreAll(page, ['4', '3', '2', '5', '2'])
      const sheet = page.getByRole('dialog', { name: 'Evaluate' })
      await sheet
        .getByRole('radiogroup', { name: 'Overall recommendation' })
        .getByRole('radio', { name: 'Go' })
        .click()
      await sheet.getByRole('button', { name: 'Submit' }).click()
      await expect(page.getByRole('dialog', { name: 'Your evaluation' })).toBeVisible()
      await page.waitForTimeout(1200)
    },
  },
  { name: 'idea-390-mobile', path: '/ideas/CUST-1', width: 390, height: 844, scheme: 'light' },
  {
    name: 'idea-evaluate-390-mobile',
    path: '/ideas/CUST-1?evaluate=1',
    width: 390,
    height: 844,
    scheme: 'dark',
    act: async (page) => {
      const sheet = page.getByRole('dialog', { name: 'Evaluate' })
      await sheet.getByRole('radiogroup', { name: 'Value' }).getByRole('radio', { name: '4' }).tap()
    },
  },
  {
    name: 'idea-details-390-mobile',
    path: '/ideas/CUST-2',
    width: 390,
    height: 844,
    scheme: 'light',
    act: async (page) => {
      await page.getByRole('button', { name: 'Details' }).tap()
    },
  },
  {
    name: 'idea-not-found-1440',
    path: '/ideas/CUST-999',
    width: 1440,
    height: 900,
    scheme: 'light',
  },
]

for (const shot of shots) {
  const mobile = shot.width < 500
  test.describe(`${shot.name}-${shot.scheme}`, () => {
    test.use({
      colorScheme: shot.scheme,
      viewport: { width: shot.width, height: shot.height },
      ...(mobile ? { isMobile: true, hasTouch: true } : {}),
    })

    test('capture', async ({ page }) => {
      mkdirSync(outDir, { recursive: true })
      await page.goto(shot.path)
      // The page's h1 (hidden from the accessibility tree while a sheet is open), a
      // dialog, or the not-found text.
      await expect(
        page
          .locator('main h1, [role="dialog"]')
          .or(page.getByText(/doesn’t exist/))
          .first(),
      ).toBeVisible()
      await shot.act?.(page)
      await page.evaluate(() => document.fonts.ready)
      await page.waitForTimeout(500)
      await page.screenshot({ path: path.join(outDir, `${shot.name}-${shot.scheme}.png`) })
    })
  })
}
