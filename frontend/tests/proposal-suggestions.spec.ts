import type { Page } from '@playwright/test'

import { expect, seriousViolations, test, USERS } from './support'

/**
 * Suggestions in the proposal editor (contract-phase5 §3.4 "The editor")
 * against the mock. CUST-3 (Proposal, owner Alice) has four pending ones:
 * Summary from Carol (through MCP) and from the Research agent (AI), Problem
 * from Bob (written against an older version) and Benefits / revenue from the
 * Research agent.
 */

const CAROL = '10000000-0000-4000-8000-000000000004'

const section = (page: Page, name: string) => page.getByRole('region', { name, exact: true })
const card = (page: Page, author: string | RegExp) =>
  page
    .locator('article[id^="proposal-suggestion-"]')
    .filter({ has: page.getByText(author, { exact: true }) })
const toast = (page: Page, text: string | RegExp) =>
  page.locator('[data-sonner-toast]', { hasText: text })

const CAROL_SUMMARY_END = 'about **£48,000 a month** at 2,000 boxes.'

const proposalTab = (page: Page) => page.getByRole('tab', { name: /^Proposal/ })

async function openProposal(page: Page) {
  await page.goto('/ideas/CUST-3?tab=proposal')
  await expect(page.getByRole('tab', { name: /^Proposal/, selected: true })).toBeVisible()
  await expect(page.getByTestId('proposal-editor')).toBeVisible()
}

async function storedSection(page: Page, key: string): Promise<{ body: string; version: number }> {
  return page.evaluate(async (key) => {
    const response = await fetch('/api/v1/ideas/CUST-3/proposal')
    const view = (await response.json()) as {
      proposal: { sections: { key: string; body_md: string; version: number }[] }
    }
    const found = view.proposal.sections.find((s) => s.key === key)
    return { body: found?.body_md ?? '', version: found?.version ?? 0 }
  }, key)
}

async function pendingIds(page: Page): Promise<string[]> {
  return page.evaluate(async () => {
    const response = await fetch('/api/v1/ideas/CUST-3/proposal/suggestions')
    const list = (await response.json()) as { items: { id: string }[] }
    return list.items.map((item) => item.id)
  })
}

test('shows pending suggestions by their section, with who, how and what they change', async ({
  page,
}) => {
  await openProposal(page)
  await expect(page.getByRole('button', { name: /^4 suggestions/ })).toBeVisible()
  // The owner sees what waits for them on the tab itself.
  await expect(proposalTab(page)).toHaveAccessibleName(/^Proposal\s*, 4 suggestions to decide on$/)
  const outline = page.getByRole('navigation', { name: 'Outline' })
  await expect(outline.getByRole('link', { name: /^Summary.*2 suggestions/ })).toBeVisible()

  const summary = section(page, '1. Summary')
  await expect(summary.getByRole('heading', { name: '2 suggestions for Summary' })).toBeVisible()
  const carol = card(page, 'Carol Díaz')
  await expect(carol).toContainText('via assistant')
  // Each card's scroll area says whose and which section it is.
  await expect(
    carol.getByRole('region', { name: 'Carol Díaz’s suggested changes to Summary' }),
  ).toBeVisible()
  // The diff names what goes and what comes, not by colour alone.
  await expect(carol.getByText('Removed:').first()).toBeAttached()
  await expect(carol.getByText('Added:').first()).toBeAttached()
  await expect(carol).toContainText('6 points')
  const agent = card(page, 'Research agent').first()
  // The AI badge ("AI", read as "AI agent"), and a reminder to check its facts.
  await expect(agent).toContainText('AI agent')
  await expect(agent).toContainText('check the facts')
  // An edited line shows which words changed, not just a whole new paragraph.
  await expect(carol.locator('ins').first()).toBeAttached()

  // Switch to the suggested text, rendered as Markdown.
  await carol.getByRole('radio', { name: 'Suggested text' }).click()
  await expect(carol.locator('strong', { hasText: '£48,000 a month' })).toBeVisible()

  // Bob read an older version of Problem.
  await expect(card(page, 'Bob Chen')).toContainText(
    'The section has changed since this was suggested',
  )
  await expect(section(page, '6. Benefits / revenue')).toContainText('1 suggestion')
})

test('the jump button takes you to the first suggestion', async ({ page }) => {
  await openProposal(page)
  await page.getByRole('button', { name: /^4 suggestions/ }).click()
  await expect(card(page, 'Carol Díaz')).toBeFocused()
})

test('accepting replaces the section, moves on to the next suggestion and offers Undo', async ({
  page,
}) => {
  await openProposal(page)
  const before = await storedSection(page, 'summary')
  await card(page, 'Carol Díaz')
    .getByRole('button', { name: 'Accept: Carol Díaz’s suggestion for Summary' })
    .click()
  await expect(toast(page, 'Carol Díaz’s suggestion accepted')).toBeVisible()
  await expect(page.getByRole('textbox', { name: 'Summary' })).toHaveValue(
    new RegExp(CAROL_SUMMARY_END.replace(/[*£]/g, '.')),
  )
  await expect(card(page, 'Carol Díaz')).toHaveCount(0)
  await expect(card(page, 'Research agent').first()).toBeFocused()
  const after = await storedSection(page, 'summary')
  expect(after.version).toBe(before.version + 1)
  expect(after.body).toContain(CAROL_SUMMARY_END)
  // The other Summary suggestion now compares with the new text.
  await expect(card(page, 'Research agent').first()).toContainText(
    'The section has changed since this was suggested',
  )
  await expect(page.getByRole('button', { name: /^3 suggestions/ })).toBeVisible()

  // Undo puts the old text back (as a new save).
  await toast(page, 'Carol Díaz’s suggestion accepted')
    .getByRole('button', { name: 'Undo' })
    .click()
  await expect.poll(async () => (await storedSection(page, 'summary')).body).toBe(before.body)
  await expect(page.getByRole('textbox', { name: 'Summary' })).toHaveValue(before.body)
})

test('discarding hides it at once, with Undo; the request goes when the toast closes', async ({
  page,
}) => {
  await openProposal(page)
  const benefits = section(page, '6. Benefits / revenue')
  const discard = () =>
    benefits
      .getByRole('button', { name: 'Discard Research agent’s suggestion for Benefits / revenue' })
      .click()
  await discard()
  await expect(benefits.getByRole('article')).toHaveCount(0)
  await toast(page, 'Research agent’s suggestion discarded')
    .getByRole('button', { name: 'Undo' })
    .click()
  await expect(benefits.getByRole('article')).toHaveCount(1)
  // Undo brings the card back with focus on it.
  await expect(benefits.getByRole('article')).toBeFocused()
  expect(await pendingIds(page)).toHaveLength(4)

  await discard()
  await expect(benefits.getByRole('article')).toHaveCount(0)
  // Like a queue: none after it, so focus goes to the first one still waiting (Summary).
  await expect(card(page, 'Carol Díaz')).toBeFocused()
  // The toast closes by itself after 6 s; then the discard is sent.
  expect(await pendingIds(page)).toHaveLength(4)
  await expect.poll(() => pendingIds(page), { timeout: 15_000 }).toHaveLength(3)
})

test('a section saved meanwhile: the card says so, compares with that text, Accept anyway', async ({
  page,
}) => {
  await openProposal(page)
  await expect(page.getByRole('textbox', { name: 'Summary' })).toBeVisible()
  const { version } = await storedSection(page, 'summary')
  // Someone else saves Summary (same in-page mock API): the editor still shows the old text.
  await page.evaluate(
    async ({ version }) => {
      await fetch('/api/v1/ideas/CUST-3/proposal/sections/summary', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': 'playwright' },
        body: JSON.stringify({
          body_md: 'A shorter summary saved elsewhere.',
          base_version: version,
        }),
      })
    },
    { version },
  )
  const carol = card(page, 'Carol Díaz')
  await carol.getByRole('button', { name: 'Accept: Carol Díaz’s suggestion for Summary' }).click()
  const alert = carol.getByRole('alert')
  await expect(alert).toContainText('saved Summary a moment ago')
  await expect(carol).toContainText('A shorter summary saved elsewhere.')
  await carol
    .getByRole('button', { name: 'Accept anyway: Carol Díaz’s suggestion for Summary' })
    .click()
  await expect(toast(page, 'Carol Díaz’s suggestion accepted')).toBeVisible()
  const after = await storedSection(page, 'summary')
  expect(after.version).toBe(version + 2)
  expect(after.body).toContain(CAROL_SUMMARY_END)
  await expect(page.getByRole('textbox', { name: 'Summary' })).toHaveValue(after.body)
})

test('typing just before Accept: the autosave goes first, no question, Undo brings it back', async ({
  page,
}) => {
  await openProposal(page)
  const summary = page.getByRole('textbox', { name: 'Summary' })
  await summary.fill('Typed a moment ago.')
  // Accept straight away, while the autosave still waits.
  await card(page, 'Carol Díaz')
    .getByRole('button', { name: 'Accept: Carol Díaz’s suggestion for Summary' })
    .click()
  await expect(page.getByRole('alertdialog')).toHaveCount(0)
  await expect(toast(page, 'Carol Díaz’s suggestion accepted')).toBeVisible()
  expect((await storedSection(page, 'summary')).body).toContain(CAROL_SUMMARY_END)
  await toast(page, 'Carol Díaz’s suggestion accepted')
    .getByRole('button', { name: 'Undo' })
    .click()
  await expect
    .poll(async () => (await storedSection(page, 'summary')).body)
    .toBe('Typed a moment ago.')
})

test('unsaved edits in the section: accepting asks first', async ({ page }) => {
  await openProposal(page)
  // Saves fail, so what is typed stays unsaved.
  await page.evaluate(() => localStorage.setItem('soundings-mock-fail', '/proposal/sections'))
  const summary = page.getByRole('textbox', { name: 'Summary' })
  await summary.fill('My own summary, not saved.')
  await expect(section(page, '1. Summary').getByRole('alert').first()).toContainText('Not saved', {
    timeout: 5000,
  })
  await page.evaluate(() => localStorage.removeItem('soundings-mock-fail'))

  const accept = card(page, 'Carol Díaz').getByRole('button', {
    name: 'Accept: Carol Díaz’s suggestion for Summary',
  })
  await accept.click()
  const confirm = page.getByRole('alertdialog', { name: 'Replace your unsaved changes?' })
  await confirm.getByRole('button', { name: 'Keep editing' }).click()
  await expect(confirm).toHaveCount(0)
  await expect(summary).toHaveValue('My own summary, not saved.')
  await expect(accept).toBeFocused()

  await accept.click()
  await confirm.getByRole('button', { name: 'Accept suggestion' }).click()
  await expect(toast(page, 'Carol Díaz’s suggestion accepted')).toBeVisible()
  await expect(summary).toHaveValue(new RegExp(CAROL_SUMMARY_END.replace(/[*£]/g, '.')))
  expect((await storedSection(page, 'summary')).body).toContain(CAROL_SUMMARY_END)
})

test('when suggestions can’t load, the editor says so and retries', async ({ page }) => {
  await page.addInitScript(() =>
    localStorage.setItem('soundings-mock-fail', '/proposal/suggestions'),
  )
  await openProposal(page)
  const alert = page.getByRole('alert').filter({ hasText: 'Suggestions didn’t load' })
  await expect(alert).toBeVisible({ timeout: 10_000 })
  await expect(page.getByRole('textbox', { name: 'Summary' })).toBeEditable()
  await page.evaluate(() => localStorage.removeItem('soundings-mock-fail'))
  await alert.getByRole('button', { name: /Try again/ }).click()
  await expect(page.getByRole('button', { name: /^4 suggestions/ })).toBeVisible()
})

test.describe('as Carol (a member)', () => {
  test.use({ signedInAs: CAROL })

  test('sees what is waiting, her own as "You", but can’t decide', async ({ page }) => {
    await openProposal(page)
    await expect(card(page, 'You')).toContainText('via assistant')
    await expect(card(page, 'Research agent').first()).toBeVisible()
    await expect(page.getByRole('button', { name: /^Accept/ })).toHaveCount(0)
    await expect(page.getByRole('button', { name: /^Discard/ })).toHaveCount(0)
    // Who decides, and no count on the tab: nothing waits for her.
    await expect(card(page, 'You')).toContainText('Alice Anders decides whether to use it.')
    await expect(proposalTab(page)).toHaveAccessibleName('Proposal')
  })
})

test.describe('as a viewer (Emma)', () => {
  test.use({ signedInAs: USERS.emma })

  test('reads the suggestions, nothing else', async ({ page }) => {
    await openProposal(page)
    await expect(card(page, 'Carol Díaz')).toBeVisible()
    await expect(page.getByRole('button', { name: /^Accept/ })).toHaveCount(0)
    // Readers get the proposed text first, not a raw-Markdown diff.
    await expect(
      card(page, 'Carol Díaz').getByRole('radio', { name: 'Suggested text' }),
    ).toBeChecked()
  })
})

test.describe('accessibility', () => {
  for (const scheme of ['light', 'dark'] as const) {
    test(`suggestions have no serious axe violations (${scheme})`, async ({ page }) => {
      await page.emulateMedia({ colorScheme: scheme })
      await openProposal(page)
      await expect(card(page, 'Carol Díaz')).toBeVisible()
      expect(await seriousViolations(page)).toEqual([])
      await card(page, 'Carol Díaz').getByRole('radio', { name: 'Suggested text' }).click()
      expect(await seriousViolations(page)).toEqual([])
    })
  }
})

test.describe('on a phone', () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true })

  test('cards fit, the author keeps their name, and Accept works', async ({ page }) => {
    await openProposal(page)
    const agent = card(page, 'Research agent').first()
    await agent.scrollIntoViewIfNeeded()
    // Not cut off: the author line (truncated when too long) fits its box.
    const byline = agent.locator('header p').first()
    expect(await byline.evaluate((element) => element.scrollWidth <= element.clientWidth + 1)).toBe(
      true,
    )
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true)
    // The jump button says what the number is.
    await expect(page.getByRole('button', { name: /^4 suggestions/ })).toContainText('4 to review')
    await agent
      .getByRole('button', { name: 'Accept: Research agent’s suggestion for Summary' })
      .tap()
    await expect(toast(page, 'Research agent’s suggestion accepted')).toBeVisible()
  })
})
