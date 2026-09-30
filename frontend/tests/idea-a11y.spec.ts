import type { Page } from '@playwright/test'

import { expect, seriousViolations, test } from './support'

/** axe on the idea page and the evaluate sheet: no serious or critical issues, light and dark. */

async function openIdea(page: Page, path: string, title: string) {
  await page.goto(path)
  await expect(page.getByRole('heading', { level: 1, name: title })).toBeVisible()
  await expect(page.getByRole('list', { name: 'Activity, oldest first' })).toBeVisible()
}

for (const colorScheme of ['light', 'dark'] as const) {
  test.describe(`${colorScheme} mode`, () => {
    test.use({ colorScheme })

    test('the idea page (owner, with scores) has no serious or critical violations', async ({
      page,
    }) => {
      await openIdea(page, '/ideas/CUST-2', 'Print-free returns with a QR code')
      await expect(page.locator('html')).toHaveClass(colorScheme)
      await expect(page.getByRole('meter')).toHaveCount(5)
      expect(await seriousViolations(page)).toEqual([])
    })

    test('the Evaluations tab has no serious or critical violations', async ({ page }) => {
      await page.goto('/ideas/CUST-2?tab=evaluations')
      await expect(page.getByRole('table', { name: /Scores by criterion/ })).toBeVisible()
      expect(await seriousViolations(page)).toEqual([])
    })

    test('the blind idea page and the open evaluate sheet have none', async ({ page }) => {
      await openIdea(page, '/ideas/CUST-1', 'Self-serve returns portal')
      await expect(page.getByText('Hidden until you submit')).toBeVisible()
      expect(await seriousViolations(page)).toEqual([])

      await page.keyboard.press('e')
      const sheet = page.getByRole('dialog', { name: 'Evaluate' })
      await expect(sheet.getByRole('radiogroup', { name: 'Value' })).toBeVisible()
      // With validation messages showing, too.
      await sheet.getByRole('button', { name: 'Submit' }).click()
      await expect(sheet.getByText('Pick a score').first()).toBeVisible()
      expect(await seriousViolations(page)).toEqual([])
    })

    test('the reveal after submitting has none', async ({ page }) => {
      await page.goto('/ideas/CUST-1?evaluate=1')
      const sheet = page.getByRole('dialog', { name: 'Evaluate' })
      for (const name of ['Value', 'Feasibility', 'Effort', 'Strategic fit', 'Risk']) {
        await sheet.getByRole('radiogroup', { name }).getByRole('radio', { name: '3' }).click()
      }
      await sheet
        .getByRole('radiogroup', { name: 'Overall recommendation' })
        .getByRole('radio', { name: 'Maybe' })
        .click()
      await sheet.getByRole('button', { name: 'Submit' }).click()
      const reveal = page.getByRole('dialog', { name: 'Your evaluation' })
      await expect(reveal.getByRole('img', { name: /^Carol Díaz/ }).first()).toBeVisible()
      // Let the reveal animation settle before measuring contrast.
      await page.waitForTimeout(1500)
      expect(await seriousViolations(page)).toEqual([])
    })

    test.describe('on a phone', () => {
      test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true })

      test('the page and its details sheet have none', async ({ page }) => {
        await openIdea(page, '/ideas/CUST-2', 'Print-free returns with a QR code')
        expect(await seriousViolations(page)).toEqual([])
        await page.getByRole('tab', { name: /Evaluations/ }).tap()
        await expect(page.getByRole('table', { name: /Scores by criterion/ })).toBeVisible()
        expect(await seriousViolations(page)).toEqual([])
        await page.getByRole('button', { name: 'Details' }).tap()
        await expect(page.getByRole('dialog', { name: 'Details' }).getByRole('meter')).toHaveCount(
          5,
        )
        expect(await seriousViolations(page)).toEqual([])
      })
    })
  })
}
