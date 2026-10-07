import { expect, seriousViolations, test, USERS } from './support'

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
      await expect(
        page.getByRole('link', { name: 'Gift cards with personal video messages', exact: true }),
      ).toBeVisible()
      await page.getByRole('button', { name: /Show closed/ }).click()
      expect(await seriousViolations(page)).toEqual([])
    })

    test('the New idea dialog has no serious or critical axe violations', async ({ page }) => {
      await page.goto('/')
      await expect(page.getByRole('heading', { level: 1, name: 'My work' })).toBeVisible()
      await page.keyboard.press('n')
      await expect(page.getByRole('dialog', { name: 'New idea' })).toBeVisible()
      expect(await seriousViolations(page)).toEqual([])
    })

    test.describe('signed out', () => {
      test.use({ signedInAs: null })

      test('/login has no serious or critical axe violations', async ({ page }) => {
        await page.goto('/login')
        await expect(
          page.getByRole('heading', { level: 1, name: 'Sign in to Soundings' }),
        ).toBeVisible()
        await expect(page.getByRole('button', { name: /Alice Anders/ })).toBeVisible()
        expect(await seriousViolations(page)).toEqual([])
      })
    })
  })
}

test.describe('a user without projects', () => {
  test.use({ signedInAs: USERS.ivan })

  test('My work is friendly and accessible when empty', async ({ page }) => {
    await page.goto('/')
    await expect(page.getByText('Nothing to evaluate')).toBeVisible()
    // Not a member anywhere: no "Ideas I own" to act on, no advice to volunteer or submit.
    await expect(page.getByRole('heading', { name: /Ideas I own/ })).toHaveCount(0)
    await expect(page.getByText('You’re not in any projects yet')).toBeVisible()
    expect(await seriousViolations(page)).toEqual([])
  })
})
