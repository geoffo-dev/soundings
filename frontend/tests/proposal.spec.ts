import type { Page } from '@playwright/test'

import { expect, seriousViolations, test, USERS } from './support'

/**
 * The proposal editor (SPEC §5 screen 5, wireframe 05) on the idea page's
 * Proposal tab, against the mock API. CUST-3 (Proposal, owner Alice) has a
 * proposal with five sections written and margin threads; CUST-4
 * (Shortlisted, owner Alice) has none yet.
 */

const editor = (page: Page) => page.getByTestId('proposal-editor')
const section = (page: Page, name: string) => page.getByRole('region', { name, exact: true })
const status = (page: Page) => editor(page).getByRole('status').first()

/** Saves a section as "someone else" through the same in-page mock API. */
async function saveElsewhere(page: Page, key: string, body: string, base: number) {
  await page.evaluate(
    async ({ key, body, base }) => {
      const response = await fetch(`/api/v1/ideas/CUST-3/proposal/sections/${key}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': 'playwright' },
        body: JSON.stringify({ body_md: body, base_version: base }),
      })
      if (!response.ok) throw new Error(`save failed: ${String(response.status)}`)
    },
    { key, body, base },
  )
}

async function storedSection(page: Page, key: string): Promise<string> {
  return page.evaluate(async (key) => {
    const response = await fetch('/api/v1/ideas/CUST-3/proposal')
    const view = (await response.json()) as {
      proposal: { sections: { key: string; body_md: string }[] }
    }
    return view.proposal.sections.find((s) => s.key === key)?.body_md ?? ''
  }, key)
}

async function openProposal(page: Page, key = 'CUST-3') {
  await page.goto(`/ideas/${key}?tab=proposal`)
  await expect(page.getByRole('tab', { name: 'Proposal', selected: true })).toBeVisible()
}

test('the owner starts a proposal: the idea moves to Proposal and the editor opens', async ({
  page,
}) => {
  await openProposal(page, 'CUST-4')
  await expect(page.getByRole('heading', { name: 'Write the proposal' })).toBeVisible()
  await page.getByRole('button', { name: 'Start proposal' }).click()
  await expect(editor(page)).toBeVisible()
  await expect(page.getByRole('textbox', { name: 'Summary' })).toHaveValue(
    'Open a documented API so marketplace sellers can sync stock and orders.',
  )
  // The button is gone: writing starts in Summary (focus never drops to the page).
  await expect(page.getByRole('textbox', { name: 'Summary' })).toBeFocused()
  // The status moved with it.
  await expect
    .poll(() =>
      page.evaluate(async () => {
        const idea = (await (await fetch('/api/v1/ideas/CUST-4')).json()) as { status: string }
        return idea.status
      }),
    )
    .toBe('proposal')
  await expect(page.getByRole('navigation', { name: 'Outline' })).toContainText('1/8')
})

test('explains when there is no proposal yet', async ({ page }) => {
  await openProposal(page, 'CUST-5')
  await expect(
    page.getByRole('heading', { name: 'Available once the idea is shortlisted' }),
  ).toBeVisible()
  await openProposal(page, 'GREEN-4') // in Proposal, owned by Emma: Alice waits
  await expect(
    page.getByRole('heading', { name: 'The owner will write the proposal' }),
  ).toBeVisible()
  await expect(page.getByText('Emma Lindqvist can start it now.')).toBeVisible()
})

test('autosaves each section and shows where saving is', async ({ page }) => {
  await openProposal(page)
  const risks = page.getByRole('textbox', { name: 'Risks' })
  await risks.fill('Supplier delays at peak season')
  await expect(section(page, '7. Risks')).toContainText('5 words')
  await expect(status(page)).toHaveText(/Saved/, { timeout: 5000 })
  expect(await storedSection(page, 'risks')).toBe('Supplier delays at peak season')
  // Text is kept verbatim (leading spaces are a code block in Markdown).
  await risks.fill('    indented\n\n')
  await page.keyboard.press('ControlOrMeta+s')
  await expect.poll(() => storedSection(page, 'risks')).toBe('    indented\n\n')
  // The outline ticks the section.
  await expect(page.getByRole('link', { name: /^Risks ?, written/ })).toBeVisible()
})

test('Write and Preview: the toolbar and keyboard', async ({ page }) => {
  await openProposal(page)
  const field = page.getByRole('textbox', { name: 'Next steps / the ask' })
  await field.fill('Approve the pilot')
  await field.selectText()
  await section(page, '8. Next steps / the ask')
    .getByRole('button', { name: 'Bold', exact: true })
    .click()
  await expect(field).toHaveValue('**Approve the pilot**')
  await field.press('ControlOrMeta+Enter')
  const preview = page.getByRole('region', { name: 'Next steps / the ask (preview)' })
  await expect(preview).toBeFocused()
  await expect(preview.locator('strong')).toHaveText('Approve the pilot')
  await page.keyboard.press('ControlOrMeta+Enter')
  await expect(field).toBeFocused()
})

test('a conflicting save asks which version to keep: Keep this version', async ({ page }) => {
  await openProposal(page)
  await expect(page.getByRole('textbox', { name: 'Summary' })).toBeVisible()
  await saveElsewhere(page, 'summary', 'Their summary.', 3)
  const summary = page.getByRole('textbox', { name: 'Summary' })
  await summary.fill('My summary.')
  const prompt = page.getByRole('alert').filter({ hasText: 'changed this section' })
  await expect(prompt).toBeVisible({ timeout: 5000 })
  await expect(prompt).toContainText('Their summary.')
  await expect(prompt).toContainText('My summary.')
  await expect(status(page)).toContainText('A section changed while you were editing')
  await prompt.getByRole('button', { name: 'Keep this version' }).click()
  await expect(prompt).toBeHidden()
  await expect(summary).toBeFocused()
  await expect.poll(() => storedSection(page, 'summary')).toBe('My summary.')
})

test('a conflicting save: Use the saved version replaces the draft', async ({ page }) => {
  await openProposal(page)
  await expect(page.getByRole('textbox', { name: 'Problem' })).toBeVisible()
  await saveElsewhere(page, 'problem', 'Their problem.', 3)
  const problem = page.getByRole('textbox', { name: 'Problem' })
  await problem.fill('My problem.')
  const prompt = page.getByRole('alert').filter({ hasText: 'changed this section' })
  await prompt.getByRole('button', { name: 'Use the saved version' }).click()
  await expect(problem).toHaveValue('Their problem.')
  await expect(problem).toBeFocused()
  await expect(status(page)).toHaveText(/Saved/)
})

test('a failed save keeps the text and offers Retry', async ({ page }) => {
  await openProposal(page)
  await page.evaluate(() => localStorage.setItem('soundings-mock-fail', '/proposal/sections'))
  const benefits = page.getByRole('textbox', { name: 'Benefits / revenue' })
  await benefits.fill('Recurring revenue')
  const alert = section(page, '6. Benefits / revenue').getByRole('alert')
  await expect(alert).toContainText('Not saved', { timeout: 5000 })
  await expect(status(page)).toContainText('A section isn’t saved')
  await page.evaluate(() => localStorage.removeItem('soundings-mock-fail'))
  await alert.getByRole('button', { name: 'Retry' }).click()
  await expect(alert).toBeHidden()
  expect(await storedSection(page, 'benefits')).toBe('Recurring revenue')
  await expect(benefits).toHaveValue('Recurring revenue')
})

test('exports Markdown and PDF as downloads', async ({ page }) => {
  await openProposal(page)
  const exportButton = page.getByRole('button', { name: 'Export' })
  await exportButton.click()
  // A half-written proposal says so before it is exported.
  await expect(page.getByRole('menu')).toContainText(/\d of 8 sections are still empty\./)
  const markdown = page.waitForEvent('download')
  await page.getByRole('menuitem', { name: /Markdown/ }).click()
  expect((await markdown).suggestedFilename()).toBe('CUST-3-proposal.md')
  await exportButton.click()
  const pdf = page.waitForEvent('download')
  await page.getByRole('menuitem', { name: /PDF/ }).click()
  expect((await pdf).suggestedFilename()).toBe('CUST-3-proposal.pdf')
})

test('an export that fails says why and offers Retry', async ({ page }) => {
  await openProposal(page)
  await page.evaluate(() => localStorage.setItem('soundings-mock-fail', '/proposal/pdf'))
  await page.getByRole('button', { name: 'Export' }).click()
  await page.getByRole('menuitem', { name: /PDF/ }).click()
  const toast = page.getByRole('listitem').filter({ hasText: 'Couldn’t export the PDF' })
  await expect(toast).toBeVisible()
  await page.evaluate(() => localStorage.removeItem('soundings-mock-fail'))
  const download = page.waitForEvent('download')
  await toast.getByRole('button', { name: 'Retry' }).click()
  expect((await download).suggestedFilename()).toBe('CUST-3-proposal.pdf')
})

test('the outline moves focus to a section; j and k step through them', async ({ page }) => {
  await openProposal(page)
  const outline = page.getByRole('navigation', { name: 'Outline' })
  await expect(
    outline.getByRole('link', { name: /^Summary ?, written, 1 open thread/ }),
  ).toBeVisible()
  await outline.getByRole('link', { name: /^Cost & effort/ }).click()
  await expect(page.getByRole('textbox', { name: 'Cost & effort' })).toBeFocused()
  await expect(outline.getByRole('link', { name: /^Cost & effort/ })).toHaveAttribute(
    'aria-current',
    'location',
  )
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur())
  await page.keyboard.press('j')
  await expect(page.getByRole('textbox', { name: 'Benefits / revenue' })).toBeFocused()
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur())
  await page.keyboard.press('k')
  await expect(page.getByRole('textbox', { name: 'Cost & effort' })).toBeFocused()
})

test.describe('as a member (Bob): margin comments', () => {
  test.use({ signedInAs: USERS.bob })

  test('comments on a section, replies, resolves and reopens', async ({ page }) => {
    await openProposal(page)
    // Members read the proposal; only the owner and admins edit it.
    await expect(page.getByRole('textbox', { name: 'Problem' })).toHaveCount(0)
    const margin = page.getByRole('complementary', { name: 'Comments on Risks' })
    await margin.getByRole('button', { name: 'Comment on Risks' }).click()
    const box = margin.getByRole('textbox', { name: 'Comment on Risks' })
    await expect(box).toBeFocused()
    await box.fill('What about **supplier** risk?')
    await box.press('ControlOrMeta+Enter')
    const thread = margin.getByRole('article', { name: 'Thread by Bob Chen on Risks' })
    await expect(thread).toContainText('What about supplier risk?')
    await expect(thread.locator('strong')).toHaveText('supplier')
    // Focus follows each action instead of falling to the page (WCAG 2.4.3).
    await expect(thread).toBeFocused()

    await thread.getByRole('button', { name: 'Reply' }).click()
    const reply = thread.getByRole('textbox', { name: 'Reply to Bob Chen’s thread' })
    await reply.press('Escape')
    await expect(thread.getByRole('button', { name: 'Reply' })).toBeFocused()
    await thread.getByRole('button', { name: 'Reply' }).click()
    await reply.fill('And currency risk.')
    await reply.press('ControlOrMeta+Enter')
    await expect(thread).toContainText('And currency risk.')
    await expect(thread).toBeFocused()

    await thread.getByRole('button', { name: 'Resolve' }).click()
    const collapsed = margin.getByRole('button', { name: /Resolved · Bob Chen/ })
    await expect(collapsed).toHaveAttribute('aria-expanded', 'false')
    // The excerpt is plain text, not Markdown.
    await expect(collapsed).toContainText('What about supplier risk?')
    await expect(collapsed).toBeFocused()
    await collapsed.click()
    await margin
      .getByRole('article', { name: 'Resolved thread by Bob Chen on Risks' })
      .getByRole('button', { name: 'Reopen' })
      .click()
    const reopened = margin.getByRole('article', { name: 'Thread by Bob Chen on Risks' })
    await expect(reopened).toBeVisible()
    await expect(reopened).toBeFocused()

    // Cancelling a new comment goes back to "Comment".
    await margin.getByRole('button', { name: 'Comment on Risks' }).click()
    await margin.getByRole('textbox', { name: 'Comment on Risks' }).press('Escape')
    await expect(margin.getByRole('button', { name: 'Comment on Risks' })).toBeFocused()
  })

  test('deletes their own comment with Undo, but not someone else’s', async ({ page }) => {
    await openProposal(page)
    const margin = page.getByRole('complementary', { name: 'Comments on Problem' })
    await expect(margin.getByText('Source for the 8%?')).toBeVisible()
    const summary = page.getByRole('complementary', { name: 'Comments on Summary' })
    await expect(summary.getByRole('button', { name: /Delete .* comment/ })).toHaveCount(0)
    await margin.getByRole('button', { name: 'Delete Bob Chen’s comment' }).click()
    await expect(margin.getByText('Source for the 8%?')).toHaveCount(0)
    await page.getByRole('button', { name: 'Undo' }).click()
    await expect(margin.getByText('Source for the 8%?')).toBeVisible()
  })

  test('"c" comments on the section in view', async ({ page }) => {
    await openProposal(page)
    await page
      .getByRole('navigation', { name: 'Outline' })
      .getByRole('link', { name: /^Solution/ })
      .click()
    await page.keyboard.press('c')
    await expect(
      page
        .getByRole('complementary', { name: 'Comments on Solution' })
        .getByRole('textbox', { name: 'Comment on Solution' }),
    ).toBeFocused()
  })
})

test.describe('as a viewer (Emma)', () => {
  test.use({ signedInAs: USERS.emma })

  test('reads the proposal and exports it, nothing else', async ({ page }) => {
    await openProposal(page)
    await expect(section(page, '1. Summary')).toContainText('coffee and tea')
    await expect(page.getByRole('textbox')).toHaveCount(0)
    await expect(page.getByRole('button', { name: /^Comment/ })).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Reply' })).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Export' })).toBeVisible()
    await expect(status(page)).toContainText('Edited')
  })
})

test.describe('on a phone', () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true })

  test('jumps between sections and comments in a sheet', async ({ page }) => {
    await openProposal(page)
    // Written sections open in Preview on phones; the outline is a jump list.
    await expect(page.getByRole('region', { name: 'Summary (preview)' })).toBeVisible()
    await page.getByRole('combobox', { name: 'Jump to section' }).click()
    await page.getByRole('option', { name: /Market & users/ }).click()
    await expect(page.getByRole('combobox', { name: 'Jump to section' })).toContainText(
      '4. Market & users',
    )
    await page.getByRole('button', { name: /Comments on Market & users: 1 open of 1/ }).click()
    const sheet = page.getByRole('dialog', { name: 'Comments on Market & users' })
    await expect(sheet).toContainText('Tea uptake looks optimistic')
    await sheet.getByRole('textbox', { name: 'Comment on Market & users' }).fill('Agreed.')
    await sheet.getByRole('button', { name: 'Comment', exact: true }).click()
    await expect(sheet).toContainText('Agreed.')
    // No horizontal scrolling at 390 px.
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    )
    expect(overflow).toBeLessThanOrEqual(0)
    expect(await seriousViolations(page)).toEqual([])
  })
})

test.describe('accessibility', () => {
  for (const scheme of ['light', 'dark'] as const) {
    test(`the editor has no serious axe violations (${scheme})`, async ({ page }) => {
      await page.emulateMedia({ colorScheme: scheme })
      await openProposal(page)
      await expect(page.getByRole('textbox', { name: 'Summary' })).toBeVisible()
      expect(await seriousViolations(page)).toEqual([])
    })
  }

  test('the empty state and the conflict prompt have no serious violations', async ({ page }) => {
    await openProposal(page, 'CUST-4')
    await expect(page.getByRole('button', { name: 'Start proposal' })).toBeVisible()
    expect(await seriousViolations(page)).toEqual([])
    await openProposal(page)
    await expect(page.getByRole('textbox', { name: 'Summary' })).toBeVisible()
    await saveElsewhere(page, 'summary', 'Theirs', 3)
    await page.getByRole('textbox', { name: 'Summary' }).fill('Mine')
    await expect(page.getByRole('button', { name: 'Keep this version' })).toBeVisible({
      timeout: 5000,
    })
    expect(await seriousViolations(page)).toEqual([])
  })
})
