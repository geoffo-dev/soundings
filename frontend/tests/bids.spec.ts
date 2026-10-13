import type { Locator, Page } from '@playwright/test'

import { bestPracticeViolations, expect, seriousViolations, test, USERS } from './support'

/**
 * Phase 10, calls for bids (contract-phase10). The mock's fixtures
 * (src/mocks/phase10-fixtures.ts): CUST-3's call is being assessed (Alice owns the idea;
 * Bob and Carol assess Technical, Dave Commercial with the price, Farid and Priya
 * Delivery; Bob still owes Northwind, Priya Tessellate); Quillfield is rejected. TOOL-4's
 * call is open with Kestrel flagged (no insurance certificate). TOOL-11 has a draft call,
 * CUST-12 a cancelled one; GREEN-4 (Emma's, in Proposal) none yet.
 */

const DAVE = '10000000-0000-4000-8000-000000000005'
const HANNAH = '10000000-0000-4000-8000-000000000009'
const EMMA = USERS.emma

const toast = (page: Page, text: string | RegExp) =>
  page.locator('[data-sonner-toast]', { hasText: text })
const bidsRegion = (page: Page) => page.getByRole('region', { name: 'Bids', exact: true })
const comparison = (page: Page) => page.getByRole('region', { name: 'Comparison' })

async function openBids(page: Page, key: string) {
  await page.goto(`/ideas/${key}?tab=bids`)
  await expect(page.getByRole('tab', { name: /^Bids/, selected: true })).toBeVisible()
  // The tab's code is loaded lazily; its heading is the call's title or the empty state.
  await expect(page.getByRole('tabpanel').getByRole('heading', { level: 2 }).first()).toBeVisible({
    timeout: 15_000,
  })
}

async function openBid(page: Page, bidder: string): Promise<Locator> {
  await bidsRegion(page).getByRole('button', { name: bidder, exact: true }).click()
  const sheet = page.getByRole('dialog', { name: bidder })
  await expect(sheet.getByRole('heading', { name: 'Documents' })).toBeVisible()
  return sheet
}

test.describe('a call manager (Alice owns CUST-3)', () => {
  test('compares the bids with ranks and totals, rejected bids apart with the reason', async ({
    page,
  }) => {
    await openBids(page, 'CUST-3')
    await expect(
      page.getByRole('heading', { name: 'Fulfilment partner for subscription boxes' }),
    ).toBeVisible()
    const table = comparison(page).getByRole('table', { name: 'Bids compared' })
    await expect(table.getByRole('row')).toHaveCount(3)
    const northwind = table.getByRole('row', { name: /Northwind/ })
    await expect(northwind).toContainText('87.3')
    await expect(northwind.getByRole('cell').first()).toHaveText(/1$/)
    const tessellate = table.getByRole('row', { name: /Tessellate/ })
    await expect(tessellate).toContainText('71.2')
    await expect(tessellate.getByRole('img', { name: 'Assessors disagree' })).toBeVisible()
    await expect(comparison(page).getByText('No insurance certificate provided.')).toBeVisible()
    // Prices for a call manager; the template is locked once someone has submitted.
    await expect(bidsRegion(page).getByRole('row', { name: /Northwind/ })).toContainText(
      '£120,000.00',
    )
    await expect(page.getByText('The evaluation template is locked')).toBeVisible()
  })

  test('counts the AI’s assessment in the totals only once included', async ({ page }) => {
    await openBids(page, 'CUST-3')
    const row = comparison(page).getByRole('row', { name: /Tessellate/ })
    const include = row.getByRole('switch', {
      name: /Count Bid assessor’s assessment of Tessellate/,
    })
    await expect(include).not.toBeChecked()
    await include.click()
    await expect(toast(page, 'The AI’s scores for Tessellate Logistics now count')).toBeVisible()
    await expect(include).toBeChecked()
  })

  test('awards the call, warning about outstanding assessments', async ({ page }) => {
    await openBids(page, 'CUST-3')
    await page.getByRole('button', { name: 'Award…' }).click()
    const dialog = page.getByRole('dialog', { name: 'Award the call' })
    await expect(dialog.getByText('2 assessments are outstanding')).toBeVisible()
    await expect(dialog.getByRole('radio')).toHaveCount(2)
    await dialog.getByRole('radio', { name: 'Northwind Fulfilment Ltd' }).click()
    await dialog.getByLabel('Reason').fill('Strongest technically, within budget.')
    await dialog.getByRole('button', { name: 'Award to Northwind Fulfilment Ltd' }).click()
    await expect(toast(page, 'Awarded to Northwind Fulfilment Ltd')).toBeVisible()
    await expect(page.getByText('Awarded', { exact: true }).first()).toBeVisible()
    await expect(page.getByRole('button', { name: 'Award…' })).toHaveCount(0)
  })

  test('opens a bid: details, must-haves with the AI’s evidence, documents and the AI panel', async ({
    page,
  }) => {
    await openBids(page, 'CUST-3')
    const sheet = await openBid(page, 'Tessellate Logistics')
    await expect(sheet.getByText('£96,000.00')).toBeVisible()
    await expect(sheet.getByText('Sam Okoro')).toBeVisible()
    const musts = sheet.getByRole('list', { name: 'Must-haves' })
    await expect(
      musts.getByRole('listitem').filter({ hasText: 'Signed form of tender' }),
    ).toContainText('Found in the document')
    // The AI's quote that isn't in the text says so; its scores stay out until counted.
    await expect(sheet.getByText('Not found in the document')).toBeVisible()
    await expect(sheet.getByText('One quote wasn’t found in the documents.')).toBeVisible()
    await expect(sheet.getByRole('switch', { name: 'Count in the totals' })).not.toBeChecked()
    // The extracted text opens as text, never the file.
    await sheet.getByRole('button', { name: 'Read the text of Proposal.pdf' }).first().click()
    const text = page.getByRole('dialog', { name: 'Proposal.pdf' })
    await expect(text.getByRole('region', { name: /Text of Proposal.pdf/ })).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(text).toBeHidden()
  })
})

test.describe('must-haves, rejecting and documents (TOOL-4, open)', () => {
  test('suggests rejecting a flagged bid, rejects it with a reason and reinstates it', async ({
    page,
  }) => {
    await openBids(page, 'TOOL-4')
    await expect(bidsRegion(page).getByRole('row', { name: /Kestrel/ })).toContainText('1 missing')
    const sheet = await openBid(page, 'Kestrel Code Co')
    await expect(sheet.getByText('This bid doesn’t meet every must-have')).toBeVisible()
    await sheet.getByRole('button', { name: 'Reject…' }).click()
    const dialog = page.getByRole('dialog', { name: 'Reject Kestrel Code Co’s bid?' })
    await expect(dialog.getByLabel('Reason')).toHaveValue(/Missing: Insurance certificate\./)
    await dialog.getByRole('button', { name: 'Reject the bid' }).click()
    await expect(toast(page, 'Kestrel Code Co’s bid rejected')).toBeVisible()
    await expect(sheet.getByText('Rejected', { exact: true }).first()).toBeVisible()
    await sheet.getByRole('button', { name: 'Reinstate' }).click()
    await expect(toast(page, 'Kestrel Code Co’s bid reinstated')).toBeVisible()
    await expect(sheet.getByRole('button', { name: 'Reinstate' })).toHaveCount(0)
  })

  test('confirms a must-have and marks one not met with a note', async ({ page }) => {
    await openBids(page, 'TOOL-4')
    const sheet = await openBid(page, 'Kestrel Code Co')
    const terms = sheet
      .getByRole('list', { name: 'Must-haves' })
      .getByRole('listitem')
      .filter({ hasText: 'Accepts our standard terms' })
    await terms.getByRole('button', { name: 'Not met…' }).click()
    const dialog = page.getByRole('dialog', { name: /Not met: Accepts our standard terms/ })
    await dialog.getByLabel('Note').fill('They apply their own terms.')
    await dialog.getByRole('button', { name: 'Not met', exact: true }).click()
    await expect(toast(page, 'Accepts our standard terms: not met')).toBeVisible()
    await expect(terms).toContainText('They apply their own terms.')
    await terms.getByRole('button', { name: 'Clear' }).click()
    await expect(toast(page, 'Accepts our standard terms: cleared')).toBeVisible()
    await terms.getByRole('button', { name: 'Met', exact: true }).click()
    await expect(toast(page, 'Accepts our standard terms: met')).toBeVisible()
  })

  test('uploads documents with progress, reads their text, and says why a file is refused', async ({
    page,
  }) => {
    await openBids(page, 'TOOL-4')
    const sheet = await openBid(page, 'Brightline Software')
    const input = sheet.locator('input[type=file]')
    await input.setInputFiles([
      {
        name: 'Method statement.pdf',
        mimeType: 'application/pdf',
        buffer: Buffer.from('%PDF-1.4\nOur method: weekly releases with a named lead.\n'),
      },
      {
        name: 'setup.exe',
        mimeType: 'application/octet-stream',
        buffer: Buffer.from([0x4d, 0x5a, 0x90, 0x00, 0x03, 0x00, 0x00, 0x00, 0x00, 0x00]),
      },
    ])
    const documents = sheet.getByRole('list', { name: 'Documents' })
    await expect(documents.getByText('Method statement.pdf')).toBeVisible()
    await expect(
      sheet.getByRole('list', { name: 'Uploads' }).getByText('That file type can’t be uploaded'),
    ).toBeVisible()
    // The worker reads the text a moment later; the bid is fetched again meanwhile.
    await expect(
      documents.getByRole('listitem').filter({ hasText: 'Method statement.pdf' }),
    ).toContainText('characters of text', { timeout: 10_000 })
    await sheet.getByRole('button', { name: 'Dismiss setup.exe' }).click()
    await expect(sheet.getByRole('list', { name: 'Uploads' })).toHaveCount(0)
    // An empty file is refused before it is sent.
    await input.setInputFiles({
      name: 'empty.txt',
      mimeType: 'text/plain',
      buffer: Buffer.alloc(0),
    })
    await expect(
      sheet.getByRole('list', { name: 'Uploads' }).getByText('empty.txt is empty.'),
    ).toBeVisible()
  })

  test('warns before downloading a file with active content', async ({ page }) => {
    await openBids(page, 'TOOL-4')
    const sheet = await openBid(page, 'Kestrel Code Co')
    await expect(sheet.getByText('Active content')).toBeVisible()
    await sheet.getByRole('button', { name: 'Download Brochure.pdf' }).click()
    const dialog = page.getByRole('dialog', {
      name: 'This file has content that can run when it’s opened',
    })
    await expect(dialog).toBeVisible()
    const download = page.waitForEvent('download')
    await dialog.getByRole('button', { name: 'Download anyway' }).click()
    expect((await download).suggestedFilename()).toMatch(/Brochure/)
  })
})

test.describe('an assessor (Bob, Technical on CUST-3)', () => {
  test.use({ signedInAs: USERS.bob })

  test('is blind until submitting: no comparison, no prices, no rejected bid', async ({ page }) => {
    await openBids(page, 'CUST-3')
    await expect(page.getByRole('heading', { name: 'Your assessments' })).toBeVisible()
    await expect(comparison(page)).toHaveCount(0)
    await expect(bidsRegion(page).getByRole('row')).toHaveCount(3)
    await expect(bidsRegion(page).getByText('Quillfield')).toHaveCount(0)
    await expect(bidsRegion(page).getByRole('columnheader', { name: 'Price' })).toHaveCount(0)
    await expect(
      page.getByText('Prices and pricing documents are only for the call’s managers'),
    ).toBeVisible()
  })

  test('scores a section, needs every score to submit, then sees the others’ scores', async ({
    page,
  }) => {
    await openBids(page, 'CUST-3')
    await page
      .getByRole('button', { name: 'Continue: Northwind Fulfilment Ltd, Technical' })
      .click()
    const sheet = page.getByRole('dialog', { name: /Technical · Northwind/ })
    await expect(
      sheet.getByText('The other assessors’ scores for this section stay hidden'),
    ).toBeVisible()
    await expect(sheet.getByText('Everyone’s scores')).toHaveCount(0)
    // The bid's documents and their text beside the questions on a wide screen.
    await expect(sheet.getByRole('complementary', { name: 'The bid’s documents' })).toBeVisible()
    await sheet.getByRole('button', { name: 'Submit' }).click()
    await expect(sheet.getByText('Pick a score')).toBeVisible()
    // Keyboard: the radios of the second question.
    const second = sheet.getByRole('radiogroup', {
      name: 'How well will our data be kept secure and compliant?',
    })
    await second.getByRole('radio', { name: '3' }).click()
    await page.keyboard.press('4')
    await expect(second.getByRole('radio', { name: '4' })).toBeChecked()
    await sheet.getByRole('button', { name: 'Submit' }).click()
    await expect(toast(page, 'Technical submitted for Northwind Fulfilment Ltd')).toBeVisible()
    await expect(sheet.getByRole('heading', { name: 'Everyone’s scores' })).toBeVisible()
    await expect(sheet.getByRole('list', { name: 'Assessments' })).toContainText('Carol Díaz')
  })

  test('asks before closing with unsaved changes', async ({ page }) => {
    await openBids(page, 'CUST-3')
    await page
      .getByRole('button', { name: 'Continue: Northwind Fulfilment Ltd, Technical' })
      .click()
    const sheet = page.getByRole('dialog', { name: /Technical · Northwind/ })
    await sheet
      .getByLabel(
        'Comment on How well does the proposed solution meet our requirements? (optional)',
      )
      .fill('Strong.')
    await page.keyboard.press('Escape')
    const ask = page.getByRole('dialog', { name: 'Leave without saving?' })
    await expect(ask).toBeVisible()
    await ask.getByRole('button', { name: 'Keep editing' }).click()
    await sheet.getByRole('button', { name: 'Save draft' }).click()
    await expect(toast(page, 'Draft saved')).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(sheet).toBeHidden()
  })

  test('finds the call in My work and the sidebar', async ({ page }) => {
    await page.goto('/')
    const section = page.getByRole('region', { name: /Bids to assess/ })
    await expect(
      section.getByRole('link', { name: 'Fulfilment partner for subscription boxes', exact: true }),
    ).toBeVisible()
    await expect(section).toContainText('1 of 2 submitted')
    await expect(page.getByRole('link', { name: /^Bids, 1 to assess/ })).toBeVisible()
    await section.getByRole('link', { name: /^Assess 1 bid section/ }).click()
    await expect(page.getByRole('heading', { name: 'Your assessments' })).toBeVisible({
      timeout: 15_000,
    })
  })
})

test.describe('a call manager who assesses too (Priya, Delivery)', () => {
  test.use({ signedInAs: USERS.priya })

  test('sees no ranking while she owes an assessment, and can’t step out of her section', async ({
    page,
  }) => {
    await openBids(page, 'CUST-3')
    await expect(
      comparison(page).getByText('The ranking shows once you have submitted your assessments'),
    ).toBeVisible()
    const tessellate = comparison(page).getByRole('row', { name: /Tessellate/ })
    await expect(
      tessellate.getByRole('img', { name: 'Hidden until you submit' }).first(),
    ).toBeVisible()
    await expect(
      comparison(page)
        .getByRole('row', { name: /Northwind/ })
        .getByRole('cell')
        .first(),
    ).toHaveText(/—$/)
    // Stepping out of a section she still owes is refused, in words.
    await page.getByRole('button', { name: 'More for this call' }).click()
    await page.getByRole('menuitem', { name: 'Assessors and due date…' }).click()
    const dialog = page.getByRole('dialog', { name: 'Assessors' })
    await dialog.getByRole('button', { name: 'Remove Priya Natarajan from Delivery' }).click()
    await dialog.getByRole('button', { name: 'Save' }).click()
    await expect(
      dialog.getByText(/You still owe assessments of a section you took yourself off/),
    ).toBeVisible()
  })
})

test.describe('the price section’s assessor (Dave)', () => {
  test.use({ signedInAs: DAVE })

  test('sees the prices', async ({ page }) => {
    await openBids(page, 'CUST-3')
    await expect(bidsRegion(page).getByRole('row', { name: /Northwind/ })).toContainText(
      '£120,000.00',
    )
  })
})

test.describe('a member who isn’t an assessor (Hannah)', () => {
  test.use({ signedInAs: HANNAH })

  test('sees only that a call exists', async ({ page }) => {
    await openBids(page, 'CUST-3')
    await expect(
      page.getByText('Only the idea’s owner, admins and the call’s assessors see the bids.'),
    ).toBeVisible()
    await expect(bidsRegion(page)).toHaveCount(0)
  })
})

test.describe('starting a call (Emma owns GREEN-4)', () => {
  test.use({ signedInAs: EMMA })

  test('the owner starts a call once the proposal exists (Emma, GREEN-4)', async ({ page }) => {
    // No proposal yet: no Bids tab at all.
    await page.goto('/ideas/GREEN-4')
    await expect(page.getByRole('tab', { name: /^Overview/ })).toBeVisible()
    await expect(page.getByRole('tab', { name: /^Bids/ })).toHaveCount(0)
    await page.getByRole('tab', { name: /^Proposal/ }).click()
    await page.getByRole('button', { name: 'Start proposal' }).first().click()
    await expect(page.getByRole('tab', { name: /^Bids/ })).toBeVisible()
    await page.getByRole('tab', { name: /^Bids/ }).click()
    await page.getByRole('button', { name: 'Start a call for bids' }).click()
    const dialog = page.getByRole('dialog', { name: 'Start a call for bids' })
    await dialog.getByLabel('Title').fill('Solar canopy installer')
    await dialog.getByRole('button', { name: 'Start the call' }).click()
    await expect(toast(page, 'Call for bids started')).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Solar canopy installer' })).toBeVisible()
    await expect(page.getByText('Draft', { exact: true }).first()).toBeVisible()
  })
})

test.describe('opening a call', () => {
  test('opening a draft asks for a deadline first (TOOL-11)', async ({ page }) => {
    await openBids(page, 'TOOL-11')
    await page.getByRole('button', { name: 'Open the call' }).click()
    const details = page.getByRole('dialog', { name: 'Call details' })
    await expect(details.getByText('Set a deadline for bids to open the call.')).toBeVisible()
    const date = new Date(Date.now() + 10 * 86_400_000).toISOString().slice(0, 10)
    await details.getByLabel('Deadline for bids').fill(date)
    await details.getByRole('button', { name: 'Save' }).click()
    await expect(toast(page, 'Call saved')).toBeVisible()
    await page.getByRole('button', { name: 'Open the call' }).click()
    await page.getByRole('alertdialog').getByRole('button', { name: 'Open the call' }).click()
    await expect(toast(page, 'The call is open to bids')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Enter a bid' })).toBeVisible()
  })
})

test.describe('the project’s template (Internal Tools settings)', () => {
  test('checks that the weights add up to 100 before saving', async ({ page }) => {
    await page.goto('/p/internal-tools/settings?tab=bids')
    await expect(page.getByRole('heading', { name: 'Bid evaluation template' })).toBeVisible({
      timeout: 15_000,
    })
    await expect(page.getByText('Section weights add up to 100%')).toBeVisible()
    const weight = page.getByLabel('Weight of Technical (%)')
    await weight.fill('30')
    await expect(page.getByText(/add up to 90%/)).toBeVisible()
    await weight.fill('40')
    await expect(page.getByText('Section weights add up to 100%')).toBeVisible()
  })
})

test.describe('accessibility', () => {
  test('the Bids tab, a bid and an assessment have no serious axe violations (light and dark)', async ({
    page,
  }) => {
    await openBids(page, 'CUST-3')
    await expect(comparison(page).getByRole('table')).toBeVisible()
    expect(await seriousViolations(page)).toEqual([])
    expect(await bestPracticeViolations(page)).toEqual([])
    await page.emulateMedia({ colorScheme: 'dark' })
    expect(await seriousViolations(page)).toEqual([])
    await page.emulateMedia({ colorScheme: 'light' })
    await openBid(page, 'Tessellate Logistics')
    expect(await seriousViolations(page)).toEqual([])
  })

  test('fits a phone without sideways scrolling', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    await openBids(page, 'CUST-3')
    await expect(comparison(page).getByRole('table')).toBeVisible()
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    )
    expect(overflow).toBeLessThanOrEqual(0)
    expect(await seriousViolations(page)).toEqual([])
  })
})

test.describe('an assessor’s assessment, axe', () => {
  test.use({ signedInAs: USERS.bob })

  test('has no serious violations, wide and on a phone', async ({ page }) => {
    await openBids(page, 'CUST-3')
    await page
      .getByRole('button', { name: 'Continue: Northwind Fulfilment Ltd, Technical' })
      .click()
    const sheet = page.getByRole('dialog', { name: /Technical · Northwind/ })
    await expect(sheet.getByRole('radiogroup').first()).toBeVisible()
    expect(await seriousViolations(page)).toEqual([])
    await page.setViewportSize({ width: 390, height: 844 })
    await expect(sheet.getByRole('heading', { name: 'The bid’s documents' })).toBeVisible()
    expect(await seriousViolations(page)).toEqual([])
  })
})
