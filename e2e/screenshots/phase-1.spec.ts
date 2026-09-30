import { mkdirSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import type { Page } from '@playwright/test'

import type { Person } from '../tests/support/api'
import { expect, heading, settled, signIn, test } from '../tests/support/fixtures'

/**
 * Review screenshots of every Phase 1 screen, from the real app with the seeded demo
 * data (not a regression test). `npm run screenshots` → docs/screenshots/phase-1/
 * as <screen>-<1440-light|1440-dark|390-light>.png (`SCREENSHOT_DIR` overrides).
 *
 * Needs freshly seeded data: the local stack reseeds on start; against another app
 * run `soundings seed --reset` first. Nothing here saves anything.
 */

const here = dirname(fileURLToPath(import.meta.url))
const outDir = resolve(process.env.SCREENSHOT_DIR ?? join(here, '../../docs/screenshots/phase-1'))
mkdirSync(outDir, { recursive: true })

interface Shot {
  name: string
  as: Person | null
  open: (page: Page, phone: boolean) => Promise<void>
}

const SHOTS: Shot[] = [
  {
    name: 'login',
    as: null,
    open: async (page) => {
      await page.goto('/login')
      await expect(page.getByRole('button', { name: /Alice Anders/ })).toBeVisible()
    },
  },
  {
    name: 'my-work',
    as: 'alice',
    open: async (page) => {
      await page.goto('/')
      await expect(page.locator('#evaluations').getByRole('listitem').first()).toBeVisible()
    },
  },
  {
    name: 'project-board',
    as: 'alice',
    open: async (page) => {
      await page.goto('/p/customer-innovation?view=board')
      await expect(page.getByRole('link', { name: /^CUST-11\b/ })).toBeVisible()
    },
  },
  {
    name: 'project-list',
    as: 'alice',
    open: async (page) => {
      await page.goto('/p/customer-innovation?view=list&status=evaluating&sort=-score')
      await expect(page.getByRole('button', { name: /^Status Evaluating/ })).toBeVisible()
      await expect(
        page.getByRole('table', { name: 'Ideas' }).getByRole('link').first(),
      ).toBeVisible()
    },
  },
  {
    // Alice owns CUST-12: two evaluations in (4.1), a draft and an invitation pending.
    name: 'idea-page',
    as: 'alice',
    open: async (page) => {
      await page.goto('/ideas/CUST-12')
      await expect(heading(page, 'Accessibility audit of the checkout')).toBeVisible()
    },
  },
  {
    // Alice owes CUST-11 an evaluation: blind.
    name: 'idea-page-blind',
    as: 'alice',
    open: async (page) => {
      await page.goto('/ideas/CUST-11')
      await expect(heading(page, 'WhatsApp order updates')).toBeVisible()
    },
  },
  {
    // Alice's saved draft on TOOLS-9 (two criteria scored).
    name: 'evaluate-sheet',
    as: 'alice',
    open: async (page) => {
      await page.goto('/ideas/TOOLS-9?evaluate=1')
      await expect(page.getByRole('dialog', { name: 'Evaluate' })).toBeVisible()
      await expect(page.getByText(/^Draft saved/)).toBeVisible()
    },
  },
  {
    // Alice submitted on TOOLS-6 (four evaluations, still open).
    name: 'evaluate-sheet-revealed',
    as: 'alice',
    open: async (page) => {
      await page.goto('/ideas/TOOLS-6?evaluate=1')
      await expect(page.getByRole('dialog', { name: 'Your evaluation' })).toBeVisible()
      await expect(page.getByRole('region', { name: 'Everyone’s scores' })).toBeVisible()
    },
  },
  {
    // CUST-8: three evaluations with high disagreement.
    name: 'evaluations-tab',
    as: 'alice',
    open: async (page) => {
      await page.goto('/ideas/CUST-8?tab=evaluations')
      await expect(page.getByRole('tabpanel').getByRole('article')).toHaveCount(3)
    },
  },
  {
    name: 'submit-idea',
    as: 'alice',
    open: async (page) => {
      await page.goto('/p/customer-innovation')
      await expect(heading(page, 'Customer Innovation')).toBeVisible()
      await page
        .getByRole('button', { name: /^New idea/ })
        .last()
        .click()
      const dialog = page.getByRole('dialog', { name: 'New idea' })
      await dialog.getByRole('textbox', { name: 'Title' }).fill('Returns by parcel locker')
      await dialog
        .getByRole('textbox', { name: 'Summary' })
        .fill('Let customers drop a return at any parcel locker, open around the clock.')
      await dialog
        .getByRole('textbox', { name: /Description/ })
        .fill('**Why:** a third of returns are posted after 6 pm, when post offices are closed.')
      const tags = dialog.getByRole('combobox', { name: 'Tags' })
      await tags.fill('returns,')
      await tags.fill('delivery,')
      await dialog.getByRole('textbox', { name: 'Title' }).focus()
    },
  },
  {
    name: 'command-palette',
    as: 'alice',
    open: async (page) => {
      await page.goto('/')
      await expect(heading(page, 'My work')).toBeVisible()
      await page.keyboard.press('ControlOrMeta+k')
      const palette = page.getByRole('dialog', { name: 'Command palette' })
      await expect(palette.getByRole('combobox')).toBeFocused()
      await page.keyboard.type('checkout')
      await expect(palette.getByRole('option', { name: /Accessibility audit/ })).toBeVisible()
    },
  },
  {
    name: 'project-settings',
    as: 'alice',
    open: async (page) => {
      await page.goto('/p/customer-innovation/settings')
      await expect(heading(page, 'Project settings')).toBeVisible()
      await expect(page.getByRole('textbox', { name: 'Name' })).toHaveValue('Customer Innovation')
    },
  },
  {
    // Sustainability's own rubric: weighted, with an inverted criterion.
    name: 'project-settings-rubric',
    as: 'alice',
    open: async (page) => {
      await page.goto('/p/sustainability/settings?tab=rubric')
      await expect(heading(page, 'Project settings')).toBeVisible()
      await expect(page.getByRole('list', { name: 'Criteria' }).getByRole('listitem')).toHaveCount(
        4,
      )
    },
  },
  {
    name: 'shortcut-sheet',
    as: 'alice',
    open: async (page) => {
      await page.goto('/ideas/CUST-12')
      await expect(heading(page, 'Accessibility audit of the checkout')).toBeVisible()
      await page.keyboard.press('?')
      await expect(page.getByRole('dialog', { name: 'Keyboard shortcuts' })).toBeVisible()
    },
  },
]

const VARIANTS = [
  {
    suffix: '1440-light',
    viewport: { width: 1440, height: 900 },
    colorScheme: 'light',
    phone: false,
  },
  {
    suffix: '1440-dark',
    viewport: { width: 1440, height: 900 },
    colorScheme: 'dark',
    phone: false,
  },
  { suffix: '390-light', viewport: { width: 390, height: 844 }, colorScheme: 'light', phone: true },
] as const

for (const variant of VARIANTS) {
  test.describe(variant.suffix, () => {
    test.use({
      viewport: variant.viewport,
      colorScheme: variant.colorScheme,
      isMobile: variant.phone,
      hasTouch: variant.phone,
    })

    for (const shot of SHOTS) {
      test(`${shot.name}-${variant.suffix}`, async ({ page }) => {
        if (shot.as) await signIn(page, shot.as)
        await shot.open(page, variant.phone)
        await settled(page)
        await page.evaluate(() => document.fonts.ready)
        await page.waitForTimeout(500) // enter animations
        await page.screenshot({
          path: join(outDir, `${shot.name}-${variant.suffix}.png`),
          animations: 'disabled',
          caret: 'hide',
        })
      })
    }
  })
}
