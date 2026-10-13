import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import type { Locator, Page } from '@playwright/test'

import { Api, createTeamProject, daysFromNow, type Person } from '../tests/support/api'
import {
  bidCall,
  completeBid,
  DEMO,
  decideMustHave,
  enterBid,
  MUST_HAVES,
  mustHaveId,
  openCall,
  seedDocument,
  startCall,
  uploadDocument,
  waitExtracted,
  type BidCall,
} from '../tests/support/bids'
import { disposePeople, Mailpit, newPeople, signInAs, type Someone } from '../tests/support/email'
import { expect, settled, signIn, test } from '../tests/support/fixtures'
import { renderPdfPages } from '../tests/support/pdf'

/**
 * Review screenshots of the Phase 10 screens (calls for bids) from the real app with the
 * demo data. Not a regression test.
 *
 * `npm run screenshots:phase10` → docs/screenshots/phase-10/ (`SCREENSHOT_DIR` overrides):
 * <screen>-<1440-light|1440-dark|390-light>.png, emails/ ("Asked to assess bids" as
 * Mailpit received it) and pdf/ (TOOLS-3's evaluation report and its first pages). The
 * demo story: TOOLS-3's "Data platform build" is being assessed; kenji (the idea's owner)
 * sees the bids, the comparison with the AI's assessment of Tessellate not counted and the
 * award dialog; alice owes both Delivery assessments (her sheet, with the bid's documents
 * beside it; her My work); dave edits Internal Tools' template. A bid with documents and a
 * flagged must-have, and the reject dialog, come from a call of their own ("Facilities",
 * private, archived afterwards: Quillfield Systems without its insurance certificate,
 * open, not rejected); so does the email (Nora Quinn, a new member, asked to assess
 * Delivery). Otherwise read-only: nothing is saved from the dialogs.
 */

const here = dirname(fileURLToPath(import.meta.url))
const outDir = resolve(process.env.SCREENSHOT_DIR ?? join(here, '../../docs/screenshots/phase-10'))
const emailDir = join(outDir, 'emails')
const pdfDir = join(outDir, 'pdf')
mkdirSync(emailDir, { recursive: true })
mkdirSync(pdfDir, { recursive: true })

const baseURL = () => test.info().project.use.baseURL ?? ''
const bidsRegion = (page: Page) => page.getByRole('region', { name: 'Bids', exact: true })

test.describe.configure({ mode: 'serial' })

/** Scrolls `target` to the top of its scrolling container (below any sticky bar). */
async function scrollTo(target: Locator) {
  await expect(target).toBeVisible()
  await target.evaluate((node) => node.scrollIntoView({ block: 'start' }))
}

async function bidsTab(page: Page, key: string, heading: string) {
  await page.goto(`/ideas/${key}?tab=bids`)
  await expect(page.getByRole('heading', { level: 2, name: heading })).toBeVisible({
    timeout: 15_000,
  })
}

async function openBid(page: Page, bidder: string): Promise<Locator> {
  await bidsRegion(page).getByRole('button', { name: bidder, exact: true }).click()
  const sheet = page.getByRole('dialog', { name: bidder })
  await expect(sheet.getByRole('heading', { name: 'Documents' })).toBeVisible()
  return sheet
}

// --- A call of its own: a flagged bid (Facilities) -----------------------------------------
interface Facilities {
  key: string
  title: string
  call: BidCall
}

let facilities: Promise<Facilities> | undefined
const cleanups: (() => Promise<void>)[] = []

/** Facilities' open call: Northwind complete, Quillfield without its insurance. */
function arrangeFacilities(): Promise<Facilities> {
  facilities ??= (async () => {
    const alice = await Api.as(baseURL(), 'alice')
    cleanups.push(async () => {
      await alice.archiveCreated()
      await alice.dispose()
    })
    const project = await createTeamProject(alice, 'Facilities', {})
    const idea = await alice.createIdea(project.slug, {
      title: 'Covered bike shed by the car park',
      summary: 'Forty covered, lockable bike stands with lighting, by the staff car park.',
    })
    await alice.changeStatus(idea.key, 'shortlisted')
    await alice.startProposal(idea.key)
    const title = 'Bike shed build'
    await startCall(
      alice,
      idea.key,
      title,
      'Design, supply and fit the covered bike shed, with lighting and a year of upkeep.',
    )
    const call = (await openCall(alice, idea.key, 9)).call as BidCall
    await completeBid(alice, idea.key, call, 'Northwind Data Ltd', '42000.00')
    const quillfield = await enterBid(alice, idea.key, {
      bidder: 'Quillfield Systems',
      price: '38500.00',
      contact_name: 'Owen Price',
      contact_email: 'owen@quillfield.example',
    })
    for (const [file, mustHave] of [
      ['quillfield-form-of-tender.pdf', MUST_HAVES.tender],
      ['quillfield-pricing-schedule.pdf', MUST_HAVES.pricing],
      ['quillfield-technical-proposal.docx', null],
    ] as const) {
      const response = await uploadDocument(
        alice,
        idea.key,
        quillfield.id,
        file,
        seedDocument(file),
        {
          mustHaveId: mustHave ? mustHaveId(call, mustHave) : undefined,
        },
      )
      expect(response.status(), await response.text()).toBe(201)
    }
    await decideMustHave(alice, idea.key, quillfield.id, mustHaveId(call, MUST_HAVES.terms), 'met')
    await waitExtracted(alice, idea.key, quillfield.id)
    return { key: idea.key, title, call: (await bidCall(alice, idea.key)).call as BidCall }
  })()
  return facilities
}

test.afterAll(async () => {
  for (const cleanup of cleanups.splice(0)) await cleanup()
})

interface Shot {
  name: string
  as: Person
  fullPage?: boolean
  open: (page: Page, phone: boolean) => Promise<void>
}

const SHOTS: Shot[] = [
  {
    name: 'call-overview',
    as: 'kenji',
    open: async (page) => {
      await bidsTab(page, DEMO.key, DEMO.title)
      await expect(bidsRegion(page).getByRole('row', { name: /Northwind/ })).toBeVisible()
    },
  },
  {
    name: 'bid-documents-flagged',
    as: 'alice',
    open: async (page) => {
      const { key, title } = await arrangeFacilities()
      await bidsTab(page, key, title)
      const sheet = await openBid(page, 'Quillfield Systems')
      await expect(sheet.getByText('This bid doesn’t meet every must-have')).toBeVisible()
    },
  },
  {
    name: 'reject-dialog',
    as: 'alice',
    open: async (page) => {
      const { key, title } = await arrangeFacilities()
      await bidsTab(page, key, title)
      const sheet = await openBid(page, 'Quillfield Systems')
      await sheet.getByRole('button', { name: 'Reject…' }).click()
      const dialog = page.getByRole('dialog', { name: 'Reject Quillfield Systems’s bid?' })
      await expect(dialog.getByLabel('Reason')).toHaveValue(/Missing: Insurance certificate\./)
    },
  },
  {
    name: 'assessment-sheet-document-text',
    as: 'alice',
    open: async (page, phone) => {
      await bidsTab(page, DEMO.key, DEMO.title)
      await page
        .getByRole('region', { name: 'Your assessments' })
        .getByRole('button', { name: `Assess: ${DEMO.northwind}, Delivery` })
        .click()
      const sheet = page.getByRole('dialog', { name: /Delivery · Northwind/ })
      await expect(sheet.getByRole('radiogroup').first()).toBeVisible()
      if (!phone) {
        const beside = sheet.getByRole('complementary', { name: 'The bid’s documents' })
        await expect(beside).toBeVisible()
        const pick = beside.getByRole('combobox', { name: 'Document to read' })
        if (await pick.isVisible()) {
          await pick.click()
          await page.getByRole('option', { name: /technical-proposal/ }).click()
        }
        await expect(beside).toContainText(/Northwind/)
      }
    },
  },
  {
    name: 'comparison-ai-not-counted',
    as: 'kenji',
    open: async (page) => {
      await bidsTab(page, DEMO.key, DEMO.title)
      const comparison = page.getByRole('region', { name: 'Comparison' })
      await expect(
        comparison.getByRole('switch', { name: /assessment of Tessellate Software/ }),
      ).not.toBeChecked()
      await scrollTo(comparison)
    },
  },
  {
    name: 'award-dialog',
    as: 'kenji',
    open: async (page) => {
      await bidsTab(page, DEMO.key, DEMO.title)
      await page.getByRole('button', { name: 'Award…' }).click()
      const dialog = page.getByRole('dialog', { name: 'Award the call' })
      await dialog.getByRole('radio', { name: DEMO.northwind }).click()
      await expect(dialog.getByText(/assessments are outstanding/)).toBeVisible()
    },
  },
  {
    name: 'project-bids-template',
    as: 'dave',
    open: async (page) => {
      await page.goto('/p/internal-tools/settings?tab=bids')
      await expect(page.getByRole('heading', { name: 'Bid evaluation template' })).toBeVisible({
        timeout: 15_000,
      })
    },
  },
  {
    name: 'my-work-bids-to-assess',
    as: 'alice',
    open: async (page) => {
      await page.goto('/')
      const section = page.getByRole('region', { name: /Bids to assess/ })
      await expect(section.getByRole('link', { name: DEMO.title, exact: true })).toBeVisible()
      await scrollTo(section)
    },
  },
  {
    name: 'bids-assessor',
    as: 'carol',
    open: async (page) => {
      await bidsTab(page, DEMO.key, DEMO.title)
      await expect(page.getByRole('region', { name: 'Your assessments' })).toBeVisible()
    },
  },
  {
    name: 'bids-viewer-summary',
    as: 'zanele',
    open: async (page) => {
      await bidsTab(page, DEMO.key, DEMO.title)
    },
  },
]

const VARIANTS = [
  {
    suffix: '1440-light',
    viewport: { width: 1440, height: 900 },
    colorScheme: 'light',
    phone: false,
  },
  {
    suffix: '1440-dark',
    viewport: { width: 1440, height: 900 },
    colorScheme: 'dark',
    phone: false,
  },
  { suffix: '390-light', viewport: { width: 390, height: 844 }, colorScheme: 'light', phone: true },
] as const

async function shoot(page: Page, path: string, fullPage = false) {
  await settled(page)
  await page.evaluate(() => document.fonts.ready)
  await page.waitForTimeout(500) // enter animations
  await page.screenshot({ path, animations: 'disabled', caret: 'hide', fullPage })
}

test('email: “Asked to assess bids” as a new assessor received it', async ({ browser }) => {
  test.setTimeout(120_000)
  const alice = await Api.as(baseURL(), 'alice')
  const people = await newPeople(alice, ['nora'])
  try {
    test.skip(!(await alice.notificationSummary()).email_available, 'needs SMTP')
    const nora: Someone = people.nora
    const { key, call } = await arrangeFacilities()
    const slug = (await alice.idea(key)).project.slug
    await alice.send(
      'POST',
      `/projects/${slug}/members`,
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
    const message = await new Mailpit().waitForMessage(nora.email, { since, subject: /assess/i })
    writeFileSync(join(emailDir, 'assessor-assigned.html'), message.HTML)
    writeFileSync(join(emailDir, 'assessor-assigned.txt'), message.Text)
    for (const variant of [
      { suffix: 'desktop-light', viewport: { width: 1000, height: 900 }, colorScheme: 'light' },
      { suffix: 'desktop-dark', viewport: { width: 1000, height: 900 }, colorScheme: 'dark' },
      { suffix: '390-light', viewport: { width: 390, height: 844 }, colorScheme: 'light' },
    ] as const) {
      const context = await browser.newContext({
        viewport: variant.viewport,
        colorScheme: variant.colorScheme,
        isMobile: variant.suffix.startsWith('390'),
      })
      const page = await context.newPage()
      await page.setContent(message.HTML, { waitUntil: 'load' })
      await page.screenshot({
        path: join(emailDir, `assessor-assigned-${variant.suffix}.png`),
        fullPage: true,
      })
      await context.close()
    }
    // Nora signs in once, so her inbox item is on record for the review too.
    void signInAs
  } finally {
    await disposePeople(people)
    await alice.dispose()
  }
})

test('pdf: TOOLS-3’s evaluation report', async ({ browser }) => {
  test.setTimeout(120_000)
  const kenji = await Api.as(baseURL(), 'kenji')
  try {
    const response = await kenji.raw('GET', `/ideas/${DEMO.key}/bid-call/report/pdf`)
    expect(response.status()).toBe(200)
    const body = await response.body()
    writeFileSync(join(pdfDir, `${DEMO.key}-bid-evaluation.pdf`), body)
    const markdown = await kenji.raw('GET', `/ideas/${DEMO.key}/bid-call/report/markdown`)
    writeFileSync(join(pdfDir, `${DEMO.key}-bid-evaluation.md`), await markdown.body())
    await renderPdfPages(browser, body, [
      { page: 1, path: join(pdfDir, `${DEMO.key}-bid-evaluation-page-1.png`) },
      { page: 2, path: join(pdfDir, `${DEMO.key}-bid-evaluation-page-2.png`) },
    ])
  } finally {
    await kenji.dispose()
  }
})

for (const variant of VARIANTS) {
  test.describe(variant.suffix, () => {
    test.use({
      viewport: variant.viewport,
      colorScheme: variant.colorScheme,
      isMobile: variant.phone,
      hasTouch: variant.phone,
    })

    for (const shot of SHOTS) {
      test(`${shot.name}-${variant.suffix}`, async ({ page }) => {
        test.setTimeout(90_000)
        await signIn(page, shot.as)
        await shot.open(page, variant.phone)
        await shoot(page, join(outDir, `${shot.name}-${variant.suffix}.png`), shot.fullPage)
      })
    }
  })
}
