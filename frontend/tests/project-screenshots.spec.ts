import { mkdirSync } from 'node:fs'
import path from 'node:path'

import type { Page } from '@playwright/test'

import { expect, test, USERS } from './support'

/**
 * Review screenshots of the project screens against the MSW mock (not a regression
 * test). Run with `npm run screenshots` (every *screenshots.spec.ts) or
 *   SCREENSHOTS=1 npx playwright test tests/project-screenshots.spec.ts
 * Writes to ../docs/screenshots/phase-1/mock/ (or SCREENSHOT_DIR).
 */
test.skip(!process.env.SCREENSHOTS, 'Set SCREENSHOTS=1 to capture')

const outDir = path.resolve(process.env.SCREENSHOT_DIR ?? '../docs/screenshots/phase-1/mock')
// Only when capturing: loading a skipped file must not create folders.
if (process.env.SCREENSHOTS) mkdirSync(outDir, { recursive: true })

async function settle(page: Page) {
  await page.evaluate(() => document.fonts.ready)
  await page.waitForTimeout(400)
}

type Scheme = 'light' | 'dark'
const shots: { name: string; path: string; width: number; height: number; scheme: Scheme }[] = [
  {
    name: 'project-board-1440',
    path: '/p/customer-innovation?view=board',
    width: 1440,
    height: 900,
    scheme: 'light',
  },
  {
    name: 'project-board-1440',
    path: '/p/customer-innovation?view=board',
    width: 1440,
    height: 900,
    scheme: 'dark',
  },
  {
    name: 'project-board-390-mobile',
    path: '/p/customer-innovation?view=board',
    width: 390,
    height: 844,
    scheme: 'light',
  },
  {
    name: 'project-list-1440',
    path: '/p/customer-innovation?view=list',
    width: 1440,
    height: 900,
    scheme: 'light',
  },
  {
    name: 'project-list-1440',
    path: '/p/customer-innovation?view=list',
    width: 1440,
    height: 900,
    scheme: 'dark',
  },
  {
    name: 'project-list-1024',
    path: '/p/customer-innovation?view=list',
    width: 1024,
    height: 768,
    scheme: 'light',
  },
  {
    name: 'project-list-390-mobile',
    path: '/p/customer-innovation?view=list',
    width: 390,
    height: 844,
    scheme: 'dark',
  },
  {
    name: 'project-list-filtered-1440',
    path: '/p/customer-innovation?view=list&owner=me&status=evaluating,new',
    width: 1440,
    height: 900,
    scheme: 'light',
  },
  {
    name: 'project-settings-general-1440',
    path: '/p/internal-tools/settings',
    width: 1440,
    height: 1100,
    scheme: 'light',
  },
  {
    name: 'project-settings-members-1440',
    path: '/p/internal-tools/settings?tab=members',
    width: 1440,
    height: 900,
    scheme: 'dark',
  },
  {
    name: 'project-settings-rubric-1440',
    path: '/p/internal-tools/settings?tab=rubric',
    width: 1440,
    height: 1300,
    scheme: 'light',
  },
  {
    name: 'project-settings-rubric-390-mobile',
    path: '/p/internal-tools/settings?tab=rubric',
    width: 390,
    height: 844,
    scheme: 'dark',
  },
  {
    name: 'project-settings-statuses-1440',
    path: '/p/internal-tools/settings?tab=statuses',
    width: 1440,
    height: 1100,
    scheme: 'light',
  },
  {
    name: 'project-not-found-1440',
    path: '/p/does-not-exist',
    width: 1440,
    height: 900,
    scheme: 'light',
  },
]

for (const shot of shots) {
  test(`${shot.name}-${shot.scheme}`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: shot.scheme })
    await page.setViewportSize({ width: shot.width, height: shot.height })
    await page.goto(shot.path)
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
    await settle(page)
    await page.screenshot({ path: path.join(outDir, `${shot.name}-${shot.scheme}.png`) })
  })
}

test('project-board-close-picker-1440-light', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/p/customer-innovation?view=board')
  const card = page.getByRole('link', { name: /^CUST-5\b/ })
  await card.focus()
  await page.keyboard.press('Space')
  for (let i = 0; i < 4; i += 1) await page.keyboard.press('ArrowRight')
  await page.keyboard.press('Space')
  await expect(page.getByRole('dialog', { name: 'Close CUST-5 as' })).toBeVisible()
  await settle(page)
  await page.screenshot({ path: path.join(outDir, 'project-board-close-picker-1440-light.png') })
})

test.describe('as a platform admin', () => {
  test.use({ signedInAs: USERS.priya })

  for (const [width, height] of [
    [1440, 900],
    [390, 844],
  ] as const) {
    test(`create-project-${width}-light`, async ({ page }) => {
      await page.setViewportSize({ width, height })
      await page.goto('/')
      await expect(page.getByRole('heading', { level: 1, name: 'My work' })).toBeVisible()
      if (width < 768) await page.getByRole('button', { name: 'Open navigation' }).click()
      await page.getByRole('button', { name: 'New project' }).click()
      await page.keyboard.type('Field Research')
      await settle(page)
      await page.screenshot({ path: path.join(outDir, `create-project-${width}-light.png`) })
    })
  }
})
