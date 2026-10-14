import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from 'vitest'

import { api } from '@/api/client'
import { ApiError } from '@/api/errors'
import { getDb, resetDb, USERS } from '@/mocks/db'
import { PHASE10 } from '@/mocks/phase10-fixtures'
import { server } from '@/mocks/server'
import { endSession } from '@/mocks/session'

/*
 * Phase 10 in the mock (contract-phase10, role matrix table M and section 3a), over the
 * fixtures: CUST-3's call being assessed (Alice owns it; Bob and Carol on Technical, Dave
 * on Commercial with the price, Farid and Priya on Delivery), TOOL-4's open call with a
 * flagged bid, TOOL-11's draft, CUST-10's award and CUST-12's cancelled call.
 */

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
beforeEach(() => {
  resetDb()
  localStorage.setItem('soundings-mock-latency', 'none')
})
afterEach(() => {
  server.resetHandlers()
  endSession()
})
afterAll(() => server.close())

async function signIn(userId: string) {
  await api.POST('/api/v1/auth/dev/login', { body: { user_id: userId } })
}

async function rejection(promise: Promise<unknown>): Promise<ApiError> {
  try {
    await promise
  } catch (error) {
    if (error instanceof ApiError) return error
    throw error
  }
  throw new Error('expected the request to fail')
}

const ideaPath = (key: string) => ({ params: { path: { idea: key } } })
const bidPath = (key: string, bidId: string) => ({ params: { path: { idea: key, bid_id: bidId } } })

async function callOf(key: string) {
  const { data } = await api.GET('/api/v1/ideas/{idea}/bid-call', ideaPath(key))
  if (!data) throw new Error('no view')
  return data
}

async function sectionId(key: string, title: string): Promise<string> {
  await signIn(USERS.alice)
  const view = await callOf(key)
  const section = view.call?.template.sections.find((s) => s.title === title)
  if (!section) throw new Error(`no section ${title}`)
  return section.id
}

describe('who sees what (table M)', () => {
  it('shows members, viewers and internal non-members only that a call exists', async () => {
    for (const user of [USERS.hannah, USERS.emma, USERS.ivan]) {
      await signIn(user)
      const view = await callOf('CUST-3')
      expect(view.summary).toMatchObject({
        title: 'Fulfilment partner for subscription boxes',
        status: 'assessing',
        bid_count: 3,
      })
      expect(view.call).toBeNull()
      expect(view.permissions).toMatchObject({ can_view_bids: false, can_view_scores: false })
      expect(
        (await rejection(api.GET('/api/v1/ideas/{idea}/bid-call/bids', ideaPath('CUST-3')))).status,
      ).toBe(403)
      // The same 403 for a real and an unknown bid id (the call-level rule first).
      const real = await rejection(
        api.GET(
          '/api/v1/ideas/{idea}/bid-call/bids/{bid_id}',
          bidPath('CUST-3', PHASE10.northwind),
        ),
      )
      const unknown = await rejection(
        api.GET(
          '/api/v1/ideas/{idea}/bid-call/bids/{bid_id}',
          bidPath('CUST-3', '00000000-0000-4000-8000-000000000000'),
        ),
      )
      expect([real.status, unknown.status]).toEqual([403, 403])
      const detail = await api.GET('/api/v1/ideas/{idea}', ideaPath('CUST-3'))
      expect(detail.data?.bid_call?.bid_count).toBe(3)
      expect(detail.data?.permissions.can_view_bid_call).toBe(true)
    }
  })

  it('hides every bid route from a guest researcher (404) and their idea has no call', async () => {
    const db = getDb()
    const tool4 = db.ideas.find(
      (i) => i.id === db.bid.calls.find((c) => c.id === PHASE10.tool4Call)?.idea_id,
    )
    if (!tool4) throw new Error('TOOL-4 missing')
    tool4.researcher_id = USERS.ivan
    await signIn(USERS.ivan)
    const detail = await api.GET('/api/v1/ideas/{idea}', ideaPath('TOOL-4'))
    expect(detail.data?.bid_call).toBeNull()
    expect(detail.data?.permissions).toMatchObject({
      can_view_bid_call: false,
      can_create_bid_call: false,
    })
    expect(
      (await rejection(api.GET('/api/v1/ideas/{idea}/bid-call', ideaPath('TOOL-4')))).status,
    ).toBe(404)
    expect(
      (await rejection(api.GET('/api/v1/ideas/{idea}/bid-call/bids', ideaPath('TOOL-4')))).status,
    ).toBe(404)
    const feed = await api.GET('/api/v1/ideas/{idea}/activity', ideaPath('TOOL-4'))
    expect(feed.data?.items.some((item) => item.type === 'bid_call_changed')).toBe(false)
  })

  it('shows an assessor the bids that aren’t rejected, without contacts, notes or prices', async () => {
    await signIn(USERS.bob)
    const { data } = await api.GET('/api/v1/ideas/{idea}/bid-call/bids', ideaPath('CUST-3'))
    expect(data?.items.map((bid) => bid.bidder)).toEqual([
      'Northwind Fulfilment Ltd',
      'Tessellate Logistics',
    ])
    expect(data?.items[0]).toMatchObject({
      contact_name: '',
      contact_email: null,
      notes: '',
      price: null,
      price_hidden: true,
      rejection: null,
      restricted_document_count: 1,
    })
    expect(
      (
        await rejection(
          api.GET(
            '/api/v1/ideas/{idea}/bid-call/bids/{bid_id}',
            bidPath('CUST-3', PHASE10.quillfield),
          ),
        )
      ).status,
    ).toBe(404)
    // The pricing schedule: "present (restricted)", never named.
    const bid = await api.GET(
      '/api/v1/ideas/{idea}/bid-call/bids/{bid_id}',
      bidPath('CUST-3', PHASE10.northwind),
    )
    expect(bid.data?.documents.map((doc) => doc.filename)).not.toContain('Pricing schedule.xlsx')
    const pricing = bid.data?.must_have_results.find(
      (state) => state.must_have.text === 'Pricing schedule',
    )
    expect(pricing).toMatchObject({ result: 'met', document_ids: [], restricted_document_count: 1 })
  })

  it('shows the price section’s assessor the prices and the pricing documents', async () => {
    await signIn(USERS.dave)
    const { data } = await api.GET('/api/v1/ideas/{idea}/bid-call/bids', ideaPath('CUST-3'))
    expect(data?.items[0]).toMatchObject({
      price: '120000.00',
      price_hidden: false,
      restricted_document_count: 0,
    })
    const bid = await api.GET(
      '/api/v1/ideas/{idea}/bid-call/bids/{bid_id}',
      bidPath('CUST-3', PHASE10.northwind),
    )
    expect(bid.data?.documents.map((doc) => doc.filename)).toContain('Pricing schedule.xlsx')
    expect(
      (await rejection(api.GET('/api/v1/ideas/{idea}/bid-call/comparison', ideaPath('CUST-3'))))
        .status,
    ).toBe(403)
  })
})

describe('the comparison (section 8)', () => {
  it('scores, ranks and flags disagreement for a call manager who doesn’t assess', async () => {
    await signIn(USERS.alice)
    const { data } = await api.GET('/api/v1/ideas/{idea}/bid-call/comparison', ideaPath('CUST-3'))
    expect(data?.ranking_hidden).toBe(false)
    expect(data?.lowest_price).toBe('96000.00')
    const rows = data?.rows.map((row) => [row.bid.bidder, row.rank, row.total, row.price_score])
    expect(rows).toEqual([
      ['Northwind Fulfilment Ltd', 1, 87.3, 4],
      ['Tessellate Logistics', 2, 71.2, 5],
      ['Quillfield Packaging', null, null, null],
    ])
    const tessellate = data?.rows[1]
    expect(tessellate?.sections.map((cell) => [cell.score, cell.disagreement])).toEqual([
      [60, true],
      [88, false],
      [60, false],
    ])
    expect(data?.progress).toEqual({ submitted: 8, total: 10 })
  })

  it('hides a pending assessor’s cells and every rank (Priya owes Tessellate’s Delivery)', async () => {
    await signIn(USERS.priya)
    const { data } = await api.GET('/api/v1/ideas/{idea}/bid-call/comparison', ideaPath('CUST-3'))
    expect(data?.ranking_hidden).toBe(true)
    expect(data?.rows.every((row) => row.rank === null)).toBe(true)
    const tessellate = data?.rows.find((row) => row.bid.bidder === 'Tessellate Logistics')
    expect(tessellate).toMatchObject({ total: null, total_hidden: true })
    expect(tessellate?.sections.at(-1)).toMatchObject({ hidden: true, score: null })
  })

  it('counts an AI assessment only once it is included', async () => {
    await signIn(USERS.alice)
    const before = await api.GET('/api/v1/ideas/{idea}/bid-call/comparison', ideaPath('CUST-3'))
    expect(
      before.data?.rows.find((r) => r.bid.bidder === 'Tessellate Logistics')?.ai_included,
    ).toBe(false)
    const ai = await api.GET(
      '/api/v1/ideas/{idea}/bid-call/bids/{bid_id}/ai-assessments',
      bidPath('CUST-3', PHASE10.tessellate),
    )
    expect(ai.data?.items[0]?.quotes_not_found).toBe(1)
    await api.PUT(
      '/api/v1/ideas/{idea}/bid-call/bids/{bid_id}/ai-assessments/{ai_assessment_id}/include-in-totals',
      {
        params: {
          path: {
            idea: 'CUST-3',
            bid_id: PHASE10.tessellate,
            ai_assessment_id: PHASE10.tessellateAi,
          },
        },
        body: { include: true },
      },
    )
    const after = await api.GET('/api/v1/ideas/{idea}/bid-call/comparison', ideaPath('CUST-3'))
    const row = after.data?.rows.find((r) => r.bid.bidder === 'Tessellate Logistics')
    expect(row?.ai_included).toBe(true)
    expect(row?.total).not.toBe(71.2)
  })
})

describe('blind assessment (section 3a)', () => {
  it('shows nothing of a section until you submit it for that bid', async () => {
    const technical = await sectionId('CUST-3', 'Technical')
    await signIn(USERS.bob)
    const path = {
      params: { path: { idea: 'CUST-3', bid_id: PHASE10.northwind, section_id: technical } },
    }
    const hidden = await api.GET(
      '/api/v1/ideas/{idea}/bid-call/bids/{bid_id}/sections/{section_id}/assessments',
      path,
    )
    expect(hidden.data).toMatchObject({
      hidden: true,
      assessments: [],
      ai: [],
      questions: [],
      section_score: null,
    })
    const mine = await api.GET(
      '/api/v1/ideas/{idea}/bid-call/bids/{bid_id}/sections/{section_id}/assessment',
      path,
    )
    expect(mine.data?.state).toBe('draft')
    const questions = await technicalQuestions()
    const submitted = await api.PUT(
      '/api/v1/ideas/{idea}/bid-call/bids/{bid_id}/sections/{section_id}/assessment',
      {
        ...path,
        body: {
          answers: questions.map((q) => ({
            question_id: q.id,
            score: q.type === 'score' ? 4 : null,
            comment: '',
          })),
          submit: true,
        },
      },
    )
    expect(submitted.data?.state).toBe('submitted')
    const open = await api.GET(
      '/api/v1/ideas/{idea}/bid-call/bids/{bid_id}/sections/{section_id}/assessments',
      path,
    )
    expect(open.data?.hidden).toBe(false)
    expect(open.data?.assessments.map((a) => a.assessor.display_name)).toEqual([
      'Bob Chen',
      'Carol Díaz',
    ])
  })

  it('refuses another section’s assessment (not_section_assessor) and removing yourself while you owe it', async () => {
    const commercial = await sectionId('CUST-3', 'Commercial')
    await signIn(USERS.bob)
    const error = await rejection(
      api.GET('/api/v1/ideas/{idea}/bid-call/bids/{bid_id}/sections/{section_id}/assessment', {
        params: { path: { idea: 'CUST-3', bid_id: PHASE10.northwind, section_id: commercial } },
      }),
    )
    expect(error).toMatchObject({ status: 403, code: 'not_section_assessor' })
    await signIn(USERS.priya)
    const view = await callOf('CUST-3')
    const sections = (view.call?.template.sections ?? []).map((section) => ({
      section_id: section.id,
      user_ids: section.assessors
        .map((a) => a.user.id)
        .filter((id) => section.title !== 'Delivery' || id !== USERS.priya),
    }))
    const self = await rejection(
      api.PUT('/api/v1/ideas/{idea}/bid-call/assessors', {
        ...ideaPath('CUST-3'),
        body: { sections, due_at: null },
      }),
    )
    expect(self).toMatchObject({ status: 403, code: 'cannot_remove_self' })
  })
})

describe('bids, must-haves and documents', () => {
  it('flags a missing document, suggests rejecting, and keeps the reason after reinstating', async () => {
    await signIn(USERS.alice)
    const kestrel = await api.GET(
      '/api/v1/ideas/{idea}/bid-call/bids/{bid_id}',
      bidPath('TOOL-4', PHASE10.kestrel),
    )
    expect(kestrel.data?.status).toBe('received')
    expect(kestrel.data?.must_haves).toMatchObject({ missing: 1, unchecked: 1 })
    expect(kestrel.data?.permissions).toMatchObject({ reject_suggested: true, can_reject: true })
    await api.PUT('/api/v1/ideas/{idea}/bid-call/bids/{bid_id}/rejection', {
      ...bidPath('TOOL-4', PHASE10.kestrel),
      body: { reason: 'No insurance certificate.' },
    })
    const back = await api.DELETE(
      '/api/v1/ideas/{idea}/bid-call/bids/{bid_id}/rejection',
      bidPath('TOOL-4', PHASE10.kestrel),
    )
    expect(back.data?.rejection).toMatchObject({ reason: 'No insurance certificate.' })
    expect(back.data?.rejection?.reinstated_at).not.toBeNull()
  })

  it('takes uploads by their bytes, refuses macros and duplicates', async () => {
    await signIn(USERS.alice)
    const upload = (name: string, body: BodyInit) =>
      fetch(
        `/api/v1/ideas/TOOL-4/bid-call/bids/${PHASE10.kestrel}/documents?filename=${encodeURIComponent(name)}`,
        {
          method: 'POST',
          body,
          headers: { 'Content-Type': 'application/octet-stream', 'X-CSRF-Token': csrf() },
        },
      )
    const ok = await upload('Insurance', '%PDF-1.7 insurance certificate')
    expect(ok.status).toBe(201)
    expect(await ok.json()).toMatchObject({
      filename: 'Insurance.pdf',
      type: 'pdf',
      extraction: { state: 'pending' },
    })
    expect((await upload('Insurance again.pdf', '%PDF-1.7 insurance certificate')).status).toBe(409)
    const macro = await upload(
      'Plan.docx',
      new Uint8Array([0x50, 0x4b, 0x03, 0x04, ...new TextEncoder().encode('word/vbaProject.bin')]),
    )
    expect(macro.status).toBe(415)
    expect((await macro.json()) as { code: string }).toMatchObject({ code: 'macro_document' })
    expect((await upload('../evil.pdf', '%PDF-1.7')).status).toBe(422)
  })

  it('takes the file name from X-Filename, percent-encoded, before the query', async () => {
    await signIn(USERS.alice)
    const upload = (header: string) =>
      fetch(`/api/v1/ideas/TOOL-4/bid-call/bids/${PHASE10.kestrel}/documents`, {
        method: 'POST',
        body: `%PDF-1.7 ${header}`,
        headers: {
          'Content-Type': 'application/octet-stream',
          'X-CSRF-Token': csrf(),
          'X-Filename': header,
        },
      })
    const ok = await upload(encodeURIComponent('Méthode – plan.pdf'))
    expect(ok.status).toBe(201)
    expect(await ok.json()).toMatchObject({ filename: 'Méthode – plan.pdf' })
    const broken = await upload('%E9.pdf')
    expect(broken.status).toBe(422)
    expect(await broken.json()).toMatchObject({ errors: [{ loc: ['header', 'X-Filename'] }] })
    const folder = await upload(encodeURIComponent('../evil.pdf'))
    expect(folder.status).toBe(422)
  })

  it('enters bids only while the call is open', async () => {
    await signIn(USERS.alice)
    const error = await rejection(
      api.POST('/api/v1/ideas/{idea}/bid-call/bids', {
        ...ideaPath('CUST-3'),
        body: { bidder: 'Late Ltd', contact_name: '', notes: '' },
      }),
    )
    expect(error).toMatchObject({ status: 409, code: 'bid_call_not_open' })
    const created = await api.POST('/api/v1/ideas/{idea}/bid-call/bids', {
      ...ideaPath('TOOL-4'),
      body: { bidder: 'Arrow Labs', contact_name: '', notes: '', price: '39000' },
    })
    expect(created.data).toMatchObject({
      bidder: 'Arrow Labs',
      price: '39000.00',
      status: 'received',
    })
  })
})

describe('the lifecycle (section 3.2)', () => {
  it('opens a draft only with a deadline, and reopens only before any submission', async () => {
    await signIn(USERS.alice)
    const draft = await rejection(
      api.POST('/api/v1/ideas/{idea}/bid-call/status', {
        ...ideaPath('TOOL-11'),
        body: { status: 'open' },
      }),
    )
    expect(draft).toMatchObject({ code: 'bid_call_deadline_required' })
    const reopen = await rejection(
      api.POST('/api/v1/ideas/{idea}/bid-call/status', {
        ...ideaPath('CUST-3'),
        body: { status: 'open' },
      }),
    )
    expect(reopen).toMatchObject({ code: 'assessments_submitted' })
    await signIn(USERS.priya) // a platform admin: a manager of CUST-10's awarded call
    const finished = await rejection(
      api.POST('/api/v1/ideas/{idea}/bid-call/bids', {
        ...ideaPath('CUST-10'),
        body: { bidder: 'X', contact_name: '', notes: '' },
      }),
    )
    // CUST-10 is closed (409 idea_closed comes before the call's own state).
    expect(finished.status).toBe(409)
  })

  it('locks the template copy once a person has submitted', async () => {
    await signIn(USERS.alice)
    const view = await callOf('CUST-3')
    expect(view.call?.template.locked).toBe(true)
    expect(view.permissions.can_edit_template).toBe(false)
    const draft = await callOf('TOOL-11')
    expect(draft.permissions.can_edit_template).toBe(true)
  })

  it('starts a call only on an idea in Proposal with a proposal', async () => {
    await signIn(USERS.emma) // GREEN-4: in Proposal, no proposal yet
    const before = await callOf('GREEN-4')
    expect(before.permissions.can_create).toBe(false)
    await api.POST('/api/v1/ideas/{idea}/proposal', ideaPath('GREEN-4'))
    const after = await callOf('GREEN-4')
    expect(after.permissions.can_create).toBe(true)
    const created = await api.POST('/api/v1/ideas/{idea}/bid-call', {
      ...ideaPath('GREEN-4'),
      body: { title: 'Paperless invoicing: supplier', description: '', currency: 'GBP' },
    })
    expect(created.data?.call?.template.sections.map((s) => s.title)).toEqual([
      'Technical',
      'Commercial',
      'Delivery',
    ])
    expect(created.data?.call?.status).toBe('draft')
  })
})

describe('My work', () => {
  it('lists the calls you owe assessments for, with counts', async () => {
    await signIn(USERS.bob)
    const work = await api.GET('/api/v1/me/work')
    expect(
      work.data?.bids_to_assess.map((row) => [row.call.title, row.progress, row.sections.length]),
    ).toEqual([['Fulfilment partner for subscription boxes', { submitted: 1, total: 2 }, 1]])
    const counts = await api.GET('/api/v1/me/work/counts')
    expect(counts.data?.bid_assessments_due).toBe(1)
  })
})

async function technicalQuestions() {
  const view = await callOf('CUST-3')
  return view.call?.template.sections.find((s) => s.title === 'Technical')?.questions ?? []
}

function csrf(): string {
  return /soundings_csrf=([^;]+)/.exec(document.cookie)?.[1] ?? ''
}
