import type { Page } from '@playwright/test'

import { type Person } from './support/api'
import { DEMO } from './support/bids'
import {
  bestPracticeViolations,
  expect,
  seriousViolations,
  settled,
  signIn,
  test,
} from './support/fixtures'

/**
 * axe (WCAG 2.2 AA rules, serious and critical) on the Phase 10 screens against the real
 * app with the demo story (TOOLS-3's "Data platform build", being assessed), light and
 * dark: the Bids tab as a call manager (kenji: bids, comparison, the AI column not
 * counted), as a manager who still owes assessments (alice: no ranks), as an assessor who
 * has submitted (carol: no prices) and as a viewer (zanele: the summary only); a rejected,
 * flagged bid and an assessor's bid with a restricted pricing document; the reject and
 * award dialogs; the assessment sheet with the bid's documents beside it (alice's
 * Delivery); Project settings → Bids (dave) and My work's "Bids to assess" (alice).
 * axe's best-practice rules on the screens without overlays; the same at 390 px without
 * sideways scrolling; the bid list with the keyboard only. Read-only: nothing is saved.
 * Test plan: A11Y10-*, MO10-*, K10-*.
 */

const bidsRegion = (page: Page) => page.getByRole('region', { name: 'Bids', exact: true })

async function bidsTab(page: Page) {
  await page.goto(`/ideas/${DEMO.key}?tab=bids`)
  await expect(page.getByRole('heading', { level: 2, name: DEMO.title })).toBeVisible({
    timeout: 15_000,
  })
}

async function openBid(page: Page, bidder: string) {
  await bidsTab(page)
  await bidsRegion(page).getByRole('button', { name: bidder, exact: true }).click()
  await expect(
    page.getByRole('dialog', { name: bidder }).getByRole('heading', { name: 'Documents' }),
  ).toBeVisible()
}

interface Screen {
  name: string
  as: Person
  /** Has an overlay open (best-practice rules don't apply: portalled outside landmarks). */
  overlay?: boolean
  open: (page: Page) => Promise<void>
}

const SCREENS: Screen[] = [
  {
    name: 'the Bids tab for a call manager (bids, comparison, an AI assessment not counted)',
    as: 'kenji',
    open: async (page) => {
      await bidsTab(page)
      await expect(
        page.getByRole('region', { name: 'Comparison' }).getByRole('table'),
      ).toBeVisible()
    },
  },
  {
    name: 'the Bids tab for a manager who still owes assessments (no ranks)',
    as: 'alice',
    open: async (page) => {
      await bidsTab(page)
      await expect(
        page.getByText('The ranking shows once you have submitted your assessments'),
      ).toBeVisible()
    },
  },
  {
    name: 'the Bids tab for an assessor (no prices)',
    as: 'carol',
    open: async (page) => {
      await bidsTab(page)
      await expect(page.getByRole('region', { name: 'Your assessments' })).toBeVisible()
    },
  },
  {
    name: 'the Bids tab for a viewer (the summary only)',
    as: 'zanele',
    open: async (page) => {
      await bidsTab(page)
      await expect(
        page.getByText('Only the idea’s owner, admins and the call’s assessors see the bids.'),
      ).toBeVisible()
    },
  },
  {
    name: 'a rejected bid with a missing must-have',
    as: 'kenji',
    overlay: true,
    open: (page) => openBid(page, DEMO.quillfield),
  },
  {
    name: 'an assessor’s bid with a restricted pricing document',
    as: 'carol',
    overlay: true,
    open: (page) => openBid(page, DEMO.northwind),
  },
  {
    name: 'the reject dialog',
    as: 'kenji',
    overlay: true,
    open: async (page) => {
      await openBid(page, DEMO.tessellate)
      const sheet = page.getByRole('dialog', { name: DEMO.tessellate })
      await sheet.getByRole('button', { name: 'Reject…' }).click()
      await expect(
        page.getByRole('dialog', { name: 'Reject the bid from Tessellate Software?' }),
      ).toBeVisible()
    },
  },
  {
    name: 'the award dialog',
    as: 'kenji',
    overlay: true,
    open: async (page) => {
      await bidsTab(page)
      await page.getByRole('button', { name: 'Award…' }).click()
      await expect(
        page.getByRole('dialog', { name: 'Award the call' }).getByRole('radio').first(),
      ).toBeVisible()
    },
  },
  {
    name: 'the assessment sheet with the bid’s documents beside it',
    as: 'alice',
    overlay: true,
    open: async (page) => {
      await bidsTab(page)
      await page
        .getByRole('region', { name: 'Your assessments' })
        .getByRole('button', { name: `Assess: ${DEMO.northwind}, Delivery` })
        .click()
      const sheet = page.getByRole('dialog', { name: /Delivery · Northwind/ })
      await expect(sheet.getByRole('radiogroup').first()).toBeVisible()
    },
  },
  {
    name: 'Project settings → Bids',
    as: 'dave',
    open: async (page) => {
      await page.goto('/p/internal-tools/settings?tab=bids')
      await expect(page.getByRole('heading', { name: 'Bid evaluation template' })).toBeVisible({
        timeout: 15_000,
      })
    },
  },
  {
    name: 'My work with “Bids to assess”',
    as: 'alice',
    open: async (page) => {
      await page.goto('/')
      await expect(
        page
          .getByRole('region', { name: /Bids to assess/ })
          .getByRole('link', { name: DEMO.title, exact: true }),
      ).toBeVisible()
    },
  },
]

for (const colorScheme of ['light', 'dark'] as const) {
  test.describe(`${colorScheme} theme`, () => {
    test.use({ colorScheme })

    for (const screen of SCREENS) {
      test(`A11Y10: ${screen.name} has no serious or critical violations`, async ({ page }) => {
        await signIn(page, screen.as)
        await screen.open(page)
        await settled(page)
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

  test('MO10-01: the Phase 10 screens fit without sideways scrolling', async ({ page }) => {
    test.setTimeout(240_000)
    const overflow = () =>
      page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      )
    for (const screen of SCREENS) {
      await signIn(page, screen.as)
      await screen.open(page)
      await settled(page)
      expect(await overflow(), screen.name).toBeLessThanOrEqual(0)
      expect(await seriousViolations(page), screen.name).toEqual([])
    }
  })

  test('MO10-02: on a phone the assessment sheet opens the bid’s documents over it', async ({
    page,
  }) => {
    await signIn(page, 'alice')
    await bidsTab(page)
    await page
      .getByRole('region', { name: 'Your assessments' })
      .getByRole('button', { name: `Assess: ${DEMO.northwind}, Delivery` })
      .click()
    const sheet = page.getByRole('dialog', { name: /Delivery · Northwind/ })
    await expect(sheet.getByRole('radiogroup').first()).toBeVisible()
    await expect(sheet.getByRole('button', { name: /^Submit$/ })).toBeVisible()
    await expect(sheet.getByText(/The bid’s documents/).first()).toBeVisible()
  })
})

test('K10-01: the bid list with the keyboard only; Escape puts focus back on the bid', async ({
  page,
}) => {
  await signIn(page, 'kenji')
  await bidsTab(page)
  const row = bidsRegion(page).getByRole('button', { name: DEMO.tessellate, exact: true })
  await row.focus()
  await page.keyboard.press('Enter')
  const sheet = page.getByRole('dialog', { name: DEMO.tessellate })
  await expect(sheet.getByRole('heading', { name: 'Documents' })).toBeVisible()
  await expect(sheet).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(sheet).toHaveCount(0)
  await expect(row).toBeFocused()
})
