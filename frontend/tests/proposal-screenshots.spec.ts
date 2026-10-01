import { mkdirSync } from 'node:fs'
import path from 'node:path'

import type { Page } from '@playwright/test'

import { expect, test, USERS } from './support'

/**
 * Review screenshots of the proposal editor against the MSW mock (not a
 * regression test). Run with `npm run screenshots` (every *screenshots.spec.ts)
 * or
 *   SCREENSHOTS=1 npx playwright test tests/proposal-screenshots.spec.ts
 * Writes to ../docs/screenshots/phase-4/mock/ (or SCREENSHOT_DIR).
 */
test.skip(!process.env.SCREENSHOTS, 'Set SCREENSHOTS=1 to capture')

const outDir = path.resolve(process.env.SCREENSHOT_DIR ?? '../docs/screenshots/phase-4/mock')

type Scheme = 'light' | 'dark'
interface Shot {
  name: string
  path: string
  width: number
  height: number
  scheme: Scheme
  user?: string
  act?: (page: Page) => Promise<void>
}

/** Someone else saves the Summary, then Alice types: the conflict prompt. */
async function conflict(page: Page) {
  await page.getByRole('textbox', { name: 'Summary' }).waitFor()
  await page.evaluate(async () => {
    await fetch('/api/v1/ideas/CUST-3/proposal/sections/summary', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': 'playwright' },
      body: JSON.stringify({
        body_md:
          'A monthly curated box for existing customers, starting with **coffee and tea**.\n\nWe expect it to lift repeat purchases by 6%.',
        base_version: 3,
      }),
    })
  })
  const box = page.getByRole('textbox', { name: 'Summary' })
  await box.click()
  await box.press('End')
  await page.keyboard.type(' Boxes ship on the first Monday.')
  await page.getByRole('button', { name: 'Keep mine' }).waitFor()
}

const shots: Shot[] = [
  {
    name: 'proposal-owner-1440',
    path: '/ideas/CUST-3?tab=proposal',
    width: 1440,
    height: 900,
    scheme: 'light',
  },
  {
    name: 'proposal-owner-1440',
    path: '/ideas/CUST-3?tab=proposal',
    width: 1440,
    height: 900,
    scheme: 'dark',
  },
  {
    name: 'proposal-reader-1440',
    path: '/ideas/CUST-3?tab=proposal',
    width: 1440,
    height: 900,
    scheme: 'light',
    user: USERS.emma,
  },
  {
    name: 'proposal-conflict-1440',
    path: '/ideas/CUST-3?tab=proposal',
    width: 1440,
    height: 900,
    scheme: 'light',
    act: conflict,
  },
  {
    name: 'proposal-comment-1440',
    path: '/ideas/CUST-3?tab=proposal',
    width: 1440,
    height: 900,
    scheme: 'light',
    user: USERS.bob,
    act: async (page) => {
      await page.getByRole('button', { name: 'Comment on Problem' }).click()
      await page.keyboard.type('Could we add the **source** for this number?')
    },
  },
  {
    name: 'proposal-start-1440',
    path: '/ideas/CUST-4?tab=proposal',
    width: 1440,
    height: 900,
    scheme: 'light',
  },
  {
    name: 'proposal-not-yet-390',
    path: '/ideas/CUST-5?tab=proposal',
    width: 390,
    height: 844,
    scheme: 'light',
  },
  {
    name: 'proposal-owner-390',
    path: '/ideas/CUST-3?tab=proposal',
    width: 390,
    height: 844,
    scheme: 'light',
  },
  {
    name: 'proposal-owner-390',
    path: '/ideas/CUST-3?tab=proposal',
    width: 390,
    height: 844,
    scheme: 'dark',
  },
  {
    name: 'proposal-comments-sheet-390',
    path: '/ideas/CUST-3?tab=proposal',
    width: 390,
    height: 844,
    scheme: 'light',
    user: USERS.bob,
    act: async (page) => {
      await page.getByRole('button', { name: /Comments on Summary/ }).click()
      await page.getByRole('dialog', { name: 'Comments on Summary' }).waitFor()
    },
  },
]

for (const shot of shots) {
  test.describe(`${shot.name} (${shot.scheme})`, () => {
    test.use({
      viewport: { width: shot.width, height: shot.height },
      colorScheme: shot.scheme,
      ...(shot.user ? { signedInAs: shot.user } : {}),
    })
    test('capture', async ({ page }) => {
      mkdirSync(outDir, { recursive: true })
      await page.goto(shot.path)
      await expect(page.getByRole('tab', { name: 'Proposal', selected: true })).toBeVisible()
      await page.waitForLoadState('networkidle')
      await shot.act?.(page)
      await page.waitForTimeout(300)
      await page.screenshot({ path: path.join(outDir, `${shot.name}-${shot.scheme}.png`) })
    })
  })
}
