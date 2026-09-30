import type { Locator, Page } from '@playwright/test'

import { expect, test } from './support'

/**
 * The evaluate sheet (wireframe 04) and blind evaluation on the idea page.
 * Alice is a pending evaluator on CUST-1 "Self-serve returns portal"; Carol
 * and Dave have submitted.
 */

const CRITERIA = ['Value', 'Feasibility', 'Effort', 'Strategic fit', 'Risk'] as const
const details = (page: Page) => page.getByRole('complementary', { name: 'Idea details' })
const sheet = (page: Page) => page.getByRole('dialog', { name: /^(Evaluate|Your evaluation)$/ })

async function score(dialog: Locator, criterion: string, value: string) {
  await dialog
    .getByRole('radiogroup', { name: criterion })
    .getByRole('radio', { name: value })
    .click()
}

async function recommend(dialog: Locator, value: 'Go' | 'Maybe' | 'No') {
  await dialog
    .getByRole('radiogroup', { name: 'Overall recommendation' })
    .getByRole('radio', { name: value })
    .click()
}

test('a pending evaluator sees no scores, evaluates, and then sees them revealed', async ({
  page,
}) => {
  await page.goto('/ideas/CUST-1')
  await expect(
    page.getByRole('heading', { level: 1, name: 'Self-serve returns portal' }),
  ).toBeVisible()

  // Blind: no aggregate, no bars, no tallies — but who has submitted is visible.
  const sidebar = details(page)
  await expect(sidebar.getByText('Hidden until you submit')).toBeVisible()
  await expect(sidebar.getByRole('meter')).toHaveCount(0)
  await expect(sidebar).not.toContainText(/\d\.\d/)
  await expect(sidebar.getByRole('img', { name: '2 of 3 evaluations submitted' })).toBeVisible()
  await page.getByRole('tab', { name: /Evaluations/ }).click()
  await expect(page.getByRole('tabpanel')).toContainText('Hidden until you submit')
  await expect(page.getByRole('tabpanel').getByRole('article')).toHaveCount(0)

  // "e" opens the sheet; focus starts on the first criterion.
  await page.keyboard.press('e')
  const dialog = sheet(page)
  await expect(dialog).toBeVisible()
  await expect(page).toHaveURL(/evaluate=1/)
  await expect(
    dialog.getByRole('radiogroup', { name: 'Value' }).getByRole('radio', { name: '1' }),
  ).toBeFocused()
  // Scores from the keyboard: digits pick, Tab moves on.
  await page.keyboard.press('4')
  await expect(
    dialog.getByRole('radiogroup', { name: 'Value' }).getByRole('radio', { name: '4' }),
  ).toBeChecked()
  await expect(dialog.getByText(/^Draft saved/)).toBeVisible()

  // Submitting with gaps points at them instead of failing silently.
  await dialog.getByRole('button', { name: /^Submit/ }).click()
  await expect(dialog.getByText('Pick a score')).toHaveCount(4)
  await expect(
    dialog.getByRole('radiogroup', { name: 'Feasibility' }).getByRole('radio', { name: '1' }),
  ).toBeFocused()

  await score(dialog, 'Feasibility', '3')
  await score(dialog, 'Effort', '2')
  await score(dialog, 'Strategic fit', '5')
  await score(dialog, 'Risk', '2')
  await dialog.getByRole('button', { name: 'Add a comment on Risk' }).click()
  await dialog.getByRole('textbox', { name: 'Comment on Risk (optional)' }).fill('Low risk.')
  await recommend(dialog, 'Go')
  await expect(dialog.getByText('5 of 5 scored')).toBeVisible()
  await page.keyboard.press('ControlOrMeta+Enter')

  // The reveal: everyone's scores next to yours, the mean and the aggregate.
  await expect(page.getByRole('dialog', { name: 'Your evaluation' })).toBeVisible()
  const reveal = page.getByRole('dialog', { name: 'Your evaluation' })
  await expect(reveal.getByRole('img', { name: /^Carol Díaz: \d out of 5$/ })).toHaveCount(5)
  await expect(reveal.getByRole('img', { name: /^Dave Okafor: \d out of 5$/ })).toHaveCount(5)
  await expect(reveal.getByRole('img', { name: 'Your score: 4 out of 5' }).first()).toBeVisible()
  await expect(reveal.getByText('3 evaluations')).toBeVisible()

  await reveal.getByRole('button', { name: 'Done' }).click()
  await expect(reveal).toBeHidden()
  await expect(page).not.toHaveURL(/evaluate=1/)
  await expect(sidebar.getByText('Hidden until you submit')).toBeHidden()
  await expect(sidebar.getByRole('meter')).toHaveCount(5)
  await expect(sidebar.getByRole('img', { name: '3 of 3 evaluations submitted' })).toBeVisible()
  await expect(page.getByRole('tabpanel').getByRole('article')).toHaveCount(3)
  // No more "Evaluate" for Alice here.
  await expect(page.getByRole('button', { name: /^Evaluate/ })).toHaveCount(0)
})

test('?evaluate=1 opens the sheet; Esc closes it and keeps the draft', async ({ page }) => {
  await page.goto('/ideas/CUST-1?evaluate=1')
  const dialog = sheet(page)
  await expect(dialog).toBeVisible()
  await expect(dialog).toContainText('Due tomorrow')
  await score(dialog, 'Effort', '3')
  await page.keyboard.press('Escape')
  await expect(dialog).toBeHidden()
  await expect(page).toHaveURL(/\/ideas\/CUST-1$/)
  // Focus goes back to the page's primary action.
  await expect(page.locator('[data-primary-action]:visible')).toBeFocused()
  await expect(page.locator('[data-primary-action]:visible')).toHaveAccessibleName(
    'Continue evaluation',
  )

  await page.keyboard.press('e')
  await expect(
    sheet(page).getByRole('radiogroup', { name: 'Effort' }).getByRole('radio', { name: '3' }),
  ).toBeChecked()
})

test('?evaluate=1 is ignored for someone who isn’t an evaluator', async ({ page }) => {
  await page.goto('/ideas/CUST-2?evaluate=1')
  await expect(
    page.getByRole('heading', { level: 1, name: 'Print-free returns with a QR code' }),
  ).toBeVisible()
  await expect(page).toHaveURL(/\/ideas\/CUST-2$/)
  await expect(sheet(page)).toHaveCount(0)
})

test('a draft saved earlier comes back, and the reveal can be edited again', async ({ page }) => {
  // Alice has a draft on TOOL-1 "Shared test data service".
  await page.goto('/ideas/TOOL-1')
  const primary = page.locator('[data-primary-action]:visible')
  await expect(primary).toHaveAccessibleName('Continue evaluation')
  await primary.click()
  const dialog = sheet(page)
  await expect(dialog.getByText(/^Draft saved/)).toBeVisible()
  for (const criterion of CRITERIA) await score(dialog, criterion, '4')
  await recommend(dialog, 'Maybe')
  await dialog.getByRole('button', { name: /^Submit/ }).click()
  const reveal = page.getByRole('dialog', { name: 'Your evaluation' })
  await expect(reveal).toBeVisible()

  await reveal.getByRole('button', { name: 'Edit my evaluation' }).click()
  const edit = sheet(page)
  const save = edit.getByRole('button', { name: /^Save changes/ })
  await expect(save).toBeDisabled()
  await score(edit, 'Value', '5')
  await save.click()
  await expect(page.getByRole('dialog', { name: 'Your evaluation' })).toBeVisible()
  await expect(
    page
      .getByRole('dialog', { name: 'Your evaluation' })
      .getByRole('img', { name: 'Your score: 5 out of 5' }),
  ).toBeVisible()
})

test.describe('on a phone (390 px, touch)', () => {
  test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true })

  test('evaluates from the bottom bar in a full-height sheet', async ({ page }) => {
    await page.goto('/ideas/CUST-1')
    await expect(
      page.getByRole('heading', { level: 1, name: 'Self-serve returns portal' }),
    ).toBeVisible()
    // The sidebar folds into a summary line; its details are one tap away.
    await expect(
      page.getByRole('img', { name: 'Scores hidden until you submit your evaluation' }),
    ).toBeVisible()

    const bar = page.locator('[data-primary-action]:visible')
    await expect(bar).toHaveAccessibleName('Evaluate')
    const barBox = await bar.boundingBox()
    expect(Math.round(barBox?.height ?? 0)).toBeGreaterThanOrEqual(44)
    await bar.tap()

    const dialog = sheet(page)
    await expect(dialog).toBeVisible()
    const box = await dialog.boundingBox()
    expect(box?.height).toBeGreaterThan(800)
    expect(box?.width).toBe(390)
    // No keyboard on a phone: focus isn't parked on a score.
    await expect(dialog.getByRole('radio', { checked: true })).toHaveCount(0)

    const radio = dialog
      .getByRole('radiogroup', { name: 'Value' })
      .getByRole('radio', { name: '4' })
    const radioBox = await radio.boundingBox()
    expect(Math.round(radioBox?.height ?? 0)).toBeGreaterThanOrEqual(44)
    for (const criterion of CRITERIA) {
      await dialog
        .getByRole('radiogroup', { name: criterion })
        .getByRole('radio', { name: '4' })
        .tap()
    }
    // Tapping shows what the score means.
    await expect(
      dialog
        .locator('[data-slot="segmented-guidance"]', { hasText: '4 · Between 3 and 5' })
        .first(),
    ).toBeVisible()
    await dialog
      .getByRole('radiogroup', { name: 'Overall recommendation' })
      .getByRole('radio', { name: 'Go' })
      .tap()
    const submit = dialog.getByRole('button', { name: /^Submit/ })
    await expect(submit).toBeInViewport()
    await submit.tap()
    await expect(page.getByRole('dialog', { name: 'Your evaluation' })).toBeVisible()
    await page
      .getByRole('dialog', { name: 'Your evaluation' })
      .getByRole('button', { name: 'Done' })
      .tap()
    await expect(page.getByRole('img', { name: /^Score \d\.\d out of 5/ })).toBeVisible()
  })

  test('the details sheet holds the sidebar', async ({ page }) => {
    await page.goto('/ideas/CUST-2')
    await page.getByRole('button', { name: 'Details' }).tap()
    const panel = page.getByRole('dialog', { name: 'Details' })
    await expect(panel.getByRole('button', { name: /^Status:/ })).toBeVisible()
    await expect(panel.getByRole('list', { name: 'Evaluators' })).toBeVisible()
    await expect(panel.getByRole('meter')).toHaveCount(5)
    // Opening a picker from the sheet hands over to its dialog.
    await panel.getByRole('button', { name: /^Status:/ }).tap()
    await expect(page.getByRole('dialog', { name: 'Change status' })).toBeVisible()
    await expect(panel).toBeHidden()
  })
})
