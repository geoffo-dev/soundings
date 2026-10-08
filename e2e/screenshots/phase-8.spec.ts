import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import type { Locator, Page } from '@playwright/test'

import { Api, type Person } from '../tests/support/api'
import { expect, settled, signIn, test } from '../tests/support/fixtures'
import { readPdf, renderPdfPages } from '../tests/support/pdf'

/**
 * Review screenshots of the Phase 8 screens (per-project proposal templates and the
 * research step) from the real app with the demo data. Not a regression test.
 *
 * `npm run screenshots:phase8` → docs/screenshots/phase-8/ (`SCREENSHOT_DIR` overrides):
 * <screen>-<1440-light|1440-dark|390-light>.png, and pdf/ (the TOOLS-3 and GREEN-4
 * exports with the pages that show the research appendix and Carbon impact). The demo's
 * Internal Tools runs the step before evaluation with a custom template: Dave (its
 * admin) on Project settings → Research and → Proposal; the board with the Research
 * column (TOOLS-11 complete, TOOLS-12 with one required item open) as Sven; the gate
 * dialog as Dave (who may "Move anyway"; nothing is moved); TOOLS-11's Research panel
 * with Similar ideas as Carol and TOOLS-12's, answerable, as Sven; TOOLS-3's proposal in
 * the custom template with the appendix as Kenji. Read-only: it changes no data.
 */

const here = dirname(fileURLToPath(import.meta.url))
const outDir = resolve(process.env.SCREENSHOT_DIR ?? join(here, '../../docs/screenshots/phase-8'))
const pdfDir = join(outDir, 'pdf')
mkdirSync(pdfDir, { recursive: true })

const baseURL = () => test.info().project.use.baseURL ?? ''

test.describe.configure({ mode: 'serial' })

/** Scrolls `target` to the top of its scrolling container (below any sticky bar). */
async function scrollTo(target: Locator) {
  await expect(target).toBeVisible()
  await target.evaluate((node) => node.scrollIntoView({ block: 'start' }))
}

interface Shot {
  name: string
  as: Person
  fullPage?: boolean
  open: (page: Page, phone: boolean) => Promise<void>
}

const SHOTS: Shot[] = [
  {
    name: 'settings-research',
    as: 'dave',
    open: async (page) => {
      await page.goto('/p/internal-tools/settings?tab=research')
      await expect(page.getByRole('heading', { name: 'Research step' })).toBeVisible()
      await expect(page.getByRole('list', { name: 'Checklist items' })).toBeVisible()
    },
  },
  {
    name: 'settings-proposal-template',
    as: 'dave',
    open: async (page) => {
      await page.goto('/p/internal-tools/settings?tab=proposal-template')
      await expect(page.getByRole('heading', { name: 'Proposal template' })).toBeVisible()
      await expect(page.getByRole('list', { name: 'Sections' }).getByRole('listitem')).toHaveCount(
        6,
      )
    },
  },
  {
    name: 'board-research-column',
    as: 'sven',
    open: async (page, phone) => {
      await page.goto('/p/internal-tools?view=board')
      const column = page.getByRole('region', { name: /^Research\b/ })
      await expect(column.getByRole('link', { name: /\(TOOLS-12\)$/ })).toBeVisible()
      if (phone) await column.evaluate((node) => node.scrollIntoView({ inline: 'start' }))
    },
  },
  {
    name: 'research-gate-dialog',
    as: 'dave',
    open: async (page) => {
      await page.goto('/p/internal-tools?view=board')
      const card = page.getByRole('link', { name: /\(TOOLS-12\)$/ })
      await expect(card).toBeVisible()
      await settled(page)
      const announcer = page.locator('[id^="DndLiveRegion"]')
      await card.focus()
      await page.keyboard.press('Space')
      await expect(announcer).toContainText('Picked up TOOLS-12')
      await page.keyboard.press('ArrowRight')
      await expect(announcer).toContainText('TOOLS-12 is over')
      await page.keyboard.press('Space')
      await expect(page.getByRole('dialog', { name: 'Finish the research first' })).toBeVisible()
    },
  },
  {
    name: 'idea-research-similar-ideas',
    as: 'carol',
    open: async (page) => {
      await page.goto('/ideas/TOOLS-11')
      const panel = page.getByRole('region', { name: 'Research' })
      await expect(panel.getByRole('link', { name: /CUST-14/ })).toBeVisible()
      await scrollTo(panel)
    },
  },
  {
    name: 'idea-research-open-item',
    as: 'sven',
    open: async (page) => {
      await page.goto('/ideas/TOOLS-12')
      const panel = page.getByRole('region', { name: 'Research' })
      await expect(panel.getByRole('textbox').first()).toBeVisible()
      await scrollTo(panel)
    },
  },
  {
    name: 'proposal-custom-template',
    as: 'kenji',
    open: async (page) => {
      await page.goto('/ideas/TOOLS-3?tab=proposal')
      await expect(
        page.getByRole('heading', { level: 2, name: /^4\. Effort & rollout$/ }),
      ).toBeVisible()
    },
  },
  {
    name: 'proposal-research-appendix',
    as: 'kenji',
    open: async (page) => {
      await page.goto('/ideas/TOOLS-3?tab=proposal')
      await scrollTo(page.getByRole('region', { name: 'Research and consultation' }))
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

async function shoot(page: Page, path: string, fullPage = false) {
  await settled(page)
  await page.evaluate(() => document.fonts.ready)
  await page.waitForTimeout(500) // enter animations
  await page.screenshot({ path, animations: 'disabled', caret: 'hide', fullPage })
}

test('pdf: the exports with the research appendix and Carbon impact', async ({ browser }) => {
  test.setTimeout(120_000)
  const kenji = await Api.as(baseURL(), 'kenji')
  try {
    for (const [key, marker, name] of [
      ['TOOLS-3', 'Research and consultation', 'research-appendix'],
      ['GREEN-4', 'Carbon impact', 'carbon-impact'],
    ] as const) {
      const { response, body } = await kenji.exportProposal(key, 'pdf')
      expect(response.status()).toBe(200)
      writeFileSync(join(pdfDir, `${key}-proposal.pdf`), body)
      const { pages } = await readPdf(body)
      // The first page after the contents that carries the heading.
      const index = pages.findIndex((text, at) => at > 0 && text.includes(marker))
      expect(index, `${key}: a page with "${marker}"`).toBeGreaterThan(0)
      await renderPdfPages(browser, body, [
        { page: 1, path: join(pdfDir, `${key}-proposal-page-1.png`) },
        { page: index + 1, path: join(pdfDir, `${key}-proposal-${name}.png`) },
      ])
    }
  } finally {
    await kenji.dispose()
  }
})

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
        test.setTimeout(60_000)
        await signIn(page, shot.as)
        await shot.open(page, variant.phone)
        await shoot(page, join(outDir, `${shot.name}-${variant.suffix}.png`), shot.fullPage)
      })
    }
  })
}
