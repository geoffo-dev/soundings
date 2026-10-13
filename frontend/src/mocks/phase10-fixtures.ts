/**
 * Phase 10 fixtures (contract-phase10 §17, adapted to the mock's people): a call for
 * bids in every state.
 *
 * - **CUST-3** ("Subscription boxes for repeat buyers", owner **Alice**, Customer
 *   Innovation is internal): call **"Fulfilment partner for subscription boxes"**,
 *   **assessing**, deadline passed, assessments due in 4 days, the default template
 *   (Technical 40 / Commercial 40 with the price / Delivery 20, four must-haves).
 *   Technical: **Bob** (submitted Tessellate; a **draft** on Northwind: he still owes
 *   it, so it's blind for him) and **Carol** (submitted both); Commercial (the price):
 *   **Dave** (both; he opens the pricing schedules); Delivery: **Farid** (both) and
 *   **Priya** (a platform admin, so a call manager who assesses too: she owes
 *   Tessellate, so her comparison has no ranks). Bids:
 *   **Northwind Fulfilment Ltd** (complete and strong, 120,000.00),
 *   **Tessellate Logistics** (complete, cheaper at 96,000.00, weaker technically:
 *   Carol 4 and Bob 2 on its first question disagree; an AI assessment from the
 *   **Bid assessor** left out of the totals, one of its quotes not found in the
 *   document) and **Quillfield Packaging** (no insurance certificate: flagged,
 *   **rejected** by Alice with "No insurance certificate provided."). Alice sees the
 *   whole comparison with ranks; **Hannah** (member), **Emma** (viewer) and **Ivan**
 *   (no role; the project is internal) see only that a call exists.
 * - **TOOL-4** ("Self-service feature flags", owner Bob; Alice is a TOOL admin):
 *   **open** call "Feature flag service: build partner", deadline in 5 days, the Bid
 *   assessor named as its AI assessor. **Brightline Software** (complete; its terms
 *   confirmed by Alice; one document still being read) and **Kestrel Code Co**
 *   (**flagged**: no insurance certificate, its terms unchecked and the AI's automatic
 *   pre-check found them not met; a brochure with active content and an encrypted scan).
 * - **TOOL-11** ("Release notes generator", owner Alice, moved back to Shortlisted after
 *   its call was started: a **draft** call with no deadline yet.
 * - **CUST-10** (closed, owner Farid): an **awarded** call (Lockwise Systems awarded,
 *   Parcelhub Retail unsuccessful).
 * - **CUST-12** (closed, owner Alice): a **cancelled** call ("The idea was parked.").
 * - **GREEN-4** (Proposal, owner Emma, no proposal yet): no call; once Emma starts
 *   its proposal she may start one.
 */
import type { AiRunEventType } from '@/api/types'

import type { MockAiAgent, MockAiRun, MockAiRunEvent } from './ai'
import { agentKeyScopes } from './ai'
import {
  defaultBidTemplate,
  type MockBid,
  type MockBidCall,
  type MockBidDocument,
  type MockBidQuestion,
  type MockBidSection,
} from './bids'
import {
  mockId,
  type MockDb,
  type MockIdea,
  type PROJECTS as ProjectsMap,
  type USERS as UsersMap,
} from './db'

type Users = typeof UsersMap
type Projects = typeof ProjectsMap

const MINUTE = 60_000
const HOUR = 60 * MINUTE
const DAY = 24 * HOUR

const id = (n: number) => mockId('f', 0x1000 + n)

/** Fixture ids tests use. */
export const PHASE10 = {
  assessorUser: id(1),
  assessorAgent: id(2),
  assessorKey: id(3),
  cust3Call: id(10),
  tool4Call: id(11),
  tool11Call: id(12),
  cust10Call: id(13),
  cust12Call: id(14),
  northwind: id(20),
  tessellate: id(21),
  quillfield: id(22),
  brightline: id(23),
  kestrel: id(24),
  lockwise: id(25),
  parcelhub: id(26),
  tessellateAi: id(30),
  kestrelAi: id(31),
  kestrelRun: id(32),
} as const

/** Text the fake extraction "read" from each fixture document. */
const TEXT = {
  northwindTender: [
    'FORM OF TENDER',
    'Northwind Fulfilment Ltd offers to pack and deliver subscription boxes for repeat buyers for a contract term of three years.',
    'We accept your standard terms and conditions without amendment.',
    'Signed for and on behalf of Northwind Fulfilment Ltd by its managing director.',
  ].join('\n\n'),
  northwindProposal: [
    'Our solution',
    'We run two fulfilment centres with automated box erection and pick-to-light stations, so a monthly run of 40,000 boxes is packed within 48 hours of the cut-off.',
    'Every box is tracked from packing to doorstep, and customers can skip, pause or change a box until the cut-off.',
    'Security and data',
    'Customer addresses are held in the UK, encrypted at rest, and only the dispatch team can read them. We are ISO 27001 certified and audited every year.',
    'Delivery plan',
    'Weeks 1 to 4: integration with your order system; weeks 5 to 8: a pilot of 2,000 boxes; from week 9: full volume.',
    'The account team is led by Ada Price, who ran the meal-kit programme for Greenleaf Foods.',
  ].join('\n\n'),
  northwindInsurance:
    'CERTIFICATE OF INSURANCE. Public liability cover of 10,000,000 GBP and employers liability cover of 5,000,000 GBP, valid until 31 March 2027.',
  northwindPricing:
    'Pricing schedule\nPacking per box,1.85\nDelivery per box,2.40\nTotal for three years,120000.00',
  tessellateTender: [
    'FORM OF TENDER',
    'Tessellate Logistics offers to fulfil subscription boxes from its Midlands warehouse.',
    'We accept the standard terms, with a request to agree the liability cap at contract signature.',
  ].join('\n\n'),
  tessellateProposal: [
    'Approach',
    'Boxes are packed by hand on two shifts; we would add a third shift for the first monthly run and review it after three months.',
    'Tracking is shared with customers by email at dispatch.',
    'Data protection',
    'Addresses are stored in our warehouse system, which is backed up nightly. We follow Cyber Essentials and are working towards ISO 27001.',
    'Timeline',
    'We can start packing within six weeks of signature, after a two-week trial with 500 boxes.',
  ].join('\n\n'),
  tessellatePricing:
    'Item,Price\nPacking and delivery per box,3.20\nTotal for three years,96000.00',
  quillfieldTender:
    'FORM OF TENDER. Quillfield Packaging offers eco-friendly boxes and fulfilment for the full term. We accept your standard terms.',
  quillfieldPricing: 'Item,Price\nTotal for three years,80000.00',
  brightlineTender: [
    'FORM OF TENDER',
    'Brightline Software offers to build and run a self-service feature flag service for the internal tools team.',
    'We accept your standard terms and conditions.',
  ].join('\n\n'),
  brightlineInsurance:
    'CERTIFICATE OF INSURANCE. Professional indemnity cover of 2,000,000 GBP, valid until 30 June 2027.',
  brightlinePricing: 'Item,Price\nBuild,32000.00\nSupport for two years,16500.00\nTotal,48500.00',
  kestrelTender: [
    'FORM OF TENDER',
    'Kestrel Code Co offers a feature flag service built on open-source components.',
    'Our terms of business are attached and apply to this offer.',
  ].join('\n\n'),
  kestrelPricing: 'Item,Price\nTotal,41000.00',
  kestrelBrochure:
    'Kestrel Code Co. We build developer tools for fast-moving teams. Ask us about our launch offer.',
  lockwiseTender:
    'FORM OF TENDER. Lockwise Systems offers 40 pickup lockers installed in 10 stores, with remote monitoring. We accept your standard terms.',
  parcelhubTender:
    'FORM OF TENDER. Parcelhub Retail offers staffed pickup desks in 10 stores. We accept your standard terms.',
}

function bytesOf(text: string): Uint8Array {
  return new TextEncoder().encode(text)
}

/** A short pseudo SHA-256 (hex) for fixture files (64 hex digits, unique per text). */
function fakeSha(text: string): string {
  let h = 0x811c9dc5
  for (let i = 0; i < text.length; i++) h = Math.imul(h ^ text.charCodeAt(i), 0x01000193) >>> 0
  return (h.toString(16).padStart(8, '0') + text.length.toString(16).padStart(8, '0')).repeat(4)
}

export function seedPhase10(
  db: MockDb,
  ctx: { users: Users; projects: Projects; nextId: (kind: number | string) => string },
): void {
  const { users, projects, nextId } = ctx
  const now = db.now
  const iso = (ms: number) => new Date(ms).toISOString()
  /** The end of the local day `days` from today (a DueAt the SPA picked). */
  const endOfDay = (days: number) => {
    const date = new Date(now)
    date.setDate(date.getDate() + days)
    date.setHours(23, 59, 0, 0)
    return date.getTime()
  }
  const idea = (key: string): MockIdea => {
    const [projectKey = '', number = ''] = key.split('-')
    const found = db.ideas.find(
      (i) =>
        db.projects.find((p) => p.id === i.project_id)?.key === projectKey &&
        i.number === Number(number),
    )
    if (!found) throw new Error(`fixture idea ${key} missing`)
    return found
  }

  /* The AI assessor agent ------------------------------------------------ */
  db.users.push({
    id: PHASE10.assessorUser,
    display_name: 'Bid assessor',
    email: `agent-${PHASE10.assessorUser}@soundings.invalid`,
    avatar_url: null,
    is_platform_admin: false,
    is_active: true,
    is_service_account: true,
    is_break_glass: false,
    created_at: iso(now - 3 * DAY),
    last_seen_at: null,
  })
  for (const projectId of [projects.cust, projects.tool]) {
    db.members.push({
      project_id: projectId,
      user_id: PHASE10.assessorUser,
      role: 'member',
      joined_at: iso(now - 3 * DAY),
    })
  }
  const agent: MockAiAgent = {
    id: PHASE10.assessorAgent,
    user_id: PHASE10.assessorUser,
    description:
      'Checks a bid’s must-haves and scores its questions with quotes from its documents.',
    namespace: 'soundings',
    name: 'bid-assessor',
    protocol: 'kagent_v0_10',
    purposes: ['assess_bid'],
    project_ids: [projects.cust, projects.tool],
    enabled: true,
    created_at: iso(now - 3 * DAY),
    updated_at: iso(now - 3 * DAY),
    created_by_id: users.priya,
  }
  db.aiAgents.push(agent)
  db.apiKeys.push({
    id: PHASE10.assessorKey,
    user_id: PHASE10.assessorUser,
    name: 'kagent soundings/bid-assessor',
    lookup_id: 'B1dAss3ss0rK',
    scopes: agentKeyScopes(agent.purposes),
    project_ids: [projects.cust, projects.tool],
    expires_at: null,
    created_at: iso(now - 3 * DAY),
    created_by_id: users.priya,
    created_auth_method: 'sso',
    last_used_at: iso(now - 20 * HOUR),
    revoked_at: null,
    revoked_by_id: null,
  })

  /* Project templates (every project gets the built-in default) ---------- */
  for (const project of db.projects) db.bid.templates.push(defaultBidTemplate(project.id))

  /* Builders ------------------------------------------------------------- */
  const makeCall = (
    callId: string,
    target: MockIdea,
    spec: Partial<MockBidCall> & { title: string; createdAgo: number; createdBy: string },
  ) => {
    const { createdAgo, createdBy, ...rest } = spec
    const call: MockBidCall = {
      id: callId,
      idea_id: target.id,
      description: '',
      currency: 'GBP',
      status: 'draft',
      deadline_at: null,
      assessment_due_at: null,
      ai_assessor_id: null,
      scale: defaultBidTemplate(target.project_id).scale,
      created_by_id: createdBy,
      created_at: iso(now - createdAgo),
      updated_at: iso(now - createdAgo + HOUR),
      awarded_at: null,
      awarded_bid_id: null,
      award_reason: null,
      cancelled_at: null,
      cancel_reason: null,
      complete_notified: false,
      ...rest,
    }
    db.bid.calls.push(call)
    // Its copy of the project's template.
    const template = defaultBidTemplate(target.project_id)
    const sections: MockBidSection[] = []
    const questions: MockBidQuestion[] = []
    template.sections.forEach((section, position) => {
      const sectionId = nextId('f')
      sections.push({
        id: sectionId,
        call_id: call.id,
        position,
        title: section.title,
        guidance: section.guidance,
        weight: section.weight,
      })
      section.questions.forEach((q, qPosition) => {
        questions.push({
          id: nextId('f'),
          call_id: call.id,
          section_id: sectionId,
          position: qPosition,
          ...q,
        })
      })
    })
    db.bid.sections.push(...sections)
    db.bid.questions.push(...questions)
    const mustHaves = template.must_haves.map((m, position) => ({
      id: nextId('f'),
      call_id: call.id,
      position,
      ...m,
    }))
    db.bid.mustHaves.push(...mustHaves)
    db.events.push({
      id: nextId(7),
      idea_id: target.id,
      actor_id: createdBy,
      type: 'bid_call_changed',
      payload: { call_id: call.id, from_status: null, to_status: 'draft' },
      comment_id: null,
      created_at: call.created_at,
    })
    const section = (title: string) => {
      const found = sections.find((s) => s.title === title)
      if (!found) throw new Error(`section ${title} missing`)
      return found
    }
    const question = (sectionTitle: string, position: number) => {
      const s = section(sectionTitle)
      const found = questions.find((q) => q.section_id === s.id && q.position === position)
      if (!found) throw new Error(`question ${sectionTitle}/${position} missing`)
      return found
    }
    const mustHave = (text: string) => {
      const found = mustHaves.find((m) => m.text === text)
      if (!found) throw new Error(`must-have ${text} missing`)
      return found
    }
    return { call, section, question, mustHave }
  }

  const moved = (
    target: MockIdea,
    call: MockBidCall,
    from: string | null,
    to: string,
    ago: number,
    actor: string,
  ) => {
    db.events.push({
      id: nextId(7),
      idea_id: target.id,
      actor_id: actor,
      type: 'bid_call_changed',
      payload: { call_id: call.id, from_status: from, to_status: to },
      comment_id: null,
      created_at: iso(now - ago),
    })
  }

  const makeBid = (
    bidId: string,
    call: MockBidCall,
    spec: Partial<MockBid> & { bidder: string; receivedAgo: number; enteredBy: string },
  ): MockBid => {
    const { receivedAgo, enteredBy, ...rest } = spec
    const bid: MockBid = {
      id: bidId,
      call_id: call.id,
      contact_name: '',
      contact_email: null,
      received_at: iso(now - receivedAgo),
      price: null,
      notes: '',
      entered_by_id: enteredBy,
      created_at: iso(now - receivedAgo + 30 * MINUTE),
      updated_at: iso(now - receivedAgo + 30 * MINUTE),
      rejection: null,
      rejected: false,
      auto_ai_run_at: null,
      ...rest,
    }
    db.bid.bids.push(bid)
    return bid
  }

  const makeDoc = (
    bid: MockBid,
    spec: {
      filename: string
      type: MockBidDocument['type']
      text: string
      mustHave?: { id: string; pricing: boolean } | null
      pricing?: boolean
      by: string
      ago: number
      state?: MockBidDocument['extraction']['state']
      error?: MockBidDocument['extraction']['error']
      active?: boolean
      size?: number
    },
  ) => {
    const bytes = bytesOf(spec.text)
    const state = spec.state ?? (spec.type === 'png' || spec.type === 'jpeg' ? 'no_text' : 'done')
    db.bid.documents.push({
      id: nextId('f'),
      bid_id: bid.id,
      filename: spec.filename,
      type: spec.type,
      size_bytes: spec.size ?? bytes.byteLength * 37,
      sha256: fakeSha(spec.filename + spec.text),
      must_have_id: spec.mustHave?.id ?? null,
      pricing: spec.pricing ?? spec.mustHave?.pricing ?? false,
      active_content: spec.active ?? false,
      uploaded_by_id: spec.by,
      uploaded_at: iso(now - spec.ago),
      bytes,
      extraction: {
        state,
        error: state === 'failed' ? (spec.error ?? 'damaged') : null,
        text: state === 'done' ? spec.text : '',
        truncated: false,
      },
    })
  }

  const assess = (
    call: MockBidCall,
    bid: MockBid,
    section: MockBidSection,
    user: string,
    scores: (number | null)[],
    opts: { draft?: boolean; ago: number; comments?: string[] },
  ) => {
    const qs = db.bid.questions
      .filter((q) => q.section_id === section.id && q.type !== 'price')
      .sort((a, b) => a.position - b.position)
    let i = 0
    const answers = qs.map((q, index) => {
      if (q.type === 'comment') {
        return { question_id: q.id, score: null, comment: opts.comments?.[index] ?? '' }
      }
      const score = scores[i] ?? null
      i += 1
      return { question_id: q.id, score, comment: opts.comments?.[index] ?? '' }
    })
    db.bid.assessments.push({
      id: nextId('f'),
      call_id: call.id,
      bid_id: bid.id,
      section_id: section.id,
      user_id: user,
      status: opts.draft ? 'draft' : 'submitted',
      answers,
      submitted_at: opts.draft ? null : iso(now - opts.ago),
      edited_at: null,
      updated_at: iso(now - opts.ago),
    })
  }

  const decide = (
    bid: MockBid,
    mustHaveId: string,
    result: 'met' | 'not_met',
    by: string,
    ago: number,
    note = '',
  ) => {
    db.bid.decisions.push({
      bid_id: bid.id,
      must_have_id: mustHaveId,
      result,
      decided_by_id: by,
      decided_at: iso(now - ago),
      note,
    })
  }

  /* CUST-3: assessing --------------------------------------------------- */
  const cust3 = idea('CUST-3')
  const main = makeCall(PHASE10.cust3Call, cust3, {
    title: 'Fulfilment partner for subscription boxes',
    description:
      'Packing and delivering the monthly subscription boxes for three years, starting with a pilot of 2,000 boxes.',
    status: 'assessing',
    deadline_at: iso(endOfDay(-6)),
    assessment_due_at: iso(endOfDay(4)),
    createdAgo: 20 * DAY,
    createdBy: users.alice,
  })
  moved(cust3, main.call, 'draft', 'open', 18 * DAY, users.alice)
  moved(cust3, main.call, 'open', 'assessing', 5 * DAY, users.alice)
  const technical = main.section('Technical')
  const commercial = main.section('Commercial')
  const delivery = main.section('Delivery')
  for (const [section, people] of [
    [technical, [users.bob, users.carol]],
    [commercial, [users.dave]],
    [delivery, [users.farid, users.priya]],
  ] as const) {
    for (const user of people) {
      db.bid.assessors.push({
        call_id: main.call.id,
        section_id: section.id,
        user_id: user,
        assigned_at: iso(now - 5 * DAY),
      })
    }
  }
  const tender = main.mustHave('Signed form of tender')
  const pricing = main.mustHave('Pricing schedule')
  const insurance = main.mustHave('Insurance certificate')
  const terms = main.mustHave('Accepts our standard terms')

  const northwind = makeBid(PHASE10.northwind, main.call, {
    bidder: 'Northwind Fulfilment Ltd',
    contact_name: 'Ada Price',
    contact_email: 'ada.price@northwind.example',
    price: '120000.00',
    notes: 'Visited their Leeds centre on 2 October: well run.',
    receivedAgo: 9 * DAY,
    enteredBy: users.alice,
  })
  makeDoc(northwind, {
    filename: 'Form of tender.pdf',
    type: 'pdf',
    text: TEXT.northwindTender,
    mustHave: tender,
    by: users.alice,
    ago: 9 * DAY,
  })
  makeDoc(northwind, {
    filename: 'Pricing schedule.xlsx',
    type: 'xlsx',
    text: TEXT.northwindPricing,
    mustHave: pricing,
    by: users.alice,
    ago: 9 * DAY,
  })
  makeDoc(northwind, {
    filename: 'Insurance certificate.pdf',
    type: 'pdf',
    text: TEXT.northwindInsurance,
    mustHave: insurance,
    by: users.alice,
    ago: 9 * DAY,
  })
  makeDoc(northwind, {
    filename: 'Technical proposal.docx',
    type: 'docx',
    text: TEXT.northwindProposal,
    by: users.alice,
    ago: 9 * DAY,
    size: 48_213,
  })
  decide(northwind, terms.id, 'met', users.alice, 8 * DAY, 'Clause 1 of the form of tender.')

  const tessellate = makeBid(PHASE10.tessellate, main.call, {
    bidder: 'Tessellate Logistics',
    contact_name: 'Sam Okoro',
    contact_email: 'bids@tessellate.example',
    price: '96000.00',
    receivedAgo: 7 * DAY,
    enteredBy: users.alice,
  })
  makeDoc(tessellate, {
    filename: 'Tessellate form of tender.pdf',
    type: 'pdf',
    text: TEXT.tessellateTender,
    mustHave: tender,
    by: users.alice,
    ago: 7 * DAY,
  })
  makeDoc(tessellate, {
    filename: 'Prices.csv',
    type: 'csv',
    text: TEXT.tessellatePricing,
    mustHave: pricing,
    by: users.alice,
    ago: 7 * DAY,
  })
  makeDoc(tessellate, {
    filename: 'Insurance.png',
    type: 'png',
    text: 'png',
    mustHave: insurance,
    by: users.alice,
    ago: 7 * DAY,
    size: 182_400,
  })
  makeDoc(tessellate, {
    filename: 'Proposal.pdf',
    type: 'pdf',
    text: TEXT.tessellateProposal,
    by: users.alice,
    ago: 7 * DAY,
    size: 96_004,
  })
  decide(tessellate, terms.id, 'met', users.alice, 6 * DAY, 'Liability cap to agree at signature.')

  const quillfield = makeBid(PHASE10.quillfield, main.call, {
    bidder: 'Quillfield Packaging',
    contact_name: 'Rowan Hale',
    contact_email: 'rowan@quillfield.example',
    price: '80000.00',
    receivedAgo: 6 * DAY + 3 * HOUR,
    enteredBy: users.alice,
    rejected: true,
    rejection: {
      reason: 'No insurance certificate provided.',
      rejected_by_id: users.alice,
      rejected_at: iso(now - 5 * DAY - 2 * HOUR),
      reinstated_at: null,
      reinstated_by_id: null,
    },
  })
  makeDoc(quillfield, {
    filename: 'Tender.pdf',
    type: 'pdf',
    text: TEXT.quillfieldTender,
    mustHave: tender,
    by: users.alice,
    ago: 6 * DAY,
  })
  makeDoc(quillfield, {
    filename: 'Quillfield prices.csv',
    type: 'csv',
    text: TEXT.quillfieldPricing,
    mustHave: pricing,
    by: users.alice,
    ago: 6 * DAY,
  })

  // Assessments: Technical (Q1 weight 2, Q2 weight 1, a comment), Commercial (the price,
  // clarity, terms), Delivery (plan weight 2, team weight 1).
  assess(main.call, northwind, technical, users.carol, [5, 4], {
    ago: 3 * DAY,
    comments: ['', '', 'Ask how the pick-to-light stations cope with seasonal peaks.'],
  })
  assess(main.call, northwind, technical, users.bob, [4, null], { draft: true, ago: 2 * DAY })
  assess(main.call, tessellate, technical, users.carol, [4, 3], { ago: 3 * DAY })
  assess(main.call, tessellate, technical, users.bob, [2, 3], {
    ago: 2 * DAY,
    comments: [
      'Hand packing on shifts won’t keep up with a monthly peak.',
      '',
      'Capacity is the main risk.',
    ],
  })
  assess(main.call, northwind, commercial, users.dave, [4, 4], { ago: 4 * DAY })
  assess(main.call, tessellate, commercial, users.dave, [3, 4], { ago: 4 * DAY })
  assess(main.call, northwind, delivery, users.farid, [4, 5], { ago: 3 * DAY })
  assess(main.call, tessellate, delivery, users.farid, [3, 3], { ago: 3 * DAY })
  assess(main.call, northwind, delivery, users.priya, [5, 4], { ago: 1 * DAY })

  // The Bid assessor's assessment of Tessellate (left out of the totals); one quote
  // isn't in the document.
  const tessellateDocs = db.bid.documents.filter((d) => d.bid_id === tessellate.id)
  const proposalDoc = tessellateDocs.find((d) => d.filename === 'Proposal.pdf')
  const tenderDoc = tessellateDocs.find((d) => d.filename === 'Tessellate form of tender.pdf')
  if (proposalDoc && tenderDoc) {
    const q = (title: string, position: number) => main.question(title, position).id
    db.bid.aiAssessments.push({
      id: PHASE10.tessellateAi,
      bid_id: tessellate.id,
      agent_id: agent.id,
      submitted_at: iso(now - 2 * DAY - 3 * HOUR),
      included: false,
      scores: [
        {
          question_id: q('Technical', 0),
          score: 3,
          rationale: 'Hand packing on two shifts meets the volume, with little room for peaks.',
          evidence: [
            {
              document_id: proposalDoc.id,
              quote:
                'Boxes are packed by hand on two shifts; we would add a third shift for the first monthly run',
            },
          ],
        },
        {
          question_id: q('Technical', 1),
          score: 3,
          rationale: 'Backups and Cyber Essentials, but no ISO 27001 yet.',
          evidence: [
            {
              document_id: proposalDoc.id,
              quote: 'We follow Cyber Essentials and are working towards ISO 27001.',
            },
          ],
        },
        {
          question_id: q('Commercial', 1),
          score: 4,
          rationale: 'One price per box, all costs included.',
          evidence: [
            {
              document_id: tenderDoc.id,
              quote: 'Our price includes every cost of packing, delivery and returns.',
            },
          ],
        },
        {
          question_id: q('Commercial', 2),
          score: 3,
          rationale: 'They accept the standard terms but want to discuss the liability cap.',
          evidence: [
            {
              document_id: tenderDoc.id,
              quote: 'We accept the standard terms, with a request to agree the liability cap',
            },
          ],
        },
        {
          question_id: q('Delivery', 0),
          score: 3,
          rationale: 'Six weeks to start, after a short trial.',
          evidence: [
            {
              document_id: proposalDoc.id,
              quote: 'We can start packing within six weeks of signature, after a two-week trial',
            },
          ],
        },
        {
          question_id: q('Delivery', 1),
          score: 2,
          rationale: 'No named team or references in the documents.',
          evidence: [],
        },
      ],
      findings: [
        {
          must_have_id: tender.id,
          finding: 'met',
          rationale: 'A signed form of tender is attached.',
          evidence: [
            {
              document_id: tenderDoc.id,
              quote:
                'Tessellate Logistics offers to fulfil subscription boxes from its Midlands warehouse.',
            },
          ],
        },
        {
          must_have_id: insurance.id,
          finding: 'unclear',
          rationale: 'The certificate is an image: I couldn’t read it.',
          evidence: [],
        },
        {
          must_have_id: terms.id,
          finding: 'met',
          rationale: 'The form of tender accepts the terms, asking to agree the liability cap.',
          evidence: [
            {
              document_id: tenderDoc.id,
              quote: 'We accept the standard terms, with a request to agree the liability cap',
            },
          ],
        },
      ],
    })
  }

  /* TOOL-4: open, with a flagged bid ------------------------------------- */
  const tool4 = idea('TOOL-4')
  const open = makeCall(PHASE10.tool4Call, tool4, {
    title: 'Feature flag service: build partner',
    description: 'Build and support the self-service feature flag service for two years.',
    status: 'open',
    deadline_at: iso(endOfDay(5)),
    assessment_due_at: iso(endOfDay(14)),
    ai_assessor_id: agent.id,
    createdAgo: 6 * DAY,
    createdBy: users.bob,
  })
  moved(tool4, open.call, 'draft', 'open', 5 * DAY, users.bob)
  db.bid.assessors.push(
    {
      call_id: open.call.id,
      section_id: open.section('Technical').id,
      user_id: users.dave,
      assigned_at: iso(now - 5 * DAY),
    },
    {
      call_id: open.call.id,
      section_id: open.section('Commercial').id,
      user_id: users.farid,
      assigned_at: iso(now - 5 * DAY),
    },
    {
      call_id: open.call.id,
      section_id: open.section('Delivery').id,
      user_id: users.dave,
      assigned_at: iso(now - 5 * DAY),
    },
  )
  const brightline = makeBid(PHASE10.brightline, open.call, {
    bidder: 'Brightline Software',
    contact_name: 'Mira Jensen',
    contact_email: 'mira@brightline.example',
    price: '48500.00',
    receivedAgo: 2 * DAY,
    enteredBy: users.bob,
  })
  makeDoc(brightline, {
    filename: 'Form of tender.pdf',
    type: 'pdf',
    text: TEXT.brightlineTender,
    mustHave: open.mustHave('Signed form of tender'),
    by: users.bob,
    ago: 2 * DAY,
  })
  makeDoc(brightline, {
    filename: 'Pricing.xlsx',
    type: 'xlsx',
    text: TEXT.brightlinePricing,
    mustHave: open.mustHave('Pricing schedule'),
    by: users.bob,
    ago: 2 * DAY,
  })
  makeDoc(brightline, {
    filename: 'Insurance certificate.pdf',
    type: 'pdf',
    text: TEXT.brightlineInsurance,
    mustHave: open.mustHave('Insurance certificate'),
    by: users.bob,
    ago: 2 * DAY,
  })
  makeDoc(brightline, {
    filename: 'Solution design.docx',
    type: 'docx',
    text: 'Solution design',
    by: users.bob,
    ago: 3 * MINUTE,
    state: 'pending',
    size: 210_554,
  })
  decide(brightline, open.mustHave('Accepts our standard terms').id, 'met', users.alice, 1 * DAY)

  const kestrel = makeBid(PHASE10.kestrel, open.call, {
    bidder: 'Kestrel Code Co',
    contact_name: 'Theo Marsh',
    contact_email: 'theo@kestrel.example',
    price: '41000.00',
    receivedAgo: 1 * DAY,
    enteredBy: users.bob,
    auto_ai_run_at: iso(now - 20 * HOUR),
  })
  makeDoc(kestrel, {
    filename: 'Tender form.pdf',
    type: 'pdf',
    text: TEXT.kestrelTender,
    mustHave: open.mustHave('Signed form of tender'),
    by: users.bob,
    ago: 1 * DAY,
  })
  makeDoc(kestrel, {
    filename: 'Kestrel pricing.csv',
    type: 'csv',
    text: TEXT.kestrelPricing,
    mustHave: open.mustHave('Pricing schedule'),
    by: users.bob,
    ago: 1 * DAY,
  })
  makeDoc(kestrel, {
    filename: 'Brochure.pdf',
    type: 'pdf',
    text: TEXT.kestrelBrochure,
    by: users.bob,
    ago: 1 * DAY,
    active: true,
    size: 1_204_331,
  })
  makeDoc(kestrel, {
    filename: 'Scanned references.pdf',
    type: 'pdf',
    text: '',
    by: users.bob,
    ago: 1 * DAY,
    state: 'failed',
    error: 'encrypted',
    size: 3_402_118,
  })
  const kestrelTender = db.bid.documents.find(
    (d) => d.bid_id === kestrel.id && d.filename === 'Tender form.pdf',
  )
  db.bid.aiAssessments.push({
    id: PHASE10.kestrelAi,
    bid_id: kestrel.id,
    agent_id: agent.id,
    submitted_at: iso(now - 20 * HOUR + 3 * MINUTE),
    included: false,
    scores: [],
    findings: [
      {
        must_have_id: open.mustHave('Signed form of tender').id,
        finding: 'met',
        rationale: 'A form of tender is attached.',
        evidence: kestrelTender
          ? [
              {
                document_id: kestrelTender.id,
                quote:
                  'Kestrel Code Co offers a feature flag service built on open-source components.',
              },
            ]
          : [],
      },
      {
        must_have_id: open.mustHave('Insurance certificate').id,
        finding: 'not_met',
        rationale: 'I found no insurance certificate among the documents.',
        evidence: [],
      },
      {
        must_have_id: open.mustHave('Accepts our standard terms').id,
        finding: 'not_met',
        rationale: 'The bid applies its own terms of business instead of ours.',
        evidence: kestrelTender
          ? [
              {
                document_id: kestrelTender.id,
                quote: 'Our terms of business are attached and apply to this offer.',
              },
            ]
          : [],
      },
    ],
  })
  // Its automatic pre-check run (the call's AI assessor), done.
  const runStart = now - 20 * HOUR
  const run: MockAiRun = {
    id: PHASE10.kestrelRun,
    idea_id: tool4.id,
    agent_id: agent.id,
    kind: 'assess_bid',
    section_key: null,
    bid_id: kestrel.id,
    bid_call_id: open.call.id,
    automatic: true,
    bid_ai_assessment_id: PHASE10.kestrelAi,
    status: 'succeeded',
    requested_by_id: null,
    created_at: iso(runStart),
    started_at: iso(runStart + 4_000),
    finished_at: iso(runStart + 3 * MINUTE + 10_000),
    timeout_seconds: db.aiSettings.run_timeout_seconds,
    cancel_requested_at: null,
    cancel_requested_by_id: null,
    error_code: null,
    error_message: null,
    evaluation_id: null,
    suggestion_id: null,
    activity_event_id: null,
    assigned_evaluator: false,
    outcome: 'succeed',
    step: 99,
  }
  db.aiRuns.push(run)
  const steps: [AiRunEventType, string][] = [
    ['queued', 'Started automatically'],
    ['started', 'Started'],
    ['agent_accepted', 'The agent accepted the task'],
    ['tool_called', 'Read the bid'],
    ['tool_called', 'Read a bid document'],
    ['tool_called', 'Saved its bid assessment'],
    ['result_recorded', 'Bid assessment saved'],
    ['succeeded', 'Done'],
  ]
  steps.forEach(([type, message], index) => {
    const event: MockAiRunEvent = {
      run_id: run.id,
      seq: index + 1,
      type,
      message,
      created_at: iso(runStart + index * 20_000),
    }
    db.aiRunEvents.push(event)
  })

  /* TOOL-11: a draft ------------------------------------------------------ */
  makeCall(PHASE10.tool11Call, idea('TOOL-11'), {
    title: 'Release notes generator: build',
    createdAgo: 2 * DAY,
    createdBy: users.alice,
  })

  /* CUST-10: awarded ----------------------------------------------------- */
  const cust10 = idea('CUST-10')
  const awarded = makeCall(PHASE10.cust10Call, cust10, {
    title: 'Pickup lockers for ten stores',
    status: 'awarded',
    deadline_at: iso(endOfDay(-80)),
    assessment_due_at: iso(endOfDay(-70)),
    awarded_at: iso(now - 65 * DAY),
    awarded_bid_id: PHASE10.lockwise,
    award_reason: 'Best value, with a proven pilot in two stores.',
    createdAgo: 100 * DAY,
    createdBy: users.farid,
  })
  moved(cust10, awarded.call, 'draft', 'open', 98 * DAY, users.farid)
  moved(cust10, awarded.call, 'open', 'assessing', 79 * DAY, users.farid)
  moved(cust10, awarded.call, 'assessing', 'awarded', 65 * DAY, users.farid)
  for (const [title, user] of [
    ['Technical', users.carol],
    ['Commercial', users.dave],
    ['Delivery', users.farid],
  ] as const) {
    db.bid.assessors.push({
      call_id: awarded.call.id,
      section_id: awarded.section(title).id,
      user_id: user,
      assigned_at: iso(now - 79 * DAY),
    })
  }
  const lockwise = makeBid(PHASE10.lockwise, awarded.call, {
    bidder: 'Lockwise Systems',
    price: '64000.00',
    receivedAgo: 85 * DAY,
    enteredBy: users.farid,
  })
  const parcelhub = makeBid(PHASE10.parcelhub, awarded.call, {
    bidder: 'Parcelhub Retail',
    price: '58000.00',
    receivedAgo: 84 * DAY,
    enteredBy: users.farid,
  })
  for (const [bid, text] of [
    [lockwise, TEXT.lockwiseTender],
    [parcelhub, TEXT.parcelhubTender],
  ] as const) {
    makeDoc(bid, {
      filename: 'Form of tender.pdf',
      type: 'pdf',
      text,
      mustHave: awarded.mustHave('Signed form of tender'),
      by: users.farid,
      ago: 84 * DAY,
    })
    makeDoc(bid, {
      filename: 'Pricing schedule.csv',
      type: 'csv',
      text: 'Total,see price',
      mustHave: awarded.mustHave('Pricing schedule'),
      by: users.farid,
      ago: 84 * DAY,
    })
    makeDoc(bid, {
      filename: 'Insurance certificate.pdf',
      type: 'pdf',
      text: 'CERTIFICATE OF INSURANCE. Public liability cover.',
      mustHave: awarded.mustHave('Insurance certificate'),
      by: users.farid,
      ago: 84 * DAY,
    })
    decide(bid, awarded.mustHave('Accepts our standard terms').id, 'met', users.farid, 83 * DAY)
  }
  assess(awarded.call, lockwise, awarded.section('Technical'), users.carol, [5, 4], {
    ago: 72 * DAY,
  })
  assess(awarded.call, parcelhub, awarded.section('Technical'), users.carol, [3, 4], {
    ago: 72 * DAY,
  })
  assess(awarded.call, lockwise, awarded.section('Commercial'), users.dave, [4, 4], {
    ago: 72 * DAY,
  })
  assess(awarded.call, parcelhub, awarded.section('Commercial'), users.dave, [4, 3], {
    ago: 72 * DAY,
  })
  assess(awarded.call, lockwise, awarded.section('Delivery'), users.farid, [4, 4], {
    ago: 71 * DAY,
  })
  assess(awarded.call, parcelhub, awarded.section('Delivery'), users.farid, [3, 3], {
    ago: 71 * DAY,
  })
  awarded.call.complete_notified = true

  /* CUST-12: cancelled --------------------------------------------------- */
  const cust12 = idea('CUST-12')
  const cancelled = makeCall(PHASE10.cust12Call, cust12, {
    title: 'AR viewer development',
    status: 'cancelled',
    deadline_at: iso(endOfDay(-40)),
    cancelled_at: iso(now - 45 * DAY),
    cancel_reason: 'The idea was parked.',
    createdAgo: 60 * DAY,
    createdBy: users.alice,
  })
  moved(cust12, cancelled.call, 'draft', 'open', 58 * DAY, users.alice)
  moved(cust12, cancelled.call, 'open', 'cancelled', 45 * DAY, users.alice)

  /* Notifications (read: the earlier phases' unread counts stay) --------- */
  const notification = (
    to: string,
    type: 'assessor_assigned' | 'assessment_reminder' | 'assessments_complete',
    target: MockIdea,
    payload: Record<string, unknown>,
    ago: number,
    actor: string | null,
  ) => {
    db.notifications.push({
      id: nextId('c'),
      user_id: to,
      type,
      idea_id: target.id,
      actor_id: actor,
      comment_id: null,
      payload,
      dedupe_key: `${type}:${String(payload.call_id)}:${to}:${ago}`,
      email_mode: 'immediate',
      email_id: null,
      created_at: iso(now - ago),
      read_at: iso(now - ago + HOUR),
    })
  }
  notification(
    users.bob,
    'assessor_assigned',
    cust3,
    { call_id: main.call.id, sections: ['Technical'], due_at: main.call.assessment_due_at },
    5 * DAY,
    users.alice,
  )
  notification(
    users.priya,
    'assessor_assigned',
    cust3,
    { call_id: main.call.id, sections: ['Delivery'], due_at: main.call.assessment_due_at },
    5 * DAY,
    users.alice,
  )
  notification(
    users.dave,
    'assessor_assigned',
    tool4,
    {
      call_id: open.call.id,
      sections: ['Technical', 'Delivery'],
      due_at: open.call.assessment_due_at,
    },
    5 * DAY,
    users.bob,
  )
  notification(
    users.priya,
    'assessment_reminder',
    cust3,
    { call_id: main.call.id, due_at: main.call.assessment_due_at, days_before: 2 },
    2 * HOUR,
    null,
  )
  notification(
    users.farid,
    'assessments_complete',
    cust10,
    { call_id: awarded.call.id, bid_count: 2, assessment_count: 6 },
    70 * DAY,
    null,
  )
}
