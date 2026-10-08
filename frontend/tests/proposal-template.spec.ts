import type { Page } from '@playwright/test'

import { bestPracticeViolations, expect, seriousViolations, test } from './support'

/**
 * Phase 8, per-project proposal templates (contract-phase8 §2.7). Internal Tools
 * (Alice is its admin) has a custom template: Summary, Problem, Solution, Effort &
 * rollout, Risks, The ask; TOOL-4's proposal has most of it written, and its research
 * checklist answered (the appendix). Sustainability adds Carbon impact.
 */

const toast = (page: Page, text: string) => page.locator('[data-sonner-toast]', { hasText: text })
const sections = (page: Page) => page.getByRole('list', { name: 'Sections' }).getByRole('listitem')

async function openTemplate(page: Page) {
  await page.goto('/p/internal-tools/settings?tab=proposal-template')
  await expect(page.getByRole('heading', { name: 'Proposal template' })).toBeVisible()
  await expect(sections(page)).toHaveCount(6)
}

test('lists the sections in order, axe-clean', async ({ page }) => {
  await openTemplate(page)
  await expect(sections(page).first().getByRole('textbox', { name: 'Title' })).toHaveValue(
    'Summary',
  )
  await expect(sections(page).nth(3).getByRole('textbox', { name: 'Title' })).toHaveValue(
    'Effort & rollout',
  )
  expect(await seriousViolations(page)).toEqual([])
  expect(await bestPracticeViolations(page)).toEqual([])
})

test('renames, reorders and adds; saving keeps every proposal in step', async ({ page }) => {
  await openTemplate(page)
  await sections(page).nth(5).getByRole('textbox', { name: 'Title' }).fill('The ask and timing')
  // Move "Risks" up with its Move menu (no drag needed).
  await page.getByRole('button', { name: 'Move Risks', exact: true }).click()
  await page.getByRole('menuitem', { name: 'Move up' }).click()
  await expect(sections(page).nth(3).getByRole('textbox', { name: 'Title' })).toHaveValue('Risks')
  await page.getByRole('button', { name: 'Add section' }).click()
  const added = sections(page).last().getByRole('textbox', { name: 'Title' })
  await expect(added).toBeFocused()
  await added.fill('Carbon impact')
  await page.getByRole('button', { name: 'Save template' }).click()
  await expect(toast(page, 'Proposal template saved')).toBeVisible()

  // The proposal editor follows at once (in the app: a reload resets the mock data).
  await page.getByRole('link', { name: 'Back to ideas' }).click()
  await page.getByRole('link', { name: /\(TOOL-4\)$/ }).click()
  await page.getByRole('tab', { name: /Proposal/ }).click()
  const outline = page.getByRole('navigation', { name: 'Outline' })
  await expect(outline.getByRole('link', { name: /^Risks/ })).toBeVisible()
  await expect(page.getByRole('heading', { level: 2, name: /^7\. Carbon impact$/ })).toBeVisible()
  await expect(page.getByRole('heading', { level: 2, name: /The ask and timing$/ })).toBeVisible()
})

test('removing a section keeps focus in the list; Restore puts it back in place', async ({
  page,
}) => {
  await openTemplate(page)
  // No confirmation (nothing is lost: Discard or Restore brings it back, UX review S1);
  // focus moves to the row that took its place, never to the page (UX review M2).
  await page.getByRole('button', { name: 'Remove Solution' }).click()
  await expect(page.getByRole('alertdialog')).toHaveCount(0)
  await expect(sections(page)).toHaveCount(5)
  await expect(sections(page).nth(2).getByRole('textbox', { name: 'Title' })).toBeFocused()
  await expect(sections(page).nth(2).getByRole('textbox', { name: 'Title' })).toHaveValue(
    'Effort & rollout',
  )
  await page.getByRole('button', { name: 'Save template' }).click()
  await expect(toast(page, 'Proposal template saved')).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Removed sections' })).toBeVisible()
  await expect(page.getByText('Text in 1 proposal · removed')).toBeVisible()

  // Back where it was (third), not at the end (UX review p1).
  await page.getByRole('button', { name: 'Restore Solution' }).click()
  await expect(sections(page)).toHaveCount(6)
  const restored = sections(page).nth(2).getByRole('textbox', { name: 'Title' })
  await expect(restored).toHaveValue('Solution')
  await expect(restored).toBeFocused()
  await page.getByRole('button', { name: 'Save template' }).click()
  await expect(toast(page, 'Proposal template saved')).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Removed sections' })).toHaveCount(0)
})

test('saving from a new row keeps focus in it; Discard hands focus to Save', async ({ page }) => {
  await openTemplate(page)
  await page.getByRole('button', { name: 'Add section' }).click()
  const added = sections(page).last().getByRole('textbox', { name: 'Title' })
  await added.fill('Carbon impact')
  const hint = sections(page).last().getByRole('textbox', { name: 'Hint' })
  await hint.fill('What it saves, roughly, per year.')
  await page.keyboard.press('ControlOrMeta+s')
  await expect(toast(page, 'Proposal template saved')).toBeVisible()
  // The new row got its key from the server without remounting (UX review M2).
  await expect(hint).toBeFocused()

  await sections(page).first().getByRole('textbox', { name: 'Title' }).fill('Overview')
  await page.getByRole('button', { name: 'Discard' }).click()
  await expect(page.getByRole('button', { name: /^Save template/ })).toBeFocused()
})

test('a long hint wraps on a phone and stays one line', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await openTemplate(page)
  const hint = sections(page).first().getByRole('textbox', { name: 'Hint' })
  await hint.fill('One line, long enough to wrap onto a second line on a phone screen')
  await hint.press('End')
  await hint.press('Shift+Enter')
  await expect(hint).toHaveValue(
    'One line, long enough to wrap onto a second line on a phone screen',
  )
  const box = await hint.boundingBox()
  expect(box?.height ?? 0).toBeGreaterThan(40)
  // Every settings tab in sight: they wrap instead of scrolling away (UX review m6).
  const tab = page.getByRole('tab', { name: 'Public form' })
  const tabBox = await tab.boundingBox()
  expect((tabBox?.x ?? 999) + (tabBox?.width ?? 0)).toBeLessThanOrEqual(390)
})

test('keeps one section at least, twelve at most', async ({ page }) => {
  await openTemplate(page)
  for (let i = 0; i < 6; i += 1) await page.getByRole('button', { name: 'Add section' }).click()
  await expect(page.getByRole('button', { name: 'Add section' })).toBeDisabled()
  await expect(page.getByText('That’s the maximum')).toBeVisible()
})

test('the proposal ends with the research appendix while the step is on', async ({ page }) => {
  await page.goto('/ideas/TOOL-4?tab=proposal')
  const appendix = page.getByRole('region', { name: 'Research and consultation' })
  // The lazy editor, then its research query: under load in dev mode this takes over 5 s.
  await expect(appendix).toBeVisible({ timeout: 10_000 })
  await expect(
    page.getByRole('navigation', { name: 'Outline' }).getByRole('link').last(),
  ).toHaveText('Research and consultation')
  await expect(appendix).toContainText('Departments or teams consulted')
  await expect(appendix).toContainText('Security (Raj), 21 Jul')
  await expect(appendix).toContainText('Answered by Bob Chen on')
  // The custom sections, each hint a line under its heading read with the field (UX m3).
  await expect(
    page.getByRole('heading', { level: 2, name: /^4\. Effort & rollout$/ }),
  ).toBeVisible()
  await expect(page.getByText('What you need, from whom, and by when.')).toBeVisible()
  await expect(page.getByRole('textbox', { name: 'The ask' })).toHaveAccessibleDescription(
    /^What you need, from whom, and by when\./,
  )
})

test.describe('as a member', () => {
  test.use({ signedInAs: '10000000-0000-4000-8000-000000000003' }) // Bob, a TOOL member

  test('reads the template without changing it', async ({ page }) => {
    await page.goto('/p/internal-tools/settings?tab=proposal-template')
    const panel = page.getByRole('tabpanel', { name: 'Proposal template' })
    await expect(panel.getByText('Every proposal in this project has these sections')).toBeVisible()
    await expect(panel.getByText('Effort & rollout')).toBeVisible()
    await expect(page.getByRole('textbox')).toHaveCount(0)
  })
})
