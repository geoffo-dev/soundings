import { mkdirSync } from 'node:fs'
import path from 'node:path'

import type { Page } from '@playwright/test'

import { expect, test, USERS } from './support'

/**
 * Review screenshots of the Phase 10 screens against the MSW mock (not a regression
 * test): the Bids tab as a call manager, an assessor and a member, a bid with its
 * must-haves, documents and the AI's assessment, a flagged bid, the assessment sheet with
 * the bid's documents beside it, the comparison without ranks, the award dialog, My work's
 * "Bids to assess" and Project settings → Bids. Run with
 *   SCREENSHOTS=1 npx playwright test tests/bids-screenshots.spec.ts
 * Writes to ../docs/screenshots/phase-10/mock/ (or SCREENSHOT_DIR).
 */
test.skip(!process.env.SCREENSHOTS, 'Set SCREENSHOTS=1 to capture')

const outDir = path.resolve(process.env.SCREENSHOT_DIR ?? '../docs/screenshots/phase-10/mock')
const HANNAH = '10000000-0000-4000-8000-000000000009'

type Scheme = 'light' | 'dark'
interface Shot {
  name: string
  path: string
  user?: string
  width?: number
  height?: number
  ready: (page: Page) => Promise<void>
  act?: (page: Page) => Promise<void>
}

const noSkeletons = async (page: Page) => {
  await expect(page.locator('[data-slot="skeleton"]')).toHaveCount(0, { timeout: 15_000 })
}
const tabReady = (heading: string) => async (page: Page) => {
  await expect(page.getByRole('heading', { name: heading }).first()).toBeVisible({
    timeout: 15_000,
  })
  await noSkeletons(page)
}
const openBid = (bidder: string) => async (page: Page) => {
  await page
    .getByRole('region', { name: 'Bids', exact: true })
    .getByRole('button', { name: bidder, exact: true })
    .click()
  await expect(
    page.getByRole('dialog', { name: bidder }).getByRole('heading', { name: 'Documents' }),
  ).toBeVisible()
  await noSkeletons(page)
}

const SHOTS: Shot[] = [
  { name: 'bids-manager', path: '/ideas/CUST-3?tab=bids', ready: tabReady('Comparison') },
  {
    name: 'bid-sheet',
    path: '/ideas/CUST-3?tab=bids',
    ready: tabReady('Comparison'),
    act: openBid('Tessellate Logistics'),
  },
  {
    name: 'bid-flagged',
    path: '/ideas/TOOL-4?tab=bids',
    ready: tabReady('Bids'),
    act: openBid('Kestrel Code Co'),
  },
  {
    name: 'award-dialog',
    path: '/ideas/CUST-3?tab=bids',
    ready: tabReady('Comparison'),
    act: async (page) => {
      await page.getByRole('button', { name: 'Award…' }).click()
      await expect(
        page.getByRole('dialog', { name: 'Award the call' }).getByRole('radio').first(),
      ).toBeVisible()
    },
  },
  {
    name: 'bids-assessor',
    path: '/ideas/CUST-3?tab=bids',
    user: USERS.bob,
    ready: tabReady('Your assessments'),
  },
  {
    name: 'assessment-sheet',
    path: '/ideas/CUST-3?tab=bids',
    user: USERS.bob,
    ready: tabReady('Your assessments'),
    act: async (page) => {
      await page
        .getByRole('button', { name: 'Continue: Northwind Fulfilment Ltd, Technical' })
        .click()
      await expect(page.getByRole('dialog').getByRole('radiogroup').first()).toBeVisible()
      await noSkeletons(page)
    },
  },
  {
    name: 'bids-ranking-hidden',
    path: '/ideas/CUST-3?tab=bids',
    user: USERS.priya,
    ready: tabReady('Comparison'),
    act: async (page) => {
      await page.getByRole('heading', { name: 'Comparison' }).scrollIntoViewIfNeeded()
    },
  },
  {
    name: 'bids-member',
    path: '/ideas/CUST-3?tab=bids',
    user: HANNAH,
    ready: tabReady('Fulfilment partner for subscription boxes'),
  },
  { name: 'bids-draft', path: '/ideas/TOOL-11?tab=bids', ready: tabReady('Evaluation') },
  { name: 'my-work-bids', path: '/', user: USERS.bob, ready: tabReady('Bids to assess') },
  {
    name: 'settings-bids',
    path: '/p/internal-tools/settings?tab=bids',
    ready: tabReady('Bid evaluation template'),
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
      if (shot.user) test.use({ signedInAs: shot.user })
      test('capture', async ({ page }) => {
        mkdirSync(outDir, { recursive: true })
        await page.emulateMedia({ colorScheme: variant.scheme })
        await page.setViewportSize({
          width: shot.width ?? variant.width,
          height: shot.height ?? variant.height,
        })
        await page.goto(shot.path)
        await shot.ready(page)
        await shot.act?.(page)
        await page.waitForTimeout(300)
        await page.screenshot({ path: path.join(outDir, `${shot.name}-${variant.suffix}.png`) })
      })
    })
  }
}
