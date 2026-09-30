import type { Page } from '@playwright/test'

import { expect, test } from './support'

/** Opens the palette with ⌘K / Ctrl+K and waits until typing goes into it. */
async function openPalette(page: Page) {
  await page.keyboard.press('ControlOrMeta+k')
  const palette = page.getByRole('dialog', { name: 'Command palette' })
  await expect(palette.getByRole('combobox')).toBeFocused()
  return palette
}

test('jumps to an idea by key and by title', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { level: 1, name: 'My work' })).toBeVisible()

  const palette = await openPalette(page)
  await page.keyboard.type('tool-2')
  await expect(palette.getByRole('option', { name: /Flaky test dashboard/ })).toBeVisible()
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(/\/ideas\/TOOL-2$/)
  await expect(page.getByRole('heading', { level: 1, name: 'Flaky test dashboard' })).toBeVisible()

  await openPalette(page)
  await page.keyboard.type('returns portal')
  await expect(palette.getByRole('option', { name: /Self-serve returns portal/ })).toHaveAttribute(
    'aria-selected',
    'true',
  )
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(/\/ideas\/CUST-1$/)
})

test('jumps to a project and to My work', async ({ page }) => {
  await page.goto('/settings')
  await expect(page.getByRole('heading', { level: 1, name: 'Settings' })).toBeVisible()
  await openPalette(page)
  await page.keyboard.type('sustain')
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(/\/p\/sustainability$/)
  await expect(page.getByRole('heading', { level: 1, name: 'Sustainability' })).toBeVisible()

  await openPalette(page)
  await page.keyboard.type('my work')
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(/\/$/)
})

test('creates an idea and toggles the theme', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { level: 1, name: 'My work' })).toBeVisible()
  await openPalette(page)
  await page.keyboard.type('new idea')
  await page.keyboard.press('Enter')
  await expect(page.getByRole('dialog', { name: 'New idea' })).toBeVisible()
  await page.keyboard.press('Escape')

  const dark = await page.locator('html').evaluate((html) => html.classList.contains('dark'))
  await openPalette(page)
  await page.keyboard.type('theme')
  await page.getByRole('option', { name: dark ? /light theme/ : /dark theme/ }).click()
  await expect(page.locator('html')).toHaveClass(dark ? /light/ : /dark/)
})

test('shows a friendly message when nothing matches', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { level: 1, name: 'My work' })).toBeVisible()
  await openPalette(page)
  await page.keyboard.type('zzqx')
  await expect(page.getByText('No results for “zzqx”')).toBeVisible()
})
