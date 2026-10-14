import { readFileSync } from 'node:fs'

import type { Locator, Page } from '@playwright/test'

import { daysFromNow } from './support/api'
import {
  assess,
  assessingCall,
  bid,
  bidCall,
  bidTeam,
  bidTemplate,
  comparison,
  DEMO,
  EXECUTABLE,
  MACRO_DOCM,
  MUST_HAVES,
  openCall,
  seedDocument,
  startCall,
  waitExtracted,
} from './support/bids'
import {
  emailCount,
  emailTo,
  expectNoScoreData,
  Mailpit,
  newPeople,
  disposePeople,
  visibleText,
} from './support/email'
import { expect, signIn, test, toast } from './support/fixtures'
import { readPdf } from './support/pdf'
import { answerRequired, assignResearcher, researchTeam } from './support/research'

/**
 * Phase 10, calls for bids (contract-phase10, test plan docs/test-plans/phase-10.md,
 * BD-*), on the real stack. Specs that change a call use a private project of their own
 * (`bidTeam` / `assessingCall` in tests/support/bids.ts: alice its admin and the idea's
 * owner); BD-06, BD-08 and BD-10 read the seeded story without changing it: TOOLS-3's
 * "Data platform build" is being assessed (kenji owns the idea, dave admins Internal
 * Tools; Technical carol + mateo, Commercial with the price priya, Delivery sven + alice;
 * alice still owes both Delivery assessments; Quillfield rejected for its missing
 * insurance certificate; zanele is a viewer).
 */

/** The "Asked to assess bids" email's fixed line about blind assessment ("section" for one). */
const BLIND_LINE =
  /Score your sections? for every bid on the idea's Bids tab\. Your assessment is blind: nobody's scores for a bid and section are shown to you until you submit yours\./g

const bidsTab = (page: Page) => page.getByRole('tab', { name: /^Bids/ })
const bidsRegion = (page: Page) => page.getByRole('region', { name: 'Bids', exact: true })
const comparisonRegion = (page: Page) => page.getByRole('region', { name: 'Comparison' })
const queue = (page: Page) => page.getByRole('region', { name: 'Your assessments' })

async function openBids(page: Page, key: string) {
  await page.goto(`/ideas/${key}?tab=bids`)
  await expect(bidsTab(page)).toHaveAttribute('aria-selected', 'true')
  // The tab's code loads lazily; its first h2 is the call's title or the empty state.
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

/** Drops files on the bid's drop zone as a browser would (a DataTransfer with Files). */
async function dropFiles(page: Page, zone: Locator, files: { name: string; bytes: Buffer }[]) {
  const dataTransfer = await page.evaluateHandle(
    (items) => {
      const transfer = new DataTransfer()
      for (const item of items) {
        const bytes = Uint8Array.from(atob(item.b64), (c) => c.charCodeAt(0))
        transfer.items.add(new File([bytes], item.name))
      }
      return transfer
    },
    files.map((file) => ({ name: file.name, b64: file.bytes.toString('base64') })),
  )
  await zone.dispatchEvent('dragenter', { dataTransfer })
  await zone.dispatchEvent('dragover', { dataTransfer })
  await zone.dispatchEvent('drop', { dataTransfer })
}

/** The bid's drop zone: the box around "Drop files here, or Choose files". */
const dropZone = (sheet: Locator) => sheet.getByText(/^Drop files here, or/).locator('..')

const documentRow = (sheet: Locator, filename: string) =>
  sheet.getByRole('list', { name: 'Documents' }).getByRole('listitem').filter({ hasText: filename })

const mustHaveRow = (sheet: Locator, text: string) =>
  sheet.getByRole('list', { name: 'Must-haves' }).getByRole('listitem').filter({ hasText: text })

// One upload at a time per person per API process (review L4: a second one is 503
// upload_busy): most of these specs upload as alice, so they run in order, not side by side.
test.describe.configure({ mode: 'default' })

// --- BD-01 ---------------------------------------------------------------------------------
test('BD-01 the owner starts a call from the project’s template, sets a deadline and opens it', async ({
  page,
  api,
}) => {
  const alice = await api('alice')
  const { idea } = await bidTeam(alice, 'Bid setup', { carol: 'member' })
  await signIn(page, 'alice')
  await openBids(page, idea.key)
  await page.getByRole('button', { name: 'Start a call for bids' }).click()
  const start = page.getByRole('dialog', { name: 'Start a call for bids' })
  await start.getByLabel('Title').fill('Bike shed supplier')
  await start.getByLabel('What is being bought').fill('Twenty covered bike stands, fitted.')
  await start.getByRole('button', { name: 'Start the call' }).click()
  await expect(toast(page, 'Call for bids started')).toBeVisible()
  await expect(page.getByRole('heading', { level: 2, name: 'Bike shed supplier' })).toBeVisible()
  await expect(page.getByText('Draft', { exact: true }).first()).toBeVisible()
  // The call copied the project's default template: three sections and four must-haves.
  const evaluation = page.getByRole('region', { name: 'Evaluation' })
  for (const title of ['Technical', 'Commercial', 'Delivery']) {
    await expect(evaluation.getByRole('heading', { level: 3, name: title })).toBeVisible()
  }
  const view = await bidCall(alice, idea.key)
  expect(view.call?.template.must_haves.map((m) => m.text)).toEqual(Object.values(MUST_HAVES))
  expect(view.call?.template.sections.map((s) => [s.title, s.weight])).toEqual([
    ['Technical', 40],
    ['Commercial', 40],
    ['Delivery', 20],
  ])
  // Opening without a deadline asks for one first.
  await page.getByRole('button', { name: 'Open the call' }).click()
  const details = page.getByRole('dialog', { name: 'Call details' })
  await expect(details.getByText('Set a deadline for bids to open the call.')).toBeVisible()
  const date = daysFromNow(10).slice(0, 10)
  await details.getByLabel('Deadline for bids').fill(date)
  // Saving the deadline opens the call in the same step (UX review m4).
  await details.getByRole('button', { name: 'Save and open' }).click()
  await expect(toast(page, 'The call is open to bids')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Enter a bid' })).toBeVisible()
  expect((await bidCall(alice, idea.key)).call?.status).toBe('open')
})

// --- BD-02 ---------------------------------------------------------------------------------
test('BD-02 a bid is entered and its documents uploaded by drag-and-drop and by keyboard; their text is read', async ({
  page,
  api,
}) => {
  const alice = await api('alice')
  const { idea } = await bidTeam(alice, 'Bid entry', {})
  await startCall(alice, idea.key, 'Shed supply')
  await openCall(alice, idea.key)
  await signIn(page, 'alice')
  await openBids(page, idea.key)
  await page.getByRole('button', { name: 'Enter a bid' }).click()
  const form = page.getByRole('dialog', { name: 'Enter a bid' })
  await form.getByLabel('Bidder').fill('Northwind Data Ltd')
  await form.getByLabel('Contact name').fill('Hannah Wright')
  await form.getByLabel('Contact email').fill('bids@northwind-data.example')
  await form.getByLabel('Price (GBP)').fill('120000')
  await form.getByRole('button', { name: /^(Enter the bid|Save|Add the bid)$/ }).click()
  await expect(toast(page, /Northwind Data Ltd/)).toBeVisible()
  // Entering a bid opens it, ready for its documents.
  const sheet = page.getByRole('dialog', { name: 'Northwind Data Ltd' })
  await expect(sheet.getByRole('heading', { name: 'Documents' })).toBeVisible()
  // A required document not uploaded is flagged at once.
  await expect(mustHaveRow(sheet, MUST_HAVES.insurance)).toContainText(/Missing/i)

  // Drag and drop: two files at once.
  await dropFiles(page, dropZone(sheet), [
    { name: 'Form of tender.pdf', bytes: seedDocument('northwind-form-of-tender.pdf') },
    { name: 'Technical proposal.docx', bytes: seedDocument('northwind-technical-proposal.docx') },
  ])
  await expect(documentRow(sheet, 'Form of tender.pdf')).toBeVisible()
  await expect(documentRow(sheet, 'Technical proposal.docx')).toBeVisible()
  // A file named after a must-have answers it as it lands (UX review M2); one that answers
  // none, in a call with a price question, stays a pricing document until someone says it
  // isn't (M3).
  await expect(
    documentRow(sheet, 'Form of tender.pdf').getByRole('combobox', {
      name: 'Must-have that Form of tender.pdf answers',
    }),
  ).toHaveText(MUST_HAVES.tender)
  const proposal = documentRow(sheet, 'Technical proposal.docx')
  await expect(proposal.getByRole('group', { name: /pricing document/ })).toBeVisible()
  await proposal.getByRole('button', { name: 'Not pricing' }).click()
  await expect(proposal.getByRole('group', { name: /pricing document/ })).toHaveCount(0)

  // Keyboard: Tab to "Choose files", Enter opens the file chooser.
  const choose = sheet.getByRole('button', { name: 'Choose files' })
  await choose.focus()
  const chooser = page.waitForEvent('filechooser')
  await page.keyboard.press('Enter')
  await (
    await chooser
  ).setFiles({
    name: 'Insurance certificate.pdf',
    mimeType: 'application/pdf',
    buffer: seedDocument('northwind-insurance-certificate.pdf'),
  })
  await expect(documentRow(sheet, 'Insurance certificate.pdf')).toBeVisible()

  // The worker reads each document's text; the sheet shows it when it is done.
  for (const name of [
    'Form of tender.pdf',
    'Technical proposal.docx',
    'Insurance certificate.pdf',
  ]) {
    await expect(documentRow(sheet, name)).toContainText('characters of text', { timeout: 60_000 })
  }
  await sheet.getByRole('button', { name: 'Read the text of Technical proposal.docx' }).click()
  const text = page.getByRole('dialog', { name: 'Technical proposal.docx' })
  await expect(text.getByRole('region', { name: /Text of Technical proposal.docx/ })).toContainText(
    /Northwind/,
  )
  await page.keyboard.press('Escape')
  await expect(text).toBeHidden()

  const view = await bidCall(alice, idea.key)
  const entered = (await alice.get<{ items: { id: string }[] }>(`/ideas/${idea.key}/bid-call/bids`))
    .items[0]
  const detail = await waitExtracted(alice, idea.key, entered?.id ?? '')
  expect(detail.documents.map((d) => [d.filename, d.type, d.extraction.state]).sort()).toEqual([
    ['Form of tender.pdf', 'pdf', 'done'],
    ['Insurance certificate.pdf', 'pdf', 'done'],
    ['Technical proposal.docx', 'docx', 'done'],
  ])
  const mustHaveText = new Map(view.call?.template.must_haves.map((m) => [m.id, m.text]))
  expect(
    detail.documents
      .map((d) => [d.filename, d.must_have_id ? mustHaveText.get(d.must_have_id) : null, d.pricing])
      .sort(),
  ).toEqual([
    ['Form of tender.pdf', MUST_HAVES.tender, false],
    ['Insurance certificate.pdf', MUST_HAVES.insurance, false],
    ['Technical proposal.docx', null, false],
  ])
  expect(view.call?.bid_count).toBe(1)
})

// --- BD-03 ---------------------------------------------------------------------------------
test('BD-03 a refused file says why: a macro-enabled document, an executable, an empty file, one over 25 MiB', async ({
  page,
  api,
}) => {
  const alice = await api('alice')
  const { key, northwind } = await assessingCall(alice, 'Bid refusals', {}, {}, { close: false })
  await signIn(page, 'alice')
  await openBids(page, key)
  const sheet = await openBid(page, 'Northwind Data Ltd')
  const input = sheet.locator('input[type=file]')
  await input.setInputFiles([
    { name: 'Terms.docx', mimeType: 'application/octet-stream', buffer: MACRO_DOCM },
    { name: 'setup.pdf', mimeType: 'application/pdf', buffer: EXECUTABLE },
  ])
  const uploads = sheet.getByRole('list', { name: 'Uploads' })
  await expect(uploads.getByRole('listitem').filter({ hasText: 'Terms.docx' })).toContainText(
    /macro/i,
  )
  await expect(uploads.getByRole('listitem').filter({ hasText: 'setup.pdf' })).toContainText(
    'That file type can’t be uploaded',
  )
  await sheet.getByRole('button', { name: 'Dismiss Terms.docx' }).click()
  await sheet.getByRole('button', { name: 'Dismiss setup.pdf' }).click()
  await expect(uploads).toHaveCount(0)
  // Refused before anything is sent: an empty file, and one over 25 MiB.
  const sent: string[] = []
  page.on('request', (request) => {
    if (request.url().includes('/documents?')) sent.push(request.url())
  })
  await input.setInputFiles([
    { name: 'empty.txt', mimeType: 'text/plain', buffer: Buffer.alloc(0) },
    { name: 'huge.pdf', mimeType: 'application/pdf', buffer: Buffer.alloc(25 * 1024 * 1024 + 1) },
  ])
  await expect(uploads.getByText('empty.txt is empty.')).toBeVisible()
  await expect(uploads.getByRole('listitem').filter({ hasText: 'huge.pdf' })).toContainText(
    /25 MB|25 MiB/,
  )
  expect(sent).toEqual([])
  // Nothing was stored: the bid keeps its three documents.
  expect((await bid(alice, key, northwind.id)).documents).toHaveLength(3)
})

// --- BD-04 ---------------------------------------------------------------------------------
test('BD-04 a missing must-have is flagged at once; one click and a reason reject the bid, and Reinstate undoes it', async ({
  page,
  api,
}) => {
  const alice = await api('alice')
  const { key, quillfield } = await assessingCall(
    alice,
    'Bid flags',
    {},
    {},
    { flagged: true, close: false },
  )
  await signIn(page, 'alice')
  await openBids(page, key)
  const row = bidsRegion(page).getByRole('row', { name: /Quillfield/ })
  await expect(row).toContainText('1 missing')
  const sheet = await openBid(page, 'Quillfield Systems')
  await expect(sheet.getByText('This bid doesn’t meet every must-have')).toBeVisible()
  await expect(mustHaveRow(sheet, MUST_HAVES.insurance)).toContainText(/Missing/i)
  // A confirmation decided by a person: not met with a note, cleared, met again.
  const terms = mustHaveRow(sheet, MUST_HAVES.terms)
  await terms.getByRole('button', { name: 'Not met…' }).click()
  const note = page.getByRole('dialog', { name: /Not met: Accepts our standard terms/ })
  await note.getByLabel('Note').fill('They add their own payment terms.')
  await note.getByRole('button', { name: 'Not met', exact: true }).click()
  await expect(toast(page, 'Accepts our standard terms: not met')).toBeVisible()
  await expect(terms).toContainText('They add their own payment terms.')
  await terms.getByRole('button', { name: 'Clear' }).click()
  await expect(toast(page, 'Accepts our standard terms: cleared')).toBeVisible()
  await terms.getByRole('button', { name: 'Met', exact: true }).click()
  await expect(toast(page, 'Accepts our standard terms: met')).toBeVisible()
  // Reject: one click, the reason already says what is missing.
  await sheet.getByRole('button', { name: 'Reject…' }).click()
  const reject = page.getByRole('dialog', { name: 'Reject the bid from Quillfield Systems?' })
  await expect(reject.getByLabel('Reason')).toHaveValue(/Missing: Insurance certificate\./)
  await reject.getByRole('button', { name: 'Reject the bid' }).click()
  await expect(toast(page, 'Bid from Quillfield Systems rejected')).toBeVisible()
  await expect(sheet.getByText('Rejected', { exact: true }).first()).toBeVisible()
  let detail = await bid(alice, key, quillfield?.id ?? '')
  expect(detail.status).toBe('rejected')
  expect(detail.rejection?.reason).toMatch(/Missing: Insurance certificate\./)
  const audit = await alice.audit({ action: 'bid.reject' })
  expect(audit.some((entry) => JSON.stringify(entry).includes(quillfield?.id ?? '-'))).toBe(true)
  // Reinstate: received again, the rejection kept on record.
  await sheet.getByRole('button', { name: 'Reinstate' }).click()
  await expect(toast(page, 'Bid from Quillfield Systems reinstated')).toBeVisible()
  await expect(sheet.getByRole('button', { name: 'Reinstate' })).toHaveCount(0)
  detail = await bid(alice, key, quillfield?.id ?? '')
  expect(detail.status).toBe('received')
  expect(detail.rejection?.reinstated_at).toBeTruthy()
})

// --- BD-05 ---------------------------------------------------------------------------------
test('BD-05 an assessor scores a section blind, beside the bid’s documents, then sees the others’ scores', async ({
  page,
  api,
}) => {
  const alice = await api('alice')
  const carol = await api('carol')
  const mateo = await api('mateo')
  const arranged = await assessingCall(
    alice,
    'Bid assess',
    { carol: 'member', mateo: 'member', priya: 'member', sven: 'member' },
    { Technical: ['carol', 'mateo'], Commercial: ['priya'], Delivery: ['sven'] },
  )
  const { key, call, northwind } = arranged
  // Mateo has submitted Northwind's Technical section; Carol hasn't.
  await assess(mateo, key, call, northwind.id, 'Technical', [2, 3])
  await signIn(page, 'carol')
  await openBids(page, key)
  await expect(queue(page)).toContainText('0 of 2 submitted')
  await expect(comparisonRegion(page)).toHaveCount(0)
  await expect(bidsRegion(page).getByRole('columnheader', { name: 'Price' })).toHaveCount(0)
  await queue(page).getByRole('button', { name: 'Assess: Northwind Data Ltd, Technical' }).click()
  const sheet = page.getByRole('dialog', { name: /Technical · Northwind/ })
  await expect(
    sheet.getByText('The other assessors’ scores for this section stay hidden'),
  ).toBeVisible()
  await expect(sheet.getByText('Everyone’s scores')).toHaveCount(0)
  await expect(sheet.getByText('Mateo Rodríguez')).toHaveCount(0)
  // The bid's documents and their text beside the questions.
  const beside = sheet.getByRole('complementary', { name: 'The bid’s documents' })
  await expect(beside).toBeVisible()
  await expect(beside).toContainText('form-of-tender.txt')
  await expect(beside).not.toContainText('pricing-schedule')
  // Every score question needs a score.
  await sheet.getByRole('button', { name: 'Submit' }).click()
  await expect(sheet.getByText('Pick a score').first()).toBeVisible()
  const first = sheet.getByRole('radiogroup', {
    name: 'How well does the proposed solution meet our requirements?',
  })
  await first.getByRole('radio', { name: '5' }).click()
  const second = sheet.getByRole('radiogroup', {
    name: 'How well will our data be kept secure and compliant?',
  })
  // Keyboard: a digit picks the focused question's score.
  await second.getByRole('radio', { name: '3' }).click()
  await page.keyboard.press('4')
  await expect(second.getByRole('radio', { name: '4' })).toBeChecked()
  await sheet.getByRole('button', { name: 'Submit' }).click()
  await expect(toast(page, 'Technical submitted for Northwind Data Ltd')).toBeVisible()
  await expect(sheet.getByRole('heading', { name: 'Everyone’s scores' })).toBeVisible()
  await expect(sheet.getByRole('list', { name: 'Assessments' })).toContainText('Mateo Rodríguez')
  // The disagreement on the first question (5 and 2) shows once she has submitted.
  await expect(sheet.getByText(/disagree/i).first()).toBeVisible()
  const section = await carol.get<{ hidden: boolean; assessments: unknown[] }>(
    `/ideas/${key}/bid-call/bids/${northwind.id}/sections/${call.template.sections[0]?.id}/assessments`,
  )
  expect(section.hidden).toBe(false)
  expect(section.assessments).toHaveLength(2)
})

// --- BD-06 ---------------------------------------------------------------------------------
test('BD-06 prices and pricing documents only for the managers and the price section’s assessors (TOOLS-3)', async ({
  page,
}) => {
  // Carol assesses Technical: no prices, the pricing schedule only counted.
  await signIn(page, 'carol')
  await openBids(page, DEMO.key)
  await expect(bidsRegion(page).getByRole('columnheader', { name: 'Price' })).toHaveCount(0)
  await expect(bidsRegion(page)).not.toContainText('£')
  await expect(bidsRegion(page).getByText(DEMO.quillfield)).toHaveCount(0)
  const sheet = await openBid(page, DEMO.northwind)
  await expect(sheet).not.toContainText('£120,000')
  await expect(sheet).not.toContainText('pricing-schedule')
  await expect(mustHaveRow(sheet, MUST_HAVES.pricing)).toContainText(/restricted/i)
  await page.keyboard.press('Escape')
  // Priya assesses Commercial (with the price): prices and the pricing schedule.
  await page.context().clearCookies()
  await signIn(page, 'priya')
  await openBids(page, DEMO.key)
  await expect(bidsRegion(page).getByRole('row', { name: /Northwind/ })).toContainText(
    '£120,000.00',
  )
  const priya = await openBid(page, DEMO.northwind)
  await expect(documentRow(priya, 'northwind-pricing-schedule.pdf')).toBeVisible()
})

// --- BD-07 ---------------------------------------------------------------------------------
test('BD-07 the comparison ranks the qualified bids by the contract’s math, and the award warns about what is outstanding', async ({
  page,
  api,
}) => {
  const alice = await api('alice')
  const carol = await api('carol')
  const mateo = await api('mateo')
  const priya = await api('priya')
  const { key, call, northwind, tessellate } = await assessingCall(
    alice,
    'Bid award',
    { carol: 'member', mateo: 'member', priya: 'member', sven: 'member' },
    { Technical: ['carol', 'mateo'], Commercial: ['priya'], Delivery: ['sven', 'mateo'] },
    { flagged: true },
  )
  // The scores of contract-phase10 §8.1's worked example (sven owes both Delivery
  // assessments; mateo gives his). With the default template (Technical 40: Q1 ×2, Q2 ×1;
  // Commercial 40: the price ×3, two questions ×1; Delivery 20: ×2, ×1):
  //   Northwind: Technical (2×4.5 + 4)/3 = 13/3 → 86.7; Commercial (3×4 + 4 + 4)/5 = 4 →
  //   80.0 (price 96,000/120,000×5 = 4); Delivery (2×4 + 5)/3 → 86.7; total 0.4×86.67 +
  //   0.4×80 + 0.2×86.67 = 84.0.
  //   Tessellate: Technical (2×3 + 3)/3 = 3 → 60.0 (Q1 4 and 2: disagreement); Commercial
  //   (3×5 + 3 + 3)/5 = 4.2 → 84.0; Delivery (2×3 + 4)/3 → 66.7; total 24 + 33.6 + 13.33
  //   = 70.9.
  await assess(carol, key, call, northwind.id, 'Technical', [4, 4])
  await assess(mateo, key, call, northwind.id, 'Technical', [5, 4])
  await assess(carol, key, call, tessellate.id, 'Technical', [4, 3])
  await assess(mateo, key, call, tessellate.id, 'Technical', [2, 3])
  await assess(priya, key, call, northwind.id, 'Commercial', [4, 4])
  await assess(priya, key, call, tessellate.id, 'Commercial', [3, 3])
  await assess(mateo, key, call, northwind.id, 'Delivery', [4, 5])
  await assess(mateo, key, call, tessellate.id, 'Delivery', [3, 4])
  const numbers = await comparison(alice, key)
  const row = (bidder: string) => numbers.rows.find((r) => r.bid.bidder === bidder)
  // Quillfield isn't qualified (no insurance certificate): no total, out of the price
  // formula (its 84,000 would be the lowest), so Tessellate's 96,000 is the lowest.
  expect(row('Quillfield Systems')).toMatchObject({ total: null, rank: null, price_score: null })
  expect(row('Northwind Data Ltd')).toMatchObject({ rank: 1, total: 84, price_score: 4 })
  expect(row('Northwind Data Ltd')?.sections.map((s) => s.score)).toEqual([86.7, 80, 86.7])
  expect(row('Tessellate Software')).toMatchObject({ rank: 2, total: 70.9, price_score: 5 })
  expect(row('Tessellate Software')?.sections.map((s) => s.score)).toEqual([60, 84, 66.7])
  expect(row('Tessellate Software')?.sections[0]?.disagreement).toBe(true)
  expect(numbers.complete).toBe(false)
  const { submitted, total: expected } = numbers.progress
  expect(submitted).toBe(8)

  await signIn(page, 'alice')
  await openBids(page, key)
  const table = comparisonRegion(page).getByRole('table', { name: 'Bids compared' })
  const northwindRow = table.getByRole('row', { name: /Northwind/ })
  await expect(northwindRow.getByRole('cell').first()).toHaveText(/1$/)
  await expect(northwindRow).toContainText('86.7')
  await expect(northwindRow).toContainText('84.0')
  const tessellateRow = table.getByRole('row', { name: /Tessellate/ })
  // A section's score opens its assessments; the disagreement is in its name.
  await expect(
    tessellateRow.getByRole('button', { name: /^Technical for Tessellate.*assessors disagree/ }),
  ).toBeVisible()
  await expect(tessellateRow).toContainText('70.9')
  await expect(comparisonRegion(page)).toContainText(`${submitted} of ${expected} assessed`)

  await page.getByRole('button', { name: 'Award…' }).click()
  const dialog = page.getByRole('dialog', { name: 'Award the call' })
  await expect(
    dialog.getByText(`${expected - submitted} assessments are outstanding`),
  ).toBeVisible()
  // Only qualified bids can be awarded.
  await expect(dialog.getByRole('radio')).toHaveCount(2)
  await dialog.getByRole('radio', { name: 'Northwind Data Ltd' }).click()
  await dialog.getByLabel('Reason').fill('Strongest technically, within budget.')
  await dialog.getByRole('button', { name: 'Award to Northwind Data Ltd' }).click()
  await expect(toast(page, 'Awarded to Northwind Data Ltd')).toBeVisible()
  await expect(page.getByText('Awarded', { exact: true }).first()).toBeVisible()
  await expect(page.getByRole('button', { name: 'Award…' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Enter a bid' })).toHaveCount(0)
  const after = await bidCall(alice, key)
  expect(after.call?.status).toBe('awarded')
  expect(after.call?.award_reason).toBe('Strongest technically, within budget.')
  // The same numbers and ranks after the award (scoring follows the facts).
  const awarded = await comparison(alice, key)
  expect(awarded.rows.find((r) => r.bid.bidder === 'Northwind Data Ltd')).toMatchObject({
    rank: 1,
    total: 84,
  })
  // The feed says the call was awarded, naming no bid.
  await page.getByRole('tab', { name: /^Overview/ }).click()
  await expect(page.getByText(/awarded the call|call for bids.*awarded/i).first()).toBeVisible()
})

// --- BD-08 ---------------------------------------------------------------------------------
test('BD-08 My work lists “Bids to assess” and the sidebar counts them (alice owes TOOLS-3’s Delivery)', async ({
  page,
}) => {
  await signIn(page, 'alice')
  await page.goto('/')
  const section = page.getByRole('region', { name: /Bids to assess/ })
  await expect(section.getByRole('link', { name: DEMO.title, exact: true })).toBeVisible()
  await expect(section).toContainText('2 to submit')
  await expect(section).toContainText('Delivery')
  await expect(section).not.toContainText(DEMO.northwind)
  await expect(section).not.toContainText('£')
  await expect(page.getByRole('link', { name: /^Bids, 2 to assess/ })).toBeVisible()
  await section.getByRole('link', { name: /^Assess 2 bid sections?/ }).click()
  await expect(page).toHaveURL(new RegExp(`/ideas/${DEMO.key}\\?tab=bids`))
  await expect(queue(page)).toBeVisible({ timeout: 15_000 })
  await expect(queue(page)).toContainText('0 of 2 submitted')
})

// --- BD-09 ---------------------------------------------------------------------------------
test('BD-09 the project’s Bids tab edits the default template; an existing call keeps its copy, a new one takes it', async ({
  page,
  api,
}) => {
  const alice = await api('alice')
  const { project, idea } = await bidTeam(alice, 'Bid template', {})
  await startCall(alice, idea.key, 'Before the change')
  await signIn(page, 'alice')
  await page.goto(`/p/${project.slug}/settings?tab=bids`)
  await expect(page.getByRole('heading', { name: 'Bid evaluation template' })).toBeVisible({
    timeout: 15_000,
  })
  await expect(page.getByText('Section weights add up to 100%')).toBeVisible()
  await page.getByLabel('Weight of Technical (%)').fill('50')
  await expect(page.getByText(/add up to 110%/)).toBeVisible()
  // Saving with weights that don't add up says so and saves nothing.
  await page.getByRole('button', { name: 'Save template' }).click()
  await expect(page.getByRole('alert').first()).toBeVisible()
  expect((await bidTemplate(alice, project.slug)).sections.map((s) => s.weight)).toEqual([
    40, 40, 20,
  ])
  await page.getByLabel('Weight of Commercial (%)').fill('30')
  await expect(page.getByText('Section weights add up to 100%')).toBeVisible()
  await page.getByRole('button', { name: 'Save template' }).click()
  await expect(toast(page, 'Bid template saved')).toBeVisible()
  const template = await bidTemplate(alice, project.slug)
  expect(template.sections.map((s) => s.weight)).toEqual([50, 30, 20])
  // The existing call keeps 40/40/20; a new idea's call takes 50/30/20.
  const existing = await bidCall(alice, idea.key)
  expect(existing.call?.template.sections.map((s) => s.weight)).toEqual([40, 40, 20])
  const second = await alice.createIdea(project.slug, { title: 'Second', summary: 'Another.' })
  await alice.changeStatus(second.key, 'shortlisted')
  await alice.startProposal(second.key)
  const fresh = await startCall(alice, second.key, 'After the change')
  expect(fresh.call?.template.sections.map((s) => s.weight)).toEqual([50, 30, 20])
})

// --- BD-10 ---------------------------------------------------------------------------------
test('BD-10 a viewer sees only that a call exists; a guest researcher not even that', async ({
  page,
  api,
}) => {
  // Zanele is a viewer in Internal Tools: TOOLS-3's call, its status and number of bids.
  await signIn(page, 'zanele')
  await openBids(page, DEMO.key)
  await expect(page.getByRole('heading', { level: 2, name: DEMO.title })).toBeVisible()
  await expect(
    page.getByText('Only the idea’s owner, admins and the call’s assessors see the bids.'),
  ).toBeVisible()
  await expect(page.getByRole('tabpanel')).toContainText('3 bids')
  for (const hidden of [DEMO.northwind, DEMO.tessellate, DEMO.quillfield, '£', DEMO.rejection]) {
    await expect(page.getByRole('tabpanel')).not.toContainText(hidden)
  }
  await expect(bidsRegion(page)).toHaveCount(0)
  await expect(comparisonRegion(page)).toHaveCount(0)

  // A guest researcher (Bob: no role in the private project) gets no Bids tab, and 404.
  const alice = await api('alice')
  const bob = await api('bob')
  const project = await researchTeam(alice, 'Bid guest', 'before_evaluation', {})
  const idea = await alice.createIdea(project.slug, {
    title: `Bid guest ${project.key}`,
    summary: 'Researched by an outsider, then put out to tender.',
  })
  await assignResearcher(alice, idea.key, bob.me, null)
  await answerRequired(alice, idea.key)
  await alice.changeStatus(idea.key, 'shortlisted')
  await alice.startProposal(idea.key)
  await startCall(alice, idea.key, 'Guest-proof supply')
  expect((await bob.raw('GET', `/ideas/${idea.key}/bid-call`)).status()).toBe(404)
  expect((await bob.idea(idea.key)).bid_call).toBeNull()
  await page.context().clearCookies()
  await signIn(page, 'bob')
  await page.goto(`/ideas/${idea.key}?tab=bids`)
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
  await expect(bidsTab(page)).toHaveCount(0)
  await expect(page.getByText('Guest-proof supply')).toHaveCount(0)
})

// --- BD-11 ---------------------------------------------------------------------------------
test('BD-11 the evaluation report exports as PDF and Markdown for a call manager', async ({
  page,
  api,
}) => {
  await signIn(page, 'kenji')
  await openBids(page, DEMO.key)
  await page.getByRole('button', { name: 'More for this call' }).click()
  await page.getByRole('menuitem', { name: 'Export the report' }).click()
  const download = page.waitForEvent('download')
  await page.getByRole('menuitem', { name: 'PDF' }).click()
  const file = await download
  expect(file.suggestedFilename()).toBe(`${DEMO.key}-bid-evaluation.pdf`)
  const pdf = await readPdf(readFileSync(await file.path()))
  const text = pdf.pages.join(' ').replace(/\s+/g, ' ')
  expect(text).toMatch(/bid evaluation report/i)
  expect(text).toContain(DEMO.northwind)
  expect(text).toContain(DEMO.rejection)
  const kenji = await api('kenji')
  const markdown = await kenji.raw('GET', `/ideas/${DEMO.key}/bid-call/report/markdown`)
  expect(markdown.status()).toBe(200)
  expect(await markdown.text()).toContain('84.0')
  // An assessor may not export it.
  const carol = await api('carol')
  expect((await carol.raw('GET', `/ideas/${DEMO.key}/bid-call/report/pdf`)).status()).toBe(403)
})

// --- BD-12 ---------------------------------------------------------------------------------
test('BD-12 “Asked to assess bids” reaches a new assessor by email: the call, their sections and the due date, nothing else', async ({
  api,
}) => {
  const alice = await api('alice')
  test.skip(!(await new Mailpit().isUp()), 'needs Mailpit (E2E_SMTP=1)')
  const people = await newPeople(alice, ['nora'])
  const { nora } = people
  try {
    const { key, call, project } = await assessingCall(alice, 'Bid email', {}, {}, { close: false })
    await alice.send(
      'POST',
      `/projects/${project.slug}/members`,
      { user_id: nora.user.id, role: 'member' },
      201,
    )
    const since = new Date()
    await alice.send('PUT', `/ideas/${key}/bid-call/assessors`, {
      sections: call.template.sections.map((s) => ({
        section_id: s.id,
        user_ids: s.title === 'Delivery' ? [nora.user.id] : [],
      })),
      due_at: daysFromNow(6),
    })
    const message = await emailTo(nora, /assess/i, since)
    const text = `${visibleText(message.HTML)}\n${message.Text}`
    expect(text).toContain(call.title)
    expect(text).toContain('Delivery')
    expect(text).toContain(`/ideas/${key}?tab=bids`)
    for (const secret of ['Northwind', 'Tessellate', '120,000', '96,000', '£']) {
      expect(text, secret).not.toContain(secret)
    }
    // Its one fixed sentence about blind scoring names scores; nothing else may.
    expectNoScoreData('Asked to assess bids', text.replaceAll(BLIND_LINE, ''))
    expect(await emailCount(nora, since, /assess/i)).toBe(1)
    // In the inbox too, with the same restraint.
    const items = await nora.api.notifications()
    const item = items.find((candidate) => candidate.type === 'assessor_assigned')
    expect(item).toBeTruthy()
    expect(JSON.stringify(item)).not.toMatch(/Northwind|Tessellate|120000|96000/)
  } finally {
    await disposePeople(people)
  }
})

// --- BD-14 (P10-QA-F1, fixed) ------------------------------------------------------------------
test('BD-14 a manager who still owes a bid’s assessment isn’t offered “Count in the totals” for its AI assessment (TOOLS-3, alice)', async ({
  page,
  api,
}) => {
  // Contract §9.4: a call manager who owes an assessment of the bid can't include the AI's
  // assessment (404) until they submit. Alice owes Tessellate's Delivery, so the list says
  // can_include false and the comparison offers her no switch.
  const alice = await api('alice')
  const tessellate = (
    await alice.get<{ items: { id: string; bidder: string }[] }>(`/ideas/${DEMO.key}/bid-call/bids`)
  ).items.find((b) => b.bidder === DEMO.tessellate)
  const list = await alice.get<{ can_include: boolean }>(
    `/ideas/${DEMO.key}/bid-call/bids/${tessellate?.id}/ai-assessments`,
  )
  expect(list.can_include).toBe(false)
  await signIn(page, 'alice')
  await openBids(page, DEMO.key)
  await expect(
    comparisonRegion(page).getByRole('switch', { name: /assessment of Tessellate Software/ }),
  ).toHaveCount(0)
})
