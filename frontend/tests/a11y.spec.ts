import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'

const WCAG_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']

async function seriousViolations(page: Page) {
  const results = await new AxeBuilder({ page }).withTags(WCAG_TAGS).analyze()
  return results.violations
    .filter((violation) => violation.impact === 'serious' || violation.impact === 'critical')
    .map((violation) => ({
      id: violation.id,
      impact: violation.impact,
      help: violation.help,
      targets: violation.nodes.slice(0, 5).map((node) => node.target.join(' ')),
    }))
}

for (const colorScheme of ['light', 'dark'] as const) {
  test.describe(`${colorScheme} mode`, () => {
    test.use({ colorScheme })

    test('/design has no serious or critical axe violations', async ({ page }) => {
      await page.goto('/design')
      await expect(
        page.getByRole('heading', { level: 1, name: 'Soundings design system' }),
      ).toBeVisible()
      await expect(page.locator('html')).toHaveClass(colorScheme)
      // Let the embedded app-shell preview finish loading so it's audited too.
      await expect(
        page
          .frameLocator('iframe[title="App shell preview"]')
          .getByRole('heading', { name: 'My work' }),
      ).toBeVisible()
      expect(await seriousViolations(page)).toEqual([])
    })

    test('/ (My work) has no serious or critical axe violations', async ({ page }) => {
      await page.goto('/')
      await expect(page.getByRole('heading', { level: 1, name: 'My work' })).toBeVisible()
      expect(await seriousViolations(page)).toEqual([])
    })
  })
}
