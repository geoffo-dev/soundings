import type { Locator, Page } from '@playwright/test'

import { expect, seriousViolations, test, USERS } from './support'

/**
 * Phase 10 review fixes (the UX review's M1-M6 and minors), against the mock's fixtures
 * (src/mocks/phase10-fixtures.ts): CUST-3 assessing (Alice owns it; Priya assesses
 * Delivery and still owes Tessellate), TOOL-4 open with Kestrel flagged (no insurance
 * certificate), a price question in both.
 */

const toast = (page: Page, text: string | RegExp) =>
  page.locator('[data-sonner-toast]', { hasText: text })
const bidsRegion = (page: Page) => page.getByRole('region', { name: 'Bids', exact: true })

async function openBids(page: Page, key: string) {
  await page.goto(`/ideas/${key}?tab=bids`)
  await expect(page.getByRole('tab', { name: /^Bids/, selected: true })).toBeVisible()
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

const documentRow = (sheet: Locator, name: string) =>
  sheet.getByRole('list', { name: 'Documents' }).getByRole('listitem').filter({ hasText: name })

test.describe('entering a bid (M1)', () => {
  test('a bad email is said in plain words, and fixing it lets the bid through', async ({
    page,
  }) => {
    await openBids(page, 'TOOL-4')
    await page.getByRole('button', { name: 'Enter a bid' }).click()
    const form = page.getByRole('dialog', { name: 'Enter a bid' })
    await form.getByLabel('Bidder').fill('Northwind Data Ltd')
    await form.getByLabel('Contact email').fill('bids at northwind')
    await form.getByRole('button', { name: 'Enter the bid' }).click()
    await expect(form.getByText('An email address, like name@example.com.')).toBeVisible()
    await expect(form.getByText(/String should match/)).toHaveCount(0)
    await form.getByLabel('Contact email').fill('bids@northwind.example')
    await expect(form.getByText('An email address, like name@example.com.')).toHaveCount(0)
    await form.getByRole('button', { name: 'Enter the bid' }).click()
    await expect(toast(page, 'Bid from Northwind Data Ltd entered')).toBeVisible()
    await expect(form).toBeHidden()
  })
})

test.describe('uploading to a bid (M2, M3)', () => {
  test('a file named after a must-have answers it as it lands; another asks about pricing', async ({
    page,
  }) => {
    await openBids(page, 'TOOL-4')
    const sheet = await openBid(page, 'Kestrel Code Co')
    await expect(sheet.getByText('Upload as pricing documents')).toHaveCount(0)
    await sheet.locator('input[type=file]').setInputFiles([
      {
        name: 'Kestrel insurance 2026.pdf',
        mimeType: 'application/pdf',
        buffer: Buffer.from('%PDF-1.4\nInsurance certificate: public liability.\n'),
      },
      {
        name: 'Method statement.txt',
        mimeType: 'text/plain',
        buffer: Buffer.from('We build it in three sprints.\n'),
      },
    ])
    const insurance = documentRow(sheet, 'Kestrel insurance 2026.pdf')
    await expect(
      insurance.getByRole('combobox', { name: /Must-have that Kestrel insurance/ }),
    ).toHaveText('Insurance certificate')
    await expect(insurance).toContainText('Matched from its name')
    const insuranceMust = sheet
      .getByRole('list', { name: 'Must-haves' })
      .getByRole('listitem')
      .filter({ hasText: 'Insurance certificate' })
    await expect(insuranceMust).toContainText('Met')

    // Nothing says the method statement isn't pricing: it stays restricted until asked.
    const method = documentRow(sheet, 'Method statement.txt')
    await expect(method).toContainText('Pricing')
    await expect(method.getByRole('group', { name: /pricing document/ })).toBeVisible()
    await method.getByRole('button', { name: 'Not pricing' }).click()
    await expect(toast(page, /Method statement\.txt isn’t a pricing document/)).toBeVisible()
    await expect(method.getByRole('group', { name: /pricing document/ })).toHaveCount(0)
    await expect(
      method.getByRole('button', { name: 'More for Method statement.txt' }),
    ).toBeFocused()

    // Linking another file is one step on its row.
    const brochure = documentRow(sheet, 'Brochure.pdf')
    await brochure.getByRole('combobox', { name: 'Must-have that Brochure.pdf answers' }).click()
    await page.getByRole('option', { name: 'Signed form of tender' }).click()
    await expect(toast(page, 'Brochure.pdf answers Signed form of tender')).toBeVisible()
  })

  test('says which files answer no must-have while a required document is missing', async ({
    page,
  }) => {
    await openBids(page, 'TOOL-4')
    const sheet = await openBid(page, 'Kestrel Code Co')
    await expect(sheet.getByText(/files? do(es)?n’t answer a must-have/)).toBeVisible()
    await expect(sheet.getByText('First check the files:')).toBeVisible()
    await sheet.getByRole('button', { name: 'Show the files' }).click()
    await expect(
      sheet.getByRole('combobox', { name: 'Must-have that Brochure.pdf answers' }),
    ).toBeFocused()
  })

  test('cleans a file name before sending it and shows it isolated', async ({ page }) => {
    await openBids(page, 'TOOL-4')
    const sheet = await openBid(page, 'Brightline Software')
    await sheet.locator('input[type=file]').setInputFiles({
      name: `..\\..\\notes${String.fromCharCode(0x202e)}txt.exe.txt`,
      mimeType: 'text/plain',
      buffer: Buffer.from('Plain notes.\n'),
    })
    await expect(documentRow(sheet, 'notestxt.exe.txt')).toBeVisible()
  })
})

test.describe('a call manager reads the assessments (M4)', () => {
  test('a section score in the comparison opens that section’s assessments in the bid', async ({
    page,
  }) => {
    await openBids(page, 'CUST-3')
    await page
      .getByRole('region', { name: 'Comparison' })
      .getByRole('button', { name: /^Technical for Tessellate Logistics/ })
      .click()
    const sheet = page.getByRole('dialog', { name: 'Tessellate Logistics' })
    const technical = sheet.getByRole('button', { name: /^Technical/, expanded: true })
    await expect(technical).toBeFocused()
    const assessments = sheet.getByRole('list', { name: 'Technical: assessments' })
    await expect(assessments).toContainText('Bob Chen')
    await expect(assessments).toContainText('Carol Díaz')
    // Comment answers and the disagreement, said in words.
    await expect(sheet.getByText(/two assessors’ scores on a question differ by 2/)).toBeVisible()
    // The other sections open on demand.
    const delivery = sheet.getByRole('button', { name: /^Delivery/ })
    await expect(delivery).toHaveAttribute('aria-expanded', 'false')
    await delivery.click()
    await expect(sheet.getByRole('list', { name: 'Delivery: assessments' })).toBeVisible()
    expect(await seriousViolations(page)).toEqual([])
  })

  test('an AI quote’s file name opens the text at the quote', async ({ page }) => {
    await openBids(page, 'CUST-3')
    const sheet = await openBid(page, 'Tessellate Logistics')
    await sheet
      .getByRole('button', { name: /^Show the quote in / })
      .first()
      .click()
    const text = page
      .getByRole('dialog')
      .filter({ has: page.getByRole('region', { name: /^Text of / }) })
    await expect(text.locator('mark')).toBeVisible()
  })
})

test.describe('a call manager who still owes assessments (m2)', () => {
  test.use({ signedInAs: USERS.priya })

  test('gets “Assess” as the next step, with Award in the menu', async ({ page }) => {
    await openBids(page, 'CUST-3')
    await expect(page.getByRole('button', { name: 'Assess (1)' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Award…' })).toHaveCount(0)
    await page.getByRole('button', { name: 'More for this call' }).click()
    await expect(page.getByRole('menuitem', { name: 'Award…' })).toBeVisible()
    await page.keyboard.press('Escape')
    await page.getByRole('button', { name: 'Assess (1)' }).click()
    await expect(page.getByRole('dialog', { name: /Delivery · Tessellate/ })).toBeVisible()
  })
})

test.describe('the idea’s details (m6)', () => {
  test('show the call and lead to the Bids tab', async ({ page }) => {
    await page.goto('/ideas/CUST-3')
    const details = page.getByRole('complementary', { name: 'Idea details' })
    await details.getByRole('button', { name: /^Call for bids: .*Open the Bids tab/ }).click()
    await expect(page.getByRole('tab', { name: /^Bids/, selected: true })).toBeVisible()
  })
})
