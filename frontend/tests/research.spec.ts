import type { Locator, Page } from '@playwright/test'

import { bestPracticeViolations, expect, seriousViolations, test, USERS } from './support'

/**
 * Phase 8, the research step (contract-phase8 §3.13). Internal Tools has the step
 * before evaluation: TOOL-7 (owner Bob) has one required item open, TOOL-10 (owner
 * Farid) is complete. Alice is a TOOL admin (she may "Move anyway"); Bob is a member.
 */

const BOB = '10000000-0000-4000-8000-000000000003'
const DAVE = '10000000-0000-4000-8000-000000000005'

const column = (page: Page, label: string) =>
  page.getByRole('region', { name: new RegExp(`^${label}\\b`) })
const card = (scope: Page | Locator, key: string) =>
  scope.getByRole('link', { name: new RegExp(`\\(${key}\\)$`) })
const toast = (page: Page, text: string) => page.locator('[data-sonner-toast]', { hasText: text })
const gate = (page: Page) => page.getByRole('dialog', { name: 'Finish the research first' })

async function openBoard(page: Page) {
  await page.goto('/p/internal-tools')
  await expect(page.getByRole('heading', { level: 1, name: 'Internal Tools' })).toBeVisible()
  await expect(card(column(page, 'Research'), 'TOOL-7')).toBeVisible()
}

async function moveWithKeyboard(page: Page, key: string, steps: number) {
  await card(page, key).focus()
  await page.keyboard.press('Space')
  for (let i = 0; i < steps; i += 1) await page.keyboard.press('ArrowRight')
  await page.keyboard.press('Space')
}

test.describe('the board', () => {
  test('shows the Research column where the step puts it, with checklist progress', async ({
    page,
  }) => {
    await openBoard(page)
    await expect(column(page, 'Research').getByRole('heading', { level: 2 })).toHaveText(
      'Research2',
    )
    // Between New and Evaluating.
    const x = async (label: string) => (await column(page, label).boundingBox())?.x ?? 0
    expect(await x('New')).toBeLessThan(await x('Research'))
    expect(await x('Research')).toBeLessThan(await x('Evaluating'))
    await expect(
      card(page, 'TOOL-7').getByRole('img', {
        name: 'Research 1 of 3 answered, 1 required item open',
      }),
    ).toBeVisible()
    await expect(
      card(page, 'TOOL-10').getByRole('img', { name: 'Research 3 of 3 answered, complete' }),
    ).toBeVisible()
    // Past Research: no badge.
    await expect(card(page, 'TOOL-1').getByRole('img', { name: /^Research/ })).toHaveCount(0)
    expect(await seriousViolations(page)).toEqual([])
  })

  test('a refused move snaps back and explains; an admin moves it anyway', async ({ page }) => {
    await openBoard(page)
    await moveWithKeyboard(page, 'TOOL-7', 1)
    await expect(gate(page)).toBeVisible()
    await expect(gate(page)).toContainText('TOOL-7 can’t move to Evaluating')
    await expect(gate(page).getByRole('list', { name: 'Open research items' })).toContainText(
      'Departments or teams consulted',
    )
    expect(await seriousViolations(page)).toEqual([])

    await gate(page).getByRole('button', { name: 'Move anyway…' }).click()
    const reason = gate(page).getByRole('textbox', { name: 'Reason (optional)' })
    await expect(reason).toBeFocused()
    await reason.fill('Legal agreed on a call')
    await gate(page).getByRole('button', { name: 'Move anyway' }).click()
    await expect(gate(page)).toHaveCount(0)
    await expect(card(column(page, 'Evaluating'), 'TOOL-7')).toBeVisible()
    await expect(toast(page, 'TOOL-7 moved to Evaluating')).toBeVisible()
  })

  test('closing the dialog puts focus back on the card', async ({ page }) => {
    await openBoard(page)
    await moveWithKeyboard(page, 'TOOL-7', 1)
    await expect(gate(page)).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(card(column(page, 'Research'), 'TOOL-7')).toBeFocused()
  })

  test.describe('as the owner (a member)', () => {
    test.use({ signedInAs: BOB })

    test('offers Open research, not Move anyway', async ({ page }) => {
      await openBoard(page)
      await moveWithKeyboard(page, 'TOOL-7', 1)
      await expect(gate(page)).toBeVisible()
      await expect(gate(page).getByRole('button', { name: /anyway/ })).toHaveCount(0)
      await gate(page).getByRole('button', { name: 'Open research' }).click()
      await expect(page).toHaveURL(/\/ideas\/TOOL-7#research$/)
      await expect(
        page.getByRole('textbox', { name: 'Departments or teams consulted' }),
      ).toBeFocused()
    })
  })
})

test.describe('the list', () => {
  test('filters by Research and shows the progress next to the status', async ({ page }) => {
    await page.goto('/p/internal-tools?view=list')
    await page.getByRole('button', { name: /^Status/ }).click()
    await page.getByRole('option', { name: 'Research' }).click()
    await page.keyboard.press('Escape')
    await expect(page).toHaveURL(/status=research/)
    const rows = page
      .getByRole('table', { name: 'Ideas' })
      .getByRole('row')
      .filter({ has: page.getByRole('link') })
    await expect(rows).toHaveCount(2)
    await expect(
      rows.filter({ hasText: 'TOOL-7' }).getByRole('img', {
        name: 'Research 1 of 3 answered, 1 required item open',
      }),
    ).toBeVisible()
  })
})

test.describe('the idea page', () => {
  test.use({ signedInAs: BOB })

  test('⌘K opens the checklist at its first open item', async ({ page }) => {
    await page.goto('/ideas/TOOL-7?tab=evaluations')
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
    await page.keyboard.press('ControlOrMeta+k')
    const palette = page.getByRole('dialog', { name: 'Command palette' })
    await expect(palette.getByRole('combobox')).toBeFocused()
    await page.keyboard.type('research')
    await palette.getByRole('option', { name: 'Answer the research checklist' }).click()
    await expect(
      page.getByRole('textbox', { name: 'Departments or teams consulted' }),
    ).toBeFocused()
  })

  test('the owner answers, the gate opens, and the primary action follows', async ({ page }) => {
    await page.goto('/ideas/TOOL-7')
    const panel = page.getByRole('region', { name: 'Research' })
    await expect(panel).toContainText('1 of 3 answered')
    await expect(panel).toContainText('1 required item left before Evaluating')
    await expect(page.getByRole('button', { name: 'Finish research' }).first()).toBeVisible()
    await expect(panel.getByRole('heading', { name: 'Similar ideas' })).toBeVisible()
    await expect(panel.getByRole('link', { name: /Cost dashboard per team/ })).toBeVisible()
    expect(await seriousViolations(page)).toEqual([])
    expect(await bestPracticeViolations(page)).toEqual([])

    await page.getByRole('button', { name: 'Finish research' }).first().click()
    const field = page.getByRole('textbox', { name: 'Departments or teams consulted' })
    await expect(field).toBeFocused()
    await field.fill('Legal (contracts team), 3 Oct: fine if we keep the standard terms')
    await panel.getByRole('button', { name: 'Save answer' }).click()
    await expect(field).toBeFocused()
    await expect(panel).toContainText('Research complete')
    await expect(panel).toContainText('Answered by Bob Chen')
    await expect(page.getByRole('button', { name: 'Start evaluation' }).first()).toBeVisible()

    await page.getByRole('button', { name: 'Start evaluation' }).first().click()
    await expect(toast(page, 'TOOL-7 moved to Evaluating')).toBeVisible()
  })

  test('clearing an answer can be undone', async ({ page }) => {
    await page.goto('/ideas/TOOL-7')
    const panel = page.getByRole('region', { name: 'Research' })
    await panel
      .getByRole('button', { name: 'Clear the answer to Not already being done elsewhere' })
      .click()
    await expect(panel).toContainText('0 of 3 answered')
    await toast(page, 'cleared').getByRole('button', { name: 'Undo' }).click()
    await expect(panel).toContainText('1 of 3 answered')
  })

  test.describe('as a member who doesn’t own it', () => {
    test.use({ signedInAs: DAVE })

    test('reads the answers, nothing to edit', async ({ page }) => {
      await page.goto('/ideas/TOOL-10')
      const panel = page.getByRole('region', { name: 'Research' })
      await expect(panel).toContainText('Legal (contracts team), 3 Oct')
      await expect(panel.getByRole('textbox')).toHaveCount(0)
      await expect(panel.getByRole('button', { name: /Clear/ })).toHaveCount(0)
    })
  })
})

test.describe('project settings', () => {
  test('Research: the step, its lock while ideas are in Research, and the checklist', async ({
    page,
  }) => {
    await page.goto('/p/internal-tools/settings?tab=research')
    await expect(page.getByRole('heading', { name: 'Research step' })).toBeVisible()
    await expect(
      page.getByText('Move the 2 ideas in Research to another status first'),
    ).toBeVisible()
    await expect(page.getByRole('radio', { name: 'Off' })).toBeDisabled()
    await expect(
      page.getByRole('list', { name: 'Checklist items' }).getByRole('listitem'),
    ).toHaveCount(3)
    expect(await seriousViolations(page)).toEqual([])

    // The checklist can still change: make data protection required, then save.
    await page.getByRole('switch').last().click()
    await page.getByRole('button', { name: 'Save research step' }).click()
    await expect(toast(page, 'Research step saved')).toBeVisible()
  })

  test('members read the step without changing it', async ({ page }) => {
    await page.goto('/p/customer-innovation/settings?tab=research')
    // Alice isn't a CUST admin: Priya is.
    await expect(page.getByText('Only project admins can change the research step')).toBeVisible()
  })

  test.describe('as a platform admin', () => {
    test.use({ signedInAs: USERS.priya })

    test('turning the step on offers the default checklist', async ({ page }) => {
      await page.goto('/p/customer-innovation/settings?tab=research')
      await page.getByRole('radio', { name: 'Before proposal' }).check()
      await expect(page.getByText('We filled in the default checklist')).toBeVisible()
      await expect(
        page.getByRole('list', { name: 'Checklist items' }).getByRole('listitem'),
      ).toHaveCount(3)
      await page.getByRole('button', { name: 'Save research step' }).click()
      await expect(toast(page, 'Research step saved: before proposal')).toBeVisible()
      // In the app (a reload would reset the mock data).
      await page.getByRole('link', { name: 'Back to ideas' }).click()
      await expect(column(page, 'Research')).toBeVisible()
    })
  })
})
