import { expect, test } from './support'

test('⌘K / Ctrl+K opens the command palette and navigates', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { level: 1, name: 'My work' })).toBeVisible()

  await page.keyboard.press('ControlOrMeta+k')
  const palette = page.getByRole('dialog', { name: 'Command palette' })
  await expect(palette).toBeVisible()
  await page.keyboard.type('settings')
  await page.keyboard.press('Enter')
  await expect(palette).toBeHidden()
  await expect(page).toHaveURL(/\/settings$/)
  await expect(page.getByRole('heading', { level: 1, name: 'Settings' })).toBeVisible()
})

test('"?" opens the shortcut sheet and "g m" goes to My work', async ({ page }) => {
  await page.goto('/settings')
  await expect(page.getByRole('heading', { level: 1, name: 'Settings' })).toBeVisible()

  await page.keyboard.press('?')
  const sheet = page.getByRole('dialog', { name: 'Keyboard shortcuts' })
  await expect(sheet).toBeVisible()
  await expect(sheet.getByText('Open command palette')).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(sheet).toBeHidden()

  await page.keyboard.press('g')
  await page.keyboard.press('m')
  await expect(page).toHaveURL(/\/$/)
})

test('shortcuts are ignored while typing', async ({ page }) => {
  await page.goto('/design#forms')
  const search = page.getByPlaceholder('Search ideas…')
  await search.click()
  await page.keyboard.type('?n')
  await expect(search).toHaveValue('?n')
  await expect(page.getByRole('dialog')).toHaveCount(0)
})

test('theme preference persists across reloads without a flash', async ({ page }) => {
  await page.goto('/design')
  await page.getByRole('radio', { name: 'Dark' }).click()
  await expect(page.locator('html')).toHaveClass(/dark/)
  await page.reload()
  // The inline script in index.html applies the class before the app renders.
  await expect(page.locator('html')).toHaveClass(/dark/)
  expect(await page.evaluate(() => localStorage.getItem('soundings-theme'))).toBe('dark')
})

test('the sidebar collapses with "[" and becomes a drawer on phones', async ({ page }) => {
  await page.goto('/')
  const nav = page.getByRole('navigation', { name: 'Main' })
  await expect(nav).toBeVisible()
  await page.keyboard.press('[')
  await expect(page.getByRole('button', { name: 'Expand sidebar' })).toBeVisible()

  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('button', { name: 'Open navigation' }).click()
  const drawer = page.getByRole('dialog', { name: 'Navigation' })
  await expect(drawer).toBeVisible()
  await drawer.getByRole('link', { name: 'Settings' }).click()
  await expect(drawer).toBeHidden()
  await expect(page).toHaveURL(/\/settings$/)
})

test('unknown routes show a friendly not-found page', async ({ page }) => {
  await page.goto('/no/such/page')
  await expect(page.getByRole('heading', { name: 'We couldn’t find that page' })).toBeVisible()
  await page.getByRole('link', { name: 'Go to My work' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'My work' })).toBeVisible()
})
