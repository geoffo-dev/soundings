import { expect, test } from './support'

test('submits an idea with "n" and opens it', async ({ page }) => {
  await page.goto('/p/customer-innovation')
  await expect(page.getByRole('heading', { level: 1, name: 'Customer Innovation' })).toBeVisible()
  await page.keyboard.press('n')
  const dialog = page.getByRole('dialog', { name: 'New idea' })
  await expect(dialog).toBeVisible()
  await expect(dialog.getByRole('textbox', { name: 'Title' })).toBeFocused()
  // Opened from a project: it is preselected.
  await expect(dialog.getByRole('combobox', { name: 'Project' })).toHaveText(/Customer Innovation/)

  // Required fields are checked before sending, and focus moves to the first gap.
  await dialog.getByRole('button', { name: /Submit idea/ }).click()
  await expect(dialog.getByText('Give your idea a short title.')).toBeVisible()
  await expect(dialog.getByRole('textbox', { name: 'Title' })).toBeFocused()

  await page.keyboard.type('Returns by parcel locker')
  await dialog.getByRole('textbox', { name: 'Summary' }).fill('Drop returns at any parcel locker.')
  await dialog.getByRole('textbox', { name: /Description/ }).fill('**Why:** lockers are open 24/7.')
  await dialog.getByRole('radio', { name: 'Preview' }).click()
  await expect(dialog.getByText('lockers are open 24/7.')).toBeVisible()

  const tags = dialog.getByRole('combobox', { name: 'Tags' })
  await tags.fill('ret')
  await expect(page.getByRole('option', { name: 'returns' })).toBeVisible()
  await page.keyboard.press('Enter')
  await tags.fill('lockers, parcels,')
  await expect(dialog.getByRole('button', { name: 'Remove tag lockers' })).toBeVisible()
  await expect(dialog.getByRole('button', { name: 'Remove tag parcels' })).toBeVisible()
  await page.keyboard.press('Backspace')
  await expect(dialog.getByRole('button', { name: 'Remove tag parcels' })).toBeHidden()

  await page.keyboard.press('ControlOrMeta+Enter')
  await expect(dialog).toBeHidden()
  await expect(page).toHaveURL(/\/ideas\/CUST-21$/)
  await expect(
    page.getByRole('heading', { level: 1, name: 'Returns by parcel locker' }),
  ).toBeVisible()
  await expect(page.getByText('CUST-21 created')).toBeVisible()
})

test('keeps the draft when the dialog is closed by accident', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { level: 1, name: 'My work' })).toBeVisible()
  await page.keyboard.press('n')
  const dialog = page.getByRole('dialog', { name: 'New idea' })
  await dialog.getByRole('textbox', { name: 'Title' }).fill('Half an idea')
  await page.keyboard.press('Escape')
  await expect(dialog).toBeHidden()

  await page.getByRole('button', { name: 'New idea' }).first().click()
  await expect(dialog.getByRole('textbox', { name: 'Title' })).toHaveValue('Half an idea')
  await expect(dialog.getByText('We kept your draft.')).toBeVisible()
  await dialog.getByRole('button', { name: 'Start over' }).click()
  await expect(dialog.getByRole('textbox', { name: 'Title' })).toHaveValue('')
})

test('is a full-screen form on a phone', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/')
  await expect(page.getByRole('heading', { level: 1, name: 'My work' })).toBeVisible()
  await page.keyboard.press('n')
  const dialog = page.getByRole('dialog', { name: 'New idea' })
  await expect(dialog).toBeVisible()
  // Measure once the open animation (a slight scale-up) has finished.
  await dialog.evaluate(async (node) => {
    await Promise.all(node.getAnimations().map((animation) => animation.finished))
  })
  const box = await dialog.boundingBox()
  expect(box?.width).toBeCloseTo(390, 0)
  const submit = dialog.getByRole('button', { name: /Submit idea/ })
  await expect(submit).toBeInViewport()
  expect((await submit.boundingBox())?.height).toBeGreaterThanOrEqual(44)
})
