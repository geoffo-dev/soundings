import { readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { expect } from '@playwright/test'

import type { components } from '../../../frontend/src/api/generated/schema'
import {
  createTeamProject,
  daysFromNow,
  userOf,
  type Api,
  type IdeaDetail,
  type Person,
  type Project,
  type ProjectRole,
} from './api'

/**
 * Phase 10 (contract-phase10): calls for bids, arranged through the real API as a call
 * manager would (a session, CSRF; uploads are the raw file as the body, as the SPA sends
 * them). Specs that change a call use a private project of their own (`bidTeam`), so they
 * run side by side and never touch the demo story (TOOLS-3's "Data platform build").
 */

type Schemas = components['schemas']
export type BidCallView = Schemas['BidCallView']
export type BidCall = Schemas['BidCall']
export type Bid = Schemas['Bid']
export type BidDetail = Schemas['BidDetail']
export type BidDocument = Schemas['BidDocument']
export type BidComparison = Schemas['BidComparison']
export type BidComparisonRow = Schemas['BidComparisonRow']
export type BidCallSection = Schemas['BidCallSection']
export type BidTemplate = Schemas['BidTemplate']
export type MyBidAssessment = Schemas['MyBidAssessment']
export type BidSectionAssessments = Schemas['BidSectionAssessments']
export type BidAiAssessmentList = Schemas['BidAiAssessmentList']

const here = path.dirname(fileURLToPath(import.meta.url))
/** The demo's bid documents (backend/app/seed/bids/: small PDFs and Word files). */
export const SEED_DOCUMENTS = path.resolve(here, '../../../backend/app/seed/bids')
export const seedDocument = (name: string) => readFileSync(path.join(SEED_DOCUMENTS, name))

/** The default template's must-haves (`DEFAULT_BID_TEMPLATE`). */
export const MUST_HAVES = {
  tender: 'Signed form of tender',
  pricing: 'Pricing schedule',
  insurance: 'Insurance certificate',
  terms: 'Accepts our standard terms',
} as const
/** The default template's sections and their weights. */
export const SECTIONS = { technical: 'Technical', commercial: 'Commercial', delivery: 'Delivery' }

/** The seeded call (backend/app/seed/bids.py): TOOLS-3, kenji's idea in Internal Tools. */
export const DEMO = {
  key: 'TOOLS-3',
  title: 'Data platform build',
  northwind: 'Northwind Data Ltd',
  tessellate: 'Tessellate Software',
  quillfield: 'Quillfield Systems',
  rejection: 'No insurance certificate provided.',
} as const

/** A tiny macro-enabled Word file (vbaProject.bin inside): refused 415 macro_document. */
export const MACRO_DOCM = Buffer.from(
  'UEsDBBQAAAAIAKCNTV0k852C1AAAADUBAAATAAAAW0NvbnRlbnRfVHlwZXNdLnhtbIWQwU7EMAxEfyXKFTUpHBBCbfcAyxH2' +
    'sHyAm7jdQONEibcsf4/LSlw52uN5M3K3u8RFrVhqSNTrW9NqheSSDzT3+v340jzo3dAdvzNWJadUe31izo/WVnfCCNWkjCTK' +
    'lEoElrHMNoP7hBntXdveW5eIkbjhjaGH7hknOC+s9hdZX2PHQFo9Xe+2qF5DzktwwCLblbyJtUnTFByadYRDSR/oWNuhe5Pq' +
    'JXhUByj8ClGs9isVb31y5yg4I9X+Z28W82eJ4EraE4wLigqBbjaIpNnfPww/UEsDBBQAAAAIAKCNTV3cRTrRdgAAAJwAAAAR' +
    'AAAAd29yZC9kb2N1bWVudC54bWxFzsENwjAMBdBVqg6AKw4copANGCIkpq1Ux5FtlLI9TTlweV9flqXvm8uc3oTFhp22oq7d' +
    'x8WsOgBNC1LUC1csx+3FQtGOKjM0llyFE6quZaYNrtN0A4prGYNv7sn507N2pGPhEZPwYKjmofeunNbT3w/894QvUEsDBBQA' +
    'AAAIAKCNTV3X11jaKQAAACcAAAATAAAAd29yZC92YmFQcm9qZWN0LmJpbrtwXvCBQl5+iUKiQlFqYo5CmJOjQkFRflZqcomC' +
    'RlJmim5xbn52qiYAUEsBAhQDFAAAAAgAoI1NXSTznYLUAAAANQEAABMAAAAAAAAAAAAAAIABAAAAAFtDb250ZW50X1R5cGVz' +
    'XS54bWxQSwECFAMUAAAACACgjU1d3EU60XYAAACcAAAAEQAAAAAAAAAAAAAAgAEFAQAAd29yZC9kb2N1bWVudC54bWxQSwEC' +
    'FAMUAAAACACgjU1d19dY2ikAAAAnAAAAEwAAAAAAAAAAAAAAgAGqAQAAd29yZC92YmFQcm9qZWN0LmJpblBLBQYAAAAAAwAD' +
    'AMEAAAAEAgAAAAA=',
  'base64',
)
/** A Windows executable's first bytes ("MZ"): no allowed type, 415. */
export const EXECUTABLE = Buffer.from([0x4d, 0x5a, 0x90, 0x00, 0x03, 0x00, 0x00, 0x00, 0x04, 0x00])

/** A small plain-text document whose text the worker reads back as is. */
export function textDocument(text: string): Buffer {
  return Buffer.from(text, 'utf8')
}

const callPath = (key: string) => `/ideas/${key}/bid-call`

/**
 * A private project of its own (alice its admin) with `members`, and an idea in Proposal
 * with a proposal (owned by `owner`, default alice): ready for a call for bids.
 */
export async function bidTeam(
  alice: Api,
  name: string,
  members: Partial<Record<Person, ProjectRole>>,
  owner: Person = 'alice',
): Promise<{ project: Project; idea: IdeaDetail }> {
  const project = await createTeamProject(alice, name, members)
  const created = await alice.createIdea(project.slug, {
    title: `${name} ${project.key}`,
    summary: 'A call for bids in an e2e project of its own (e2e/tests/support/bids.ts).',
  })
  if (owner !== 'alice') await alice.setOwner(created.key, owner)
  await alice.changeStatus(created.key, 'shortlisted')
  await alice.startProposal(created.key)
  return { project, idea: await alice.idea(created.key) }
}

export function bidCall(api: Api, key: string): Promise<BidCallView> {
  return api.get(callPath(key))
}

export function startCall(
  api: Api,
  key: string,
  title: string,
  description = '',
): Promise<BidCallView> {
  return api.send('POST', callPath(key), { title, description, currency: 'GBP' }, 201)
}

/** Sets a deadline `days` from now (when none) and opens the call. */
export async function openCall(api: Api, key: string, days = 7): Promise<BidCallView> {
  const view = await bidCall(api, key)
  const call = view.call
  if (!call) throw new Error(`${key} has no call`)
  if (!call.deadline_at) {
    await api.send('PUT', callPath(key), {
      title: call.title,
      description: call.description,
      currency: call.currency,
      deadline_at: daysFromNow(days),
      ai_assessor_id: call.ai_assessor?.id ?? null,
    })
  }
  return api.send('POST', `${callPath(key)}/status`, { status: 'open' })
}

export function closeToBids(api: Api, key: string): Promise<BidCallView> {
  return api.send('POST', `${callPath(key)}/status`, { status: 'assessing' })
}

export function enterBid(
  api: Api,
  key: string,
  body: {
    bidder: string
    price?: string
    contact_name?: string
    contact_email?: string
    notes?: string
  },
): Promise<Bid> {
  return api.send('POST', `${callPath(key)}/bids`, body, 201)
}

export function bid(api: Api, key: string, bidId: string): Promise<BidDetail> {
  return api.get(`${callPath(key)}/bids/${bidId}`)
}

/** Uploads `bytes` as the raw body (`application/octet-stream`, as the SPA sends it). */
export async function uploadDocument(
  api: Api,
  key: string,
  bidId: string,
  filename: string,
  bytes: Buffer,
  options: { mustHaveId?: string; pricing?: boolean } = {},
) {
  const query = new URLSearchParams({ filename })
  if (options.mustHaveId) query.set('must_have_id', options.mustHaveId)
  if (options.pricing !== undefined) query.set('pricing', String(options.pricing))
  return api.rawBody(
    `${callPath(key)}/bids/${bidId}/documents?${query.toString()}`,
    bytes,
    'application/octet-stream',
  )
}

/** Waits until the worker has read every document of the bid (none `pending`). */
export async function waitExtracted(api: Api, key: string, bidId: string): Promise<BidDetail> {
  let detail = await bid(api, key, bidId)
  await expect
    .poll(
      async () => {
        detail = await bid(api, key, bidId)
        return detail.documents.filter((document) => document.extraction.state === 'pending').length
      },
      { timeout: 60_000, intervals: [500, 1000, 2000] },
    )
    .toBe(0)
  return detail
}

export function mustHaveId(call: BidCall, text: string): string {
  const found = call.template.must_haves.find((mustHave) => mustHave.text === text)
  if (!found) throw new Error(`no must-have "${text}"`)
  return found.id
}

export function section(call: BidCall, title: string): BidCallSection {
  const found = call.template.sections.find((candidate) => candidate.title === title)
  if (!found) throw new Error(`no section "${title}"`)
  return found
}

export function decideMustHave(
  api: Api,
  key: string,
  bidId: string,
  id: string,
  result: 'met' | 'not_met' | null,
  note = '',
) {
  return api.send('PUT', `${callPath(key)}/bids/${bidId}/must-haves/${id}`, { result, note })
}

export function rejectBid(api: Api, key: string, bidId: string, reason: string) {
  return api.send<BidDetail>('PUT', `${callPath(key)}/bids/${bidId}/rejection`, { reason })
}

/**
 * Enters a complete bid: the three required documents (form of tender, pricing schedule,
 * insurance certificate; text files naming the bidder) linked to their must-haves and the
 * terms confirmed, so it is qualified. `missing` leaves those documents out (flagged).
 */
export async function completeBid(
  api: Api,
  key: string,
  call: BidCall,
  bidder: string,
  price: string,
  missing: (keyof typeof MUST_HAVES)[] = [],
): Promise<Bid> {
  const created = await enterBid(api, key, { bidder, price, contact_name: 'Sam Example' })
  const documents: [keyof typeof MUST_HAVES, string, string][] = [
    [
      'tender',
      'form-of-tender.txt',
      `Form of tender. ${bidder} offers to supply and build the service described in the ` +
        'invitation, for the total price set out in our pricing schedule. We accept the ' +
        "buyer's standard terms and conditions without amendment.",
    ],
    ['pricing', 'pricing-schedule.csv', `item,amount\nBuild,${price}\nTotal,${price}\n`],
    [
      'insurance',
      'insurance-certificate.txt',
      `Certificate of insurance. ${bidder} holds professional indemnity insurance of five ` +
        'million pounds and public liability insurance of ten million pounds.',
    ],
  ]
  for (const [kind, filename, text] of documents) {
    if (missing.includes(kind)) continue
    const response = await uploadDocument(api, key, created.id, filename, textDocument(text), {
      mustHaveId: mustHaveId(call, MUST_HAVES[kind]),
    })
    expect(response.status(), await response.text()).toBe(201)
  }
  if (!missing.includes('terms')) {
    await decideMustHave(api, key, created.id, mustHaveId(call, MUST_HAVES.terms), 'met')
  }
  return created
}

/** Sets every section's assessors (titles to people; sections left out: nobody). */
export async function setAssessors(
  api: Api,
  key: string,
  call: BidCall,
  bySection: Record<string, Person[]>,
  dueAt: string | null = daysFromNow(5),
): Promise<BidCallView> {
  const sections = await Promise.all(
    call.template.sections.map(async (candidate) => ({
      section_id: candidate.id,
      user_ids: await Promise.all(
        (bySection[candidate.title] ?? []).map(
          async (person) => (await userOf(api.baseURL, person)).id,
        ),
      ),
    })),
  )
  return api.send('PUT', `${callPath(key)}/assessors`, { sections, due_at: dueAt })
}

/**
 * Saves `person`'s assessment of `title` for a bid: `scores` in the order of the section's
 * score questions; comment questions get a short comment. `submit` (default) submits it.
 */
export async function assess(
  api: Api,
  key: string,
  call: BidCall,
  bidId: string,
  title: string,
  scores: number[],
  submit = true,
): Promise<MyBidAssessment> {
  const target = section(call, title)
  const scored = target.questions.filter((question) => question.type === 'score')
  const answers = target.questions.flatMap((question): Record<string, unknown>[] => {
    if (question.type === 'score') {
      return [{ question_id: question.id, score: scores[scored.indexOf(question)] ?? null }]
    }
    if (question.type === 'comment') return [{ question_id: question.id, comment: 'e2e comment' }]
    return []
  })
  return api.send('PUT', `${callPath(key)}/bids/${bidId}/sections/${target.id}/assessment`, {
    answers,
    submit,
  })
}

export function comparison(api: Api, key: string): Promise<BidComparison> {
  return api.get(`${callPath(key)}/comparison`)
}

/** The project's default bid evaluation template (Project settings → Bids). */
export function bidTemplate(api: Api, slug: string): Promise<BidTemplate> {
  return api.get(`/projects/${slug}/bid-template`)
}

/**
 * A whole call ready to assess, in a project of its own: alice manages; `assessors` by
 * section title; two qualified bids (Northwind 120,000, Tessellate 96,000) and, when
 * `flagged`, a third without its insurance certificate (Quillfield 84,000; not rejected).
 * The call is open, or `assessing` once closed to new bids.
 */
export async function assessingCall(
  alice: Api,
  name: string,
  members: Partial<Record<Person, ProjectRole>>,
  assessors: Record<string, Person[]>,
  options: { flagged?: boolean; close?: boolean } = {},
) {
  const team = await bidTeam(alice, name, members)
  const key = team.idea.key
  await startCall(alice, key, `${name} supply`, 'Build and run the service for a year.')
  const opened = await openCall(alice, key)
  const call = opened.call as BidCall
  const northwind = await completeBid(alice, key, call, 'Northwind Data Ltd', '120000.00')
  const tessellate = await completeBid(alice, key, call, 'Tessellate Software', '96000.00')
  const quillfield = options.flagged
    ? await completeBid(alice, key, call, 'Quillfield Systems', '84000.00', ['insurance'])
    : undefined
  await setAssessors(alice, key, call, assessors)
  const final = options.close === false ? await bidCall(alice, key) : await closeToBids(alice, key)
  return { ...team, key, call: final.call as BidCall, northwind, tessellate, quillfield }
}
