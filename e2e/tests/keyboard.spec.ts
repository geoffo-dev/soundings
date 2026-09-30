import type { Page } from '@playwright/test'

import { createTeamProject } from './support/api'
import { evaluateSheet, expect, heading, openIdea, signIn, test } from './support/fixtures'

/**
 * Keyboard use against the real stack: ⌘K / Ctrl+K jumps, "n" new idea, "e" evaluate,
 * "?" shortcut sheet, j/k in lists. Test plan: KB-*.
 */

async function openPalette(page: Page) {
  await page.keyboard.press('ControlOrMeta+k')
  const palette = page.getByRole('dialog', { name: 'Command palette' })
  await expect(palette.getByRole('combobox')).toBeFocused()
  return palette
}

test('KB-01: ⌘K jumps to an idea by key or title, and to a project', async ({ page }) => {
  await signIn(page, 'alice')
  await page.goto('/')
  await expect(heading(page, 'My work')).toBeVisible()

  let palette = await openPalette(page)
  await page.keyboard.type('cust-7')
  // An exact key match is the first result.
  await expect(palette.getByRole('option').first()).toContainText('In-app onboarding checklist')
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(/\/ideas\/CUST-7$/)
  await expect(heading(page, 'In-app onboarding checklist')).toBeVisible()

  palette = await openPalette(page)
  await page.keyboard.type('flag clean-up')
  await expect(
    palette.getByRole('option', { name: /Feature-flag clean-up reminders/ }),
  ).toBeVisible()
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(/\/ideas\/TOOLS-9$/)
  await expect(heading(page, 'Feature-flag clean-up reminders')).toBeVisible()

  palette = await openPalette(page)
  await page.keyboard.type('sustainab')
  // Wait for the server's idea results, then arrow down to the project and open it.
  await expect(
    palette.getByRole('group', { name: 'Ideas' }).getByRole('option').first(),
  ).toBeVisible()
  const project = palette
    .getByRole('group', { name: 'Go to' })
    .getByRole('option', { name: /^Sustainability/ })
  for (let i = 0; i < 10; i += 1) {
    if ((await project.getAttribute('aria-selected')) === 'true') break
    await page.keyboard.press('ArrowDown')
  }
  await expect(project).toHaveAttribute('aria-selected', 'true')
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(/\/p\/sustainability(\?.*)?$/)
  await expect(heading(page, 'Sustainability')).toBeVisible()

  // Nothing found is said plainly; Esc closes.
  palette = await openPalette(page)
  await page.keyboard.type('zzqxv')
  await expect(palette.getByText('No results for “zzqxv”')).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(palette).toBeHidden()
})

test('KB-02: "n" submits a new idea into the project in view', async ({ page, api }) => {
  const alice = await api('alice')
  const project = await createTeamProject(alice, 'Keyboard', { erin: 'member' })
  await signIn(page, 'erin')
  await page.goto(`/p/${project.slug}`)
  await expect(heading(page, project.name)).toBeVisible()

  await page.keyboard.press('n')
  const dialog = page.getByRole('dialog', { name: 'New idea' })
  await expect(dialog.getByRole('textbox', { name: 'Title' })).toBeFocused()
  // Erin can submit to this project only, so it is named instead of offered in a picker.
  await expect(dialog.getByRole('combobox', { name: 'Project' })).toHaveCount(0)
  await expect(dialog).toContainText(project.name)
  await page.keyboard.type('Keyboard-only idea')
  await page.keyboard.press('Tab')
  await expect(dialog.getByRole('textbox', { name: 'Summary' })).toBeFocused()
  await page.keyboard.type('Everything here was typed, nothing clicked.')
  await page.keyboard.press('ControlOrMeta+Enter')

  const key = `${project.key}-1`
  await expect(page).toHaveURL(new RegExp(`/ideas/${key}$`))
  await expect(heading(page, 'Keyboard-only idea')).toBeVisible()
  const saved = await alice.idea(key)
  expect(saved).toMatchObject({
    title: 'Keyboard-only idea',
    summary: 'Everything here was typed, nothing clicked.',
    status: 'new',
  })
  expect(saved.submitted_by?.display_name).toBe('Erin Evans')
})

test('KB-03: "e" opens the evaluate sheet; digits score; Esc keeps the draft', async ({
  page,
  api,
}) => {
  const alice = await api('alice')
  const project = await createTeamProject(alice, 'Keyboard eval', { sven: 'member' })
  const idea = await alice.createIdea(project.slug, {
    title: 'Dark mode for the returns page',
    summary: 'Match the app’s theme on the returns page.',
  })
  await alice.invite(idea.key, ['sven'])

  await signIn(page, 'sven')
  await openIdea(page, idea.key)
  await page.keyboard.press('e')
  const sheet = evaluateSheet(page)
  await expect(sheet).toBeVisible()
  await expect(page).toHaveURL(/evaluate=1/)
  const value = sheet.getByRole('radiogroup', { name: 'Value', exact: true })
  await expect(value.getByRole('radio', { name: '1', exact: true })).toBeFocused()
  await page.keyboard.press('4')
  await expect(value.getByRole('radio', { name: '4', exact: true })).toBeChecked()
  await expect(sheet.getByText(/^Draft saved/)).toBeVisible()

  await page.keyboard.press('Escape')
  await expect(sheet).toBeHidden()
  await expect(page).not.toHaveURL(/evaluate=1/)
  const sven = await api('sven')
  const mine = await sven.get<{ state: string; scores: { score: number | null }[] }>(
    `/ideas/${idea.key}/evaluations/me`,
  )
  expect(mine.state).toBe('draft')
  expect(mine.scores.map((score) => score.score)).toContain(4)

  await page.keyboard.press('e')
  await expect(
    evaluateSheet(page)
      .getByRole('radiogroup', { name: 'Value', exact: true })
      .getByRole('radio', { name: '4', exact: true }),
  ).toBeChecked()
})

test('KB-04: "?" lists the shortcuts', async ({ page }) => {
  await signIn(page, 'alice')
  await openIdea(page, 'CUST-12')
  await page.keyboard.press('?')
  const sheet = page.getByRole('dialog', { name: 'Keyboard shortcuts' })
  await expect(sheet).toBeVisible()
  for (const label of ['New idea', 'Change status', 'Assign owner', 'Evaluate']) {
    await expect(sheet.getByText(label, { exact: false }).first()).toBeVisible()
  }
  await page.keyboard.press('Escape')
  await expect(sheet).toBeHidden()
})

test('KB-05: j/k move through the list and Enter opens the idea', async ({ page }) => {
  await signIn(page, 'alice')
  await page.goto('/p/customer-innovation?view=list&sort=title')
  await expect(heading(page, 'Customer Innovation')).toBeVisible()
  const links = page.getByRole('table', { name: 'Ideas' }).getByRole('link')
  await expect(links.first()).toBeVisible()
  await page.keyboard.press('j')
  await expect(links.nth(0)).toBeFocused()
  await page.keyboard.press('j')
  await expect(links.nth(1)).toBeFocused()
  await page.keyboard.press('k')
  await expect(links.nth(0)).toBeFocused()
  const title = (await links.nth(0).innerText()).split('\n').pop() ?? ''
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(/\/ideas\/CUST-\d+$/)
  await expect(heading(page, title.trim())).toBeVisible()
})

test('KB-06: ⌘K keeps your selection when search results arrive', async ({ page }) => {
  // A slow network: the idea results arrive after you have already picked something.
  await signIn(page, 'alice')
  await page.goto('/')
  await expect(heading(page, 'My work')).toBeVisible()
  await page.route('**/api/v1/search?*', async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 800))
    await route.continue()
  })
  const palette = await openPalette(page)
  await page.keyboard.type('sustainab')
  const project = palette
    .getByRole('group', { name: 'Go to' })
    .getByRole('option', { name: /^Sustainability/ })
  await expect(project).toBeVisible()
  for (let i = 0; i < 10; i += 1) {
    if ((await project.getAttribute('aria-selected')) === 'true') break
    await page.keyboard.press('ArrowDown')
  }
  await expect(project).toHaveAttribute('aria-selected', 'true')
  // The ideas arrive…
  await expect(
    palette.getByRole('group', { name: 'Ideas' }).getByRole('option').first(),
  ).toBeVisible()
  // …and Enter still opens what was selected.
  await expect(project).toHaveAttribute('aria-selected', 'true')
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(/\/p\/sustainability(\?.*)?$/)
})

test('KB-07: Ctrl/⌘+K straight after a palette jump reopens it, and typing stays in it', async ({
  page,
}) => {
  // Off macOS the shortcut is Ctrl+K, which cmdk also binds ("move up"): pressed while
  // the palette was still closing, it was swallowed, and the next letter reached the
  // idea page ("s" opened Change status).
  await signIn(page, 'alice')
  await page.goto('/')
  await expect(heading(page, 'My work')).toBeVisible()
  await page.route('**/api/v1/ideas/CUST-7', async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 600))
    await route.continue()
  })
  const palette = await openPalette(page)
  await page.keyboard.type('cust-7')
  await expect(palette.getByRole('option').first()).toContainText('In-app onboarding checklist')
  await page.keyboard.press('Enter')
  await page.keyboard.press('ControlOrMeta+k')
  await expect(page).toHaveURL(/\/ideas\/CUST-7$/)
  // The idea page renders behind the open palette (hidden from the accessibility tree).
  await expect(page.locator('h1', { hasText: 'In-app onboarding checklist' })).toBeAttached()
  await expect(palette.getByRole('combobox')).toBeFocused()
  await page.keyboard.type('s')
  await expect(palette.getByRole('combobox')).toHaveValue('s')
  await expect(page.getByRole('dialog', { name: 'Change status' })).toHaveCount(0)
})
