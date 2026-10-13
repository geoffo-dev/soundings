/**
 * Phase 10: bid evaluation in the mock backend (contract-phase10, role matrix table M
 * and section 3a). Records (one store on the database), the rules (call managers,
 * section assessors with c28 checked live, the blind rule, prices and pricing
 * documents), the scoring (section 8) and the output shapes. Not the authority: the
 * backend and its tests are; this follows them closely enough to build the screens.
 */
import type {
  AiBlockedReason,
  AiMustHaveFinding,
  Bid,
  BidAiAssessment,
  BidAiFindingView,
  BidAiScoreView,
  BidAiSectionScores,
  BidAssessmentView,
  BidCall,
  BidCallPermissions,
  BidCallRef,
  BidCallStatus,
  BidCallSummary,
  BidCallTemplate,
  BidComparison,
  BidComparisonRow,
  BidDetail,
  BidDocument,
  BidDocumentType,
  BidMustHaveState,
  BidPermissions,
  BidProgress,
  BidQuestionStats,
  BidQuestionType,
  BidSectionAssessments,
  BidSectionScore,
  BidSectionState,
  BidStatus,
  BidTemplate,
  EvaluatorState,
  ExtractionError,
  ExtractionState,
  MustHaveKind,
  MustHaveResult,
  MyBidAssessment,
  WorkBidAssessment,
} from '@/api/types'

import { agentById, agentPasses, agentRef, type MockAiAgent, type MockAiRun } from './ai'
import type { MockDb, MockIdea, MockNotification, MockUser } from './db'
import {
  canViewProject,
  effectiveRole,
  findUser,
  ideaRef,
  isProjectAdmin,
  projectOf,
  userRefById,
} from './domain'
import { proposalOf } from './proposals'
import { isResearchGuest } from './researchers'

/* ------------------------------------------------------------------ */
/* Limits (app/schemas/bids.py)                                        */
/* ------------------------------------------------------------------ */

export const BID_SECTIONS_MAX = 8
export const BID_QUESTIONS_PER_SECTION_MAX = 15
export const BID_MUST_HAVES_MAX = 20
export const BIDS_PER_CALL_MAX = 50
export const ASSESSORS_PER_SECTION_MAX = 10
export const BID_DOCUMENTS_PER_BID_MAX = 30
export const BID_DOCUMENT_MAX_BYTES = 25 * 1024 * 1024
export const BID_CALL_STORAGE_MAX_BYTES = 500 * 1024 * 1024
export const BID_TEXT_PAGE_CHARS = 20_000
export const BID_FILENAME_MAX_LENGTH = 200
export const DISAGREEMENT_SPREAD = 2

export const DEFAULT_BID_SCALE = [
  'No response, or unacceptable',
  'Poor: major gaps',
  'Weak: some gaps or doubts',
  'Acceptable: meets the requirement',
  'Good: meets it with some added value',
  'Excellent: exceeds it, with clear evidence',
]

/** `BID_DOCUMENT_TYPES`: media type and extensions per sniffed type. */
export const BID_DOCUMENT_TYPES: Record<BidDocumentType, { media: string; ext: string[] }> = {
  pdf: { media: 'application/pdf', ext: ['.pdf'] },
  docx: {
    media: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    ext: ['.docx'],
  },
  xlsx: {
    media: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    ext: ['.xlsx'],
  },
  pptx: {
    media: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    ext: ['.pptx'],
  },
  odt: { media: 'application/vnd.oasis.opendocument.text', ext: ['.odt'] },
  ods: { media: 'application/vnd.oasis.opendocument.spreadsheet', ext: ['.ods'] },
  txt: { media: 'text/plain; charset=utf-8', ext: ['.txt'] },
  csv: { media: 'text/csv; charset=utf-8', ext: ['.csv'] },
  png: { media: 'image/png', ext: ['.png'] },
  jpeg: { media: 'image/jpeg', ext: ['.jpg', '.jpeg'] },
}

/* ------------------------------------------------------------------ */
/* Records (docs/erd.md: bid_templates, bid_calls, …)                  */
/* ------------------------------------------------------------------ */

export interface MockTemplateQuestion {
  text: string
  guidance: string
  type: BidQuestionType
  weight: number
}

export interface MockTemplateSection {
  title: string
  guidance: string
  weight: number
  questions: MockTemplateQuestion[]
}

export interface MockTemplateMustHave {
  text: string
  kind: MustHaveKind
  pricing: boolean
}

export interface MockBidTemplate {
  project_id: string
  scale: string[]
  sections: MockTemplateSection[]
  must_haves: MockTemplateMustHave[]
  updated_at: string | null
  updated_by_id: string | null
}

export interface MockBidCall {
  id: string
  idea_id: string
  title: string
  description: string
  currency: string
  status: BidCallStatus
  deadline_at: string | null
  assessment_due_at: string | null
  ai_assessor_id: string | null
  scale: string[]
  created_by_id: string | null
  created_at: string
  updated_at: string
  awarded_at: string | null
  awarded_bid_id: string | null
  award_reason: string | null
  cancelled_at: string | null
  cancel_reason: string | null
  /** "Bid assessments complete" was sent (once per call). */
  complete_notified: boolean
}

export interface MockBidSection {
  id: string
  call_id: string
  position: number
  title: string
  guidance: string
  weight: number
}

export interface MockBidQuestion {
  id: string
  call_id: string
  section_id: string
  position: number
  text: string
  guidance: string
  type: BidQuestionType
  weight: number
}

export interface MockBidMustHave {
  id: string
  call_id: string
  position: number
  text: string
  kind: MustHaveKind
  pricing: boolean
}

export interface MockBidAssessor {
  call_id: string
  section_id: string
  user_id: string
  assigned_at: string
}

export interface MockBidRejection {
  reason: string
  rejected_by_id: string | null
  rejected_at: string
  reinstated_at: string | null
  reinstated_by_id: string | null
}

export interface MockBid {
  id: string
  call_id: string
  bidder: string
  contact_name: string
  contact_email: string | null
  received_at: string
  price: string | null
  notes: string
  entered_by_id: string | null
  created_at: string
  updated_at: string
  rejection: MockBidRejection | null
  /** The current state: rejected (the rejection above) or not (reinstated, or never). */
  rejected: boolean
  auto_ai_run_at: string | null
}

export interface MockMustHaveDecision {
  bid_id: string
  must_have_id: string
  result: 'met' | 'not_met'
  decided_by_id: string | null
  decided_at: string
  note: string
}

export interface MockBidDocument {
  id: string
  bid_id: string
  filename: string
  type: BidDocumentType
  size_bytes: number
  sha256: string
  must_have_id: string | null
  pricing: boolean
  active_content: boolean
  uploaded_by_id: string | null
  uploaded_at: string
  bytes: Uint8Array
  extraction: {
    state: ExtractionState
    error: ExtractionError | null
    text: string
    truncated: boolean
  }
}

export interface MockAnswer {
  question_id: string
  score: number | null
  comment: string
}

export interface MockBidAssessment {
  id: string
  call_id: string
  bid_id: string
  section_id: string
  user_id: string
  status: 'draft' | 'submitted'
  answers: MockAnswer[]
  submitted_at: string | null
  edited_at: string | null
  updated_at: string
}

export interface MockEvidence {
  document_id: string
  quote: string
}

export interface MockBidAiAssessment {
  id: string
  bid_id: string
  agent_id: string
  submitted_at: string
  included: boolean
  scores: { question_id: string; score: number; rationale: string; evidence: MockEvidence[] }[]
  findings: {
    must_have_id: string
    finding: AiMustHaveFinding
    rationale: string
    evidence: MockEvidence[]
  }[]
}

export interface MockBidStore {
  templates: MockBidTemplate[]
  calls: MockBidCall[]
  sections: MockBidSection[]
  questions: MockBidQuestion[]
  mustHaves: MockBidMustHave[]
  assessors: MockBidAssessor[]
  bids: MockBid[]
  decisions: MockMustHaveDecision[]
  documents: MockBidDocument[]
  assessments: MockBidAssessment[]
  aiAssessments: MockBidAiAssessment[]
}

export function emptyBidStore(): MockBidStore {
  return {
    templates: [],
    calls: [],
    sections: [],
    questions: [],
    mustHaves: [],
    assessors: [],
    bids: [],
    decisions: [],
    documents: [],
    assessments: [],
    aiAssessments: [],
  }
}

/** The built-in default (`DEFAULT_BID_TEMPLATE`). */
export function defaultBidTemplate(projectId: string): MockBidTemplate {
  return {
    project_id: projectId,
    scale: [...DEFAULT_BID_SCALE],
    sections: [
      {
        title: 'Technical',
        guidance: 'How well the solution meets our requirements, and how safely.',
        weight: 40,
        questions: [
          {
            text: 'How well does the proposed solution meet our requirements?',
            guidance:
              'Look for a clear description of how each requirement is met, with evidence such as references, demos or examples.',
            type: 'score',
            weight: 2,
          },
          {
            text: 'How well will our data be kept secure and compliant?',
            guidance:
              'Certifications, where data is held, access controls, backups and how personal data is protected.',
            type: 'score',
            weight: 1,
          },
          {
            text: 'What risks do you see in the technical approach?',
            guidance: 'Note anything the team should ask the bidder about.',
            type: 'comment',
            weight: 0,
          },
        ],
      },
      {
        title: 'Commercial',
        guidance: 'What it costs and on what terms.',
        weight: 40,
        questions: [
          {
            text: 'Price',
            guidance:
              'The total price for the contract term, from the pricing schedule, entered by the team. Scored automatically: lowest qualified price / this price x 5.',
            type: 'price',
            weight: 3,
          },
          {
            text: 'How clear and complete is the pricing?',
            guidance: 'All costs shown, no hidden extras, clear assumptions.',
            type: 'score',
            weight: 1,
          },
          {
            text: 'Are the payment terms and contract conditions acceptable?',
            guidance: 'Payment schedule, notice periods, liability and exit terms.',
            type: 'score',
            weight: 1,
          },
        ],
      },
      {
        title: 'Delivery',
        guidance: 'Whether they can deliver it, when, and with whom.',
        weight: 20,
        questions: [
          {
            text: 'How realistic is the delivery plan and timeline?',
            guidance: 'Milestones, dependencies, what they need from us.',
            type: 'score',
            weight: 2,
          },
          {
            text: 'How strong is the team and its relevant experience?',
            guidance: 'Named people, similar work done before, references.',
            type: 'score',
            weight: 1,
          },
        ],
      },
    ],
    must_haves: [
      { text: 'Signed form of tender', kind: 'document', pricing: false },
      { text: 'Pricing schedule', kind: 'document', pricing: true },
      { text: 'Insurance certificate', kind: 'document', pricing: false },
      { text: 'Accepts our standard terms', kind: 'confirmation', pricing: false },
    ],
    updated_at: null,
    updated_by_id: null,
  }
}

export function templateOf(db: MockDb, projectId: string): MockBidTemplate {
  let template = db.bid.templates.find((t) => t.project_id === projectId)
  if (!template) {
    template = defaultBidTemplate(projectId)
    db.bid.templates.push(template)
  }
  return template
}

/* ------------------------------------------------------------------ */
/* Lookups                                                             */
/* ------------------------------------------------------------------ */

export function callOf(db: MockDb, idea: MockIdea): MockBidCall | undefined {
  return db.bid.calls.find((call) => call.idea_id === idea.id)
}

export function ideaOfCall(db: MockDb, call: MockBidCall): MockIdea | undefined {
  return db.ideas.find((idea) => idea.id === call.idea_id)
}

export function sectionsOf(db: MockDb, call: MockBidCall): MockBidSection[] {
  return db.bid.sections
    .filter((s) => s.call_id === call.id)
    .sort((a, b) => a.position - b.position)
}

export function questionsOf(db: MockDb, section: MockBidSection): MockBidQuestion[] {
  return db.bid.questions
    .filter((q) => q.section_id === section.id)
    .sort((a, b) => a.position - b.position)
}

export function mustHavesOf(db: MockDb, call: MockBidCall): MockBidMustHave[] {
  return db.bid.mustHaves
    .filter((m) => m.call_id === call.id)
    .sort((a, b) => a.position - b.position)
}

export function bidsOf(db: MockDb, call: MockBidCall): MockBid[] {
  return db.bid.bids
    .filter((b) => b.call_id === call.id)
    .sort((a, b) => a.received_at.localeCompare(b.received_at) || a.id.localeCompare(b.id))
}

export function documentsOf(db: MockDb, bid: MockBid): MockBidDocument[] {
  return db.bid.documents
    .filter((d) => d.bid_id === bid.id)
    .sort((a, b) => a.uploaded_at.localeCompare(b.uploaded_at) || a.id.localeCompare(b.id))
}

export function priceQuestion(db: MockDb, call: MockBidCall): MockBidQuestion | undefined {
  return db.bid.questions.find((q) => q.call_id === call.id && q.type === 'price')
}

export function priceSection(db: MockDb, call: MockBidCall): MockBidSection | undefined {
  const question = priceQuestion(db, call)
  return question ? db.bid.sections.find((s) => s.id === question.section_id) : undefined
}

export function isFinished(call: MockBidCall): boolean {
  return call.status === 'awarded' || call.status === 'cancelled'
}

/** The template copy is locked once a person's assessment is submitted. */
export function templateLocked(db: MockDb, call: MockBidCall): boolean {
  return db.bid.assessments.some((a) => a.call_id === call.id && a.status === 'submitted')
}

/* ------------------------------------------------------------------ */
/* Who (role matrix table M)                                           */
/* ------------------------------------------------------------------ */

function memberish(db: MockDb, projectId: string, userId: string): boolean {
  const role = effectiveRole(db, projectId, userId)
  return role === 'member' || role === 'admin'
}

/** Call managers: the idea's owner (with a role), project admins, platform admins. */
export function isCallManager(db: MockDb, idea: MockIdea, user: MockUser): boolean {
  if (user.is_service_account) return false
  const project = projectOf(db, idea)
  if (isProjectAdmin(db, project, user)) return true
  return idea.owner_id === user.id && memberish(db, project.id, user.id)
}

/** c28, checked live: an active person who can view the idea in their own right. */
export function assessorEligible(db: MockDb, idea: MockIdea, userId: string): boolean {
  const user = findUser(db, userId)
  if (!user?.is_active || user.is_service_account || user.is_break_glass) return false
  if (idea.held_for === 'email_verification') return false
  // Never through the guest researcher column (review M6): the project itself.
  return canViewProject(db, projectOf(db, idea), user)
}

/** The sections this person assesses on the call (+Asr, live). */
export function assessedSectionIds(db: MockDb, call: MockBidCall, user: MockUser): string[] {
  const idea = ideaOfCall(db, call)
  if (!idea || !assessorEligible(db, idea, user.id)) return []
  const ids = new Set(
    db.bid.assessors
      .filter((a) => a.call_id === call.id && a.user_id === user.id)
      .map((a) => a.section_id),
  )
  return sectionsOf(db, call)
    .filter((s) => ids.has(s.id))
    .map((s) => s.id)
}

/** `bid.view_call`: everyone who views the idea, never its guest researcher. */
export function canViewCall(db: MockDb, idea: MockIdea, user: MockUser): boolean {
  return !isResearchGuest(db, idea, user)
}

/** `bid.view_bids`: call managers and (live) section assessors. */
export function canViewBids(db: MockDb, idea: MockIdea, user: MockUser): boolean {
  if (!canViewCall(db, idea, user)) return false
  if (isCallManager(db, idea, user)) return true
  const call = callOf(db, idea)
  return Boolean(call && assessedSectionIds(db, call, user).length > 0)
}

/** `bid.view_price`: call managers and the price section's assessors. */
export function canSeePrices(db: MockDb, call: MockBidCall, user: MockUser): boolean {
  const idea = ideaOfCall(db, call)
  if (!idea) return false
  if (isCallManager(db, idea, user)) return true
  const section = priceSection(db, call)
  return Boolean(section && assessedSectionIds(db, call, user).includes(section.id))
}

/** Writable now: the project isn't archived, the idea isn't closed or held. */
export function ideaWritable(db: MockDb, idea: MockIdea): boolean {
  return projectOf(db, idea).archived_at === null && idea.status !== 'closed' && !idea.held_for
}

/** A submitted assessment by this person of (bid, section). */
export function submittedBy(
  db: MockDb,
  bidId: string,
  sectionId: string,
  userId: string,
): MockBidAssessment | undefined {
  return db.bid.assessments.find(
    (a) =>
      a.bid_id === bidId &&
      a.section_id === sectionId &&
      a.user_id === userId &&
      a.status === 'submitted',
  )
}

/** Section 3a: assigned to the section and not submitted it for this bid (drafts don't count). */
export function isPending(db: MockDb, bid: MockBid, sectionId: string, userId: string): boolean {
  const assigned = db.bid.assessors.some(
    (a) => a.call_id === bid.call_id && a.section_id === sectionId && a.user_id === userId,
  )
  return assigned && !submittedBy(db, bid.id, sectionId, userId)
}

/* ------------------------------------------------------------------ */
/* Must-haves                                                          */
/* ------------------------------------------------------------------ */

export function decisionOf(
  db: MockDb,
  bidId: string,
  mustHaveId: string,
): MockMustHaveDecision | undefined {
  return db.bid.decisions.find((d) => d.bid_id === bidId && d.must_have_id === mustHaveId)
}

function linkedDocuments(db: MockDb, bid: MockBid, mustHave: MockBidMustHave): MockBidDocument[] {
  return documentsOf(db, bid).filter((d) => d.must_have_id === mustHave.id)
}

/** The bid's result for one must-have (section 5.3). */
export function mustHaveResult(
  db: MockDb,
  bid: MockBid,
  mustHave: MockBidMustHave,
): { result: MustHaveResult; automatic: boolean } {
  const decision = decisionOf(db, bid.id, mustHave.id)
  if (mustHave.kind === 'document') {
    const files = linkedDocuments(db, bid, mustHave).length
    if (decision?.result === 'not_met') return { result: 'not_met', automatic: false }
    if (files === 0) return { result: 'missing', automatic: true }
    if (decision?.result === 'met') return { result: 'met', automatic: false }
    return { result: 'met', automatic: true }
  }
  if (decision) return { result: decision.result, automatic: false }
  return { result: 'unchecked', automatic: true }
}

export function results(db: MockDb, bid: MockBid): MustHaveResult[] {
  const call = db.bid.calls.find((c) => c.id === bid.call_id)
  if (!call) return []
  return mustHavesOf(db, call).map((m) => mustHaveResult(db, bid, m).result)
}

/** `is_scored`: not rejected and every must-have met, whatever the award made it. */
export function isScored(db: MockDb, bid: MockBid): boolean {
  return !bid.rejected && results(db, bid).every((result) => result === 'met')
}

/** `call_bid_status`. */
export function bidStatus(db: MockDb, bid: MockBid): BidStatus {
  if (bid.rejected) return 'rejected'
  const call = db.bid.calls.find((c) => c.id === bid.call_id)
  if (call?.status === 'awarded') return call.awarded_bid_id === bid.id ? 'awarded' : 'unsuccessful'
  return results(db, bid).every((r) => r === 'met') ? 'qualified' : 'received'
}

/** A must-have missing or not met, or an AI finding not met (`reject_suggested`). */
export function rejectSuggested(db: MockDb, bid: MockBid): boolean {
  if (bid.rejected) return false
  if (results(db, bid).some((r) => r === 'missing' || r === 'not_met')) return true
  return db.bid.aiAssessments.some(
    (a) => a.bid_id === bid.id && a.findings.some((f) => f.finding === 'not_met'),
  )
}

/* ------------------------------------------------------------------ */
/* Progress                                                            */
/* ------------------------------------------------------------------ */

function progressFor(
  db: MockDb,
  call: MockBidCall,
  bids: MockBid[],
  sectionIds: string[] | null,
  userId: string | null,
): BidProgress {
  const idea = ideaOfCall(db, call)
  let submitted = 0
  let total = 0
  for (const bid of bids) {
    if (bid.rejected) continue
    for (const row of db.bid.assessors) {
      if (row.call_id !== call.id) continue
      if (sectionIds && !sectionIds.includes(row.section_id)) continue
      if (userId && row.user_id !== userId) continue
      const done = Boolean(submittedBy(db, bid.id, row.section_id, row.user_id))
      const eligible = Boolean(idea && assessorEligible(db, idea, row.user_id))
      if (eligible || done) total += 1
      if (done) submitted += 1
    }
  }
  return { submitted, total }
}

export function callProgress(db: MockDb, call: MockBidCall): BidProgress {
  return progressFor(db, call, bidsOf(db, call), null, null)
}

export function bidProgress(db: MockDb, call: MockBidCall, bid: MockBid): BidProgress {
  return progressFor(db, call, [bid], null, null)
}

/* ------------------------------------------------------------------ */
/* Scoring (section 8; ADR 0018)                                       */
/* ------------------------------------------------------------------ */

/** Half up on the exact value (`round_score`). */
export function roundScore(value: number, places: 1 | 2 = 1): number {
  const factor = places === 1 ? 10 : 100
  return Math.round(value * factor + 1e-9) / factor
}

function mean(values: number[]): number | null {
  return values.length ? values.reduce((sum, v) => sum + v, 0) / values.length : null
}

/** The scores counted for one question of one bid: submitted human scores + included AI. */
export function countedScores(db: MockDb, bid: MockBid, question: MockBidQuestion): number[] {
  const human = db.bid.assessments
    .filter(
      (a) =>
        a.bid_id === bid.id && a.section_id === question.section_id && a.status === 'submitted',
    )
    .flatMap((a) => a.answers.filter((x) => x.question_id === question.id && x.score !== null))
    .map((x) => x.score ?? 0)
  const ai = db.bid.aiAssessments
    .filter((a) => a.bid_id === bid.id && a.included)
    .flatMap((a) => a.scores.filter((s) => s.question_id === question.id))
    .map((s) => s.score)
  return [...human, ...ai]
}

export function lowestScoredPrice(db: MockDb, call: MockBidCall): number | null {
  const prices = bidsOf(db, call)
    .filter((bid) => isScored(db, bid) && bid.price !== null)
    .map((bid) => Number(bid.price))
  return prices.length ? Math.min(...prices) : null
}

export function priceScore(db: MockDb, call: MockBidCall, bid: MockBid): number | null {
  if (!isScored(db, bid) || bid.price === null) return null
  const lowest = lowestScoredPrice(db, call)
  return lowest === null ? null : (lowest / Number(bid.price)) * 5
}

function questionScore(db: MockDb, call: MockBidCall, bid: MockBid, q: MockBidQuestion) {
  if (q.type === 'price') return priceScore(db, call, bid)
  return mean(countedScores(db, bid, q))
}

/** 0-5, or null while a scored question has no score. */
export function sectionScore(
  db: MockDb,
  call: MockBidCall,
  bid: MockBid,
  section: MockBidSection,
): number | null {
  const scored = questionsOf(db, section).filter((q) => q.type !== 'comment')
  if (!scored.length) return null
  let weighted = 0
  let weights = 0
  for (const q of scored) {
    const score = questionScore(db, call, bid, q)
    if (score === null) return null
    weighted += q.weight * score
    weights += q.weight
  }
  return weighted / weights
}

/** 0-100, or null while a section has no score; scored bids only. */
export function bidTotal(db: MockDb, call: MockBidCall, bid: MockBid): number | null {
  if (!isScored(db, bid)) return null
  let total = 0
  for (const section of sectionsOf(db, call)) {
    const score = sectionScore(db, call, bid, section)
    if (score === null) return null
    total += (section.weight / 100) * score * 20
  }
  return total
}

function disagrees(values: number[]): boolean {
  return values.length >= 2 && Math.max(...values) - Math.min(...values) >= DISAGREEMENT_SPREAD
}

export function sectionDisagreement(db: MockDb, bid: MockBid, section: MockBidSection): boolean {
  return questionsOf(db, section)
    .filter((q) => q.type === 'score')
    .some((q) => disagrees(countedScores(db, bid, q)))
}

/* ------------------------------------------------------------------ */
/* Outputs                                                             */
/* ------------------------------------------------------------------ */

export function bidCallRef(call: MockBidCall): BidCallRef {
  return { id: call.id, title: call.title, status: call.status }
}

export function bidCallRefFor(db: MockDb, callId: string): BidCallRef | null {
  const call = db.bid.calls.find((c) => c.id === callId)
  return call ? bidCallRef(call) : null
}

export function bidCallSummary(db: MockDb, call: MockBidCall): BidCallSummary {
  return {
    ...bidCallRef(call),
    deadline_at: call.deadline_at,
    bid_count: db.bid.bids.filter((b) => b.call_id === call.id).length,
  }
}

/** `IdeaDetail.bid_call`: null without a call and for a guest researcher. */
export function ideaBidCall(db: MockDb, idea: MockIdea, user: MockUser): BidCallSummary | null {
  const call = callOf(db, idea)
  if (!call || !canViewCall(db, idea, user)) return null
  return bidCallSummary(db, call)
}

/** c27 and `bid.manage`: "Start a call for bids". */
export function canCreateCall(db: MockDb, idea: MockIdea, user: MockUser): boolean {
  return (
    isCallManager(db, idea, user) &&
    !callOf(db, idea) &&
    idea.status === 'proposal' &&
    Boolean(proposalOf(db, idea)) &&
    ideaWritable(db, idea)
  )
}

/** The two `IdeaPermissions` flags. */
export function ideaBidPermissions(db: MockDb, idea: MockIdea, user: MockUser) {
  const create = canCreateCall(db, idea, user)
  return {
    can_view_bid_call: canViewCall(db, idea, user) && (Boolean(callOf(db, idea)) || create),
    can_create_bid_call: create,
  }
}

function templateOut(db: MockDb, call: MockBidCall): BidCallTemplate {
  const price = priceQuestion(db, call)
  const idea = ideaOfCall(db, call)
  return {
    scale: [...call.scale],
    sections: sectionsOf(db, call).map((section) => ({
      id: section.id,
      position: section.position,
      title: section.title,
      guidance: section.guidance,
      weight: section.weight,
      has_price: price?.section_id === section.id,
      questions: questionsOf(db, section).map((q) => ({
        id: q.id,
        section_id: q.section_id,
        position: q.position,
        text: q.text,
        guidance: q.guidance,
        type: q.type,
        weight: q.weight,
      })),
      assessors: db.bid.assessors
        .filter((a) => a.section_id === section.id)
        .map((a) => {
          const ref = userRefById(db, a.user_id)
          return {
            user: ref ?? {
              id: a.user_id,
              display_name: 'Unknown user',
              avatar_url: null,
              initials: '?',
            },
            assigned_at: a.assigned_at,
            can_assess: Boolean(idea && assessorEligible(db, idea, a.user_id)),
            progress: progressFor(db, call, bidsOf(db, call), [section.id], a.user_id),
          }
        })
        .sort((a, b) => a.user.display_name.localeCompare(b.user.display_name)),
    })),
    must_haves: mustHavesOf(db, call).map((m) => ({
      id: m.id,
      position: m.position,
      text: m.text,
      kind: m.kind,
      pricing: m.pricing,
    })),
    price_question_id: price?.id ?? null,
    locked: templateLocked(db, call),
  }
}

export function bidCallOut(db: MockDb, call: MockBidCall, user: MockUser): BidCall {
  const idea = ideaOfCall(db, call)
  const manager = Boolean(idea && isCallManager(db, idea, user))
  const agent = call.ai_assessor_id ? agentById(db, call.ai_assessor_id) : undefined
  const awarded = call.awarded_bid_id
    ? db.bid.bids.find((b) => b.id === call.awarded_bid_id)
    : undefined
  return {
    ...bidCallSummary(db, call),
    description: call.description,
    currency: call.currency,
    assessment_due_at: call.assessment_due_at,
    created_by: userRefById(db, call.created_by_id),
    created_at: call.created_at,
    updated_at: call.updated_at,
    template: templateOut(db, call),
    progress: callProgress(db, call),
    ai_assessor: agent ? agentRef(db, agent) : null,
    awarded_at: call.awarded_at,
    awarded_bid: awarded
      ? { id: awarded.id, bidder: awarded.bidder, status: bidStatus(db, awarded) }
      : null,
    award_reason: manager ? call.award_reason : null,
    cancelled_at: call.cancelled_at,
    cancel_reason: manager ? call.cancel_reason : null,
  }
}

/** Agents that may assess bids on this idea now (c10 for `assess_bid`). */
export function assessAgents(db: MockDb, idea: MockIdea): MockAiAgent[] {
  if (!db.aiSettings.enabled) return []
  return db.aiAgents
    .filter((agent) => agentPasses(db, agent, idea, 'assess_bid'))
    .sort((a, b) =>
      (userRefById(db, a.user_id)?.display_name ?? '').localeCompare(
        userRefById(db, b.user_id)?.display_name ?? '',
      ),
    )
}

/** Why "Ask AI to assess" is unavailable (`AiBlockedReason`, in check order). */
export function aiBlockedReason(
  db: MockDb,
  idea: MockIdea,
  call: MockBidCall | undefined,
  user: MockUser,
  bid?: MockBid,
): AiBlockedReason | null {
  if (!isCallManager(db, idea, user)) return 'not_allowed'
  if (!db.aiSettings.enabled) return 'ai_off'
  if (projectOf(db, idea).archived_at !== null) return 'project_archived'
  if (idea.held_for) return 'awaiting_moderation'
  if (idea.status === 'closed') return 'idea_closed'
  if (!call || (call.status !== 'open' && call.status !== 'assessing')) return 'bid_call_state'
  if (bid?.rejected) return 'bid_rejected'
  if (assessAgents(db, idea).length === 0) return 'no_agent'
  return null
}

export function callPermissions(
  db: MockDb,
  idea: MockIdea,
  call: MockBidCall | undefined,
  user: MockUser,
): BidCallPermissions {
  const manager = isCallManager(db, idea, user)
  const writable = ideaWritable(db, idea)
  const live = Boolean(call && !isFinished(call))
  const manage = manager && live && writable
  const sections = call ? assessedSectionIds(db, call, user) : []
  const blocked = aiBlockedReason(db, idea, call, user)
  return {
    can_create: canCreateCall(db, idea, user),
    can_manage_call: manage,
    can_edit_template: manage && Boolean(call && !templateLocked(db, call)),
    can_upload_documents: manage,
    can_decide: manage,
    can_delete_call: Boolean(
      call &&
      manager &&
      (call.status === 'draft' ||
        call.status === 'cancelled' ||
        (call.status === 'awarded' && user.is_platform_admin)),
    ),
    can_view_bids: Boolean(call) && canViewBids(db, idea, user),
    can_see_prices: Boolean(call && canSeePrices(db, call, user)),
    can_view_scores: Boolean(call) && manager,
    can_assess: sections.length > 0 && call?.status === 'assessing',
    assess_section_ids: sections,
    can_request_ai: blocked === null,
    request_ai_blocked_by: blocked,
  }
}

function visibleDocuments(db: MockDb, call: MockBidCall, bid: MockBid, user: MockUser) {
  const all = documentsOf(db, bid)
  if (canSeePrices(db, call, user)) return { shown: all, restricted: 0 }
  const shown = all.filter((d) => !d.pricing)
  return { shown, restricted: all.length - shown.length }
}

function mySections(
  db: MockDb,
  call: MockBidCall,
  bid: MockBid,
  user: MockUser,
): BidSectionState[] {
  const mine = assessedSectionIds(db, call, user)
  return sectionsOf(db, call)
    .filter((s) => mine.includes(s.id))
    .map((section) => {
      const own = db.bid.assessments.find(
        (a) => a.bid_id === bid.id && a.section_id === section.id && a.user_id === user.id,
      )
      const state: EvaluatorState = own
        ? own.status === 'submitted'
          ? 'submitted'
          : 'draft'
        : 'invited'
      return { section: { id: section.id, title: section.title }, state }
    })
}

export function bidOut(db: MockDb, call: MockBidCall, bid: MockBid, user: MockUser): Bid {
  const idea = ideaOfCall(db, call)
  const manager = Boolean(idea && isCallManager(db, idea, user))
  const prices = canSeePrices(db, call, user)
  const docs = visibleDocuments(db, call, bid, user)
  const counts = { met: 0, not_met: 0, missing: 0, unchecked: 0 }
  for (const result of results(db, bid)) counts[result] += 1
  const mine = assessedSectionIds(db, call, user)
  const deadline = call.deadline_at
  return {
    id: bid.id,
    bidder: bid.bidder,
    status: bidStatus(db, bid),
    contact_name: manager ? bid.contact_name : '',
    contact_email: manager ? bid.contact_email : null,
    received_at: bid.received_at,
    late: deadline !== null && bid.received_at > deadline,
    price: prices ? bid.price : null,
    price_hidden: !prices,
    notes: manager ? bid.notes : '',
    rejection:
      manager && bid.rejection
        ? {
            reason: bid.rejection.reason,
            rejected_by: userRefById(db, bid.rejection.rejected_by_id),
            rejected_at: bid.rejection.rejected_at,
            reinstated_at: bid.rejection.reinstated_at,
            reinstated_by: userRefById(db, bid.rejection.reinstated_by_id),
          }
        : null,
    must_haves: counts,
    document_count: docs.shown.length,
    restricted_document_count: docs.restricted,
    progress: bidProgress(db, call, bid),
    my_progress: mine.length ? progressFor(db, call, [bid], mine, user.id) : null,
    my_sections: mySections(db, call, bid, user),
    entered_by: userRefById(db, bid.entered_by_id),
    created_at: bid.created_at,
    updated_at: bid.updated_at,
  }
}

export function documentOut(db: MockDb, doc: MockBidDocument): BidDocument {
  const chars = doc.extraction.state === 'done' ? doc.extraction.text.length : null
  return {
    id: doc.id,
    filename: doc.filename,
    type: doc.type,
    content_type: BID_DOCUMENT_TYPES[doc.type].media,
    size_bytes: doc.size_bytes,
    sha256: doc.sha256,
    must_have_id: doc.must_have_id,
    pricing: doc.pricing,
    active_content: doc.active_content,
    uploaded_by: userRefById(db, doc.uploaded_by_id),
    uploaded_at: doc.uploaded_at,
    extraction: {
      state: doc.extraction.state,
      error: doc.extraction.state === 'failed' ? doc.extraction.error : null,
      chars,
      truncated: doc.extraction.truncated,
      page_count:
        doc.extraction.state === 'done'
          ? Math.max(1, Math.ceil(doc.extraction.text.length / BID_TEXT_PAGE_CHARS))
          : 0,
    },
  }
}

function quoteFound(quote: string, text: string): boolean {
  const normal = (value: string) => value.replace(/\s+/g, ' ').trim()
  const needle = normal(quote)
  return needle.length >= 20 && normal(text).includes(needle)
}

function evidenceOut(db: MockDb, evidence: MockEvidence[]) {
  return evidence.map((e) => {
    const doc = db.bid.documents.find((d) => d.id === e.document_id)
    return {
      document_id: e.document_id,
      quote: e.quote,
      found: Boolean(doc && quoteFound(e.quote, doc.extraction.text)),
    }
  })
}

function aiAgentUser(db: MockDb, agentId: string) {
  const agent = agentById(db, agentId)
  return (
    (agent && userRefById(db, agent.user_id)) ?? {
      id: agentId,
      display_name: 'AI agent',
      avatar_url: null,
      initials: 'AI',
    }
  )
}

function findingsFor(db: MockDb, bid: MockBid, mustHave: MockBidMustHave): BidAiFindingView[] {
  if (mustHave.pricing) return []
  return db.bid.aiAssessments
    .filter((a) => a.bid_id === bid.id)
    .flatMap((a) =>
      a.findings
        .filter((f) => f.must_have_id === mustHave.id)
        .map((f) => ({
          ai_assessment_id: a.id,
          must_have_id: f.must_have_id,
          agent: aiAgentUser(db, a.agent_id),
          finding: f.finding,
          rationale: f.rationale,
          evidence: evidenceOut(db, f.evidence),
          submitted_at: a.submitted_at,
        })),
    )
}

export function mustHaveStates(
  db: MockDb,
  call: MockBidCall,
  bid: MockBid,
  user: MockUser,
): BidMustHaveState[] {
  const prices = canSeePrices(db, call, user)
  return mustHavesOf(db, call).map((mustHave) => {
    const { result, automatic } = mustHaveResult(db, bid, mustHave)
    const decision = decisionOf(db, bid.id, mustHave.id)
    const linked = linkedDocuments(db, bid, mustHave)
    const visible = linked.filter((d) => prices || !d.pricing)
    return {
      must_have: {
        id: mustHave.id,
        position: mustHave.position,
        text: mustHave.text,
        kind: mustHave.kind,
        pricing: mustHave.pricing,
      },
      result,
      automatic,
      decided_by: automatic ? null : userRefById(db, decision?.decided_by_id),
      decided_at: automatic ? null : (decision?.decided_at ?? null),
      note: decision?.note ?? '',
      document_ids: visible.map((d) => d.id),
      restricted_document_count: linked.length - visible.length,
      ai_findings: findingsFor(db, bid, mustHave),
    }
  })
}

export function bidPermissions(
  db: MockDb,
  idea: MockIdea,
  call: MockBidCall,
  bid: MockBid,
  user: MockUser,
): BidPermissions {
  const manager = isCallManager(db, idea, user)
  const manage = manager && !isFinished(call) && ideaWritable(db, idea)
  const mine = assessedSectionIds(db, call, user)
  return {
    can_edit: manage,
    can_delete: manage && (call.status === 'draft' || call.status === 'open'),
    can_upload: manage,
    can_decide_must_haves: manage,
    can_reject: manage && !bid.rejected,
    can_reinstate: manage && bid.rejected,
    reject_suggested: manager && rejectSuggested(db, bid),
    can_assess: mine.length > 0 && call.status === 'assessing' && !bid.rejected,
    can_request_ai: aiBlockedReason(db, idea, call, user, bid) === null,
    can_view_ai: manager,
  }
}

export function bidDetailOut(
  db: MockDb,
  idea: MockIdea,
  call: MockBidCall,
  bid: MockBid,
  user: MockUser,
): BidDetail {
  return {
    ...bidOut(db, call, bid, user),
    documents: visibleDocuments(db, call, bid, user).shown.map((d) => documentOut(db, d)),
    must_have_results: mustHaveStates(db, call, bid, user),
    permissions: bidPermissions(db, idea, call, bid, user),
  }
}

export function myAssessmentOut(
  db: MockDb,
  call: MockBidCall,
  bid: MockBid,
  section: MockBidSection,
  user: MockUser,
): MyBidAssessment {
  const own = db.bid.assessments.find(
    (a) => a.bid_id === bid.id && a.section_id === section.id && a.user_id === user.id,
  )
  const order = questionsOf(db, section).map((q) => q.id)
  return {
    bid_id: bid.id,
    section: { id: section.id, title: section.title },
    state: own ? (own.status === 'submitted' ? 'submitted' : 'draft') : 'invited',
    answers: own
      ? [...own.answers].sort((a, b) => order.indexOf(a.question_id) - order.indexOf(b.question_id))
      : [],
    submitted_at: own?.submitted_at ?? null,
    edited_at: own?.edited_at ?? null,
    can_edit: call.status === 'assessing' && !bid.rejected,
  }
}

function aiScoresFor(db: MockDb, bid: MockBid, section: MockBidSection): BidAiSectionScores[] {
  const ids = questionsOf(db, section).map((q) => q.id)
  return db.bid.aiAssessments
    .filter((a) => a.bid_id === bid.id)
    .map((a) => ({
      ai_assessment_id: a.id,
      agent: aiAgentUser(db, a.agent_id),
      included: a.included,
      submitted_at: a.submitted_at,
      scores: a.scores
        .filter((s) => ids.includes(s.question_id))
        .map((s): BidAiScoreView => ({
          question_id: s.question_id,
          score: s.score,
          rationale: s.rationale,
          evidence: evidenceOut(db, s.evidence),
        })),
    }))
}

function questionStats(
  db: MockDb,
  call: MockBidCall,
  bid: MockBid,
  section: MockBidSection,
): BidQuestionStats[] {
  return questionsOf(db, section)
    .filter((q) => q.type !== 'comment')
    .map((q) => {
      if (q.type === 'price') {
        const score = priceScore(db, call, bid)
        return {
          question_id: q.id,
          type: q.type,
          mean: score === null ? null : roundScore(score, 2),
          min: null,
          max: null,
          count: score === null ? 0 : 1,
          disagreement: false,
        }
      }
      const values = countedScores(db, bid, q)
      const m = mean(values)
      return {
        question_id: q.id,
        type: q.type,
        mean: m === null ? null : roundScore(m, 2),
        min: values.length ? Math.min(...values) : null,
        max: values.length ? Math.max(...values) : null,
        count: values.length,
        disagreement: disagrees(values),
      }
    })
}

export function sectionAssessmentsOut(
  db: MockDb,
  call: MockBidCall,
  bid: MockBid,
  section: MockBidSection,
  user: MockUser,
): BidSectionAssessments {
  const hidden = isPending(db, bid, section.id, user.id)
  if (hidden || bid.rejected) {
    return {
      bid_id: bid.id,
      section: { id: section.id, title: section.title },
      hidden,
      assessments: [],
      ai: [],
      questions: [],
      section_score: null,
    }
  }
  const order = questionsOf(db, section).map((q) => q.id)
  const assessments: BidAssessmentView[] = db.bid.assessments
    .filter((a) => a.bid_id === bid.id && a.section_id === section.id && a.status === 'submitted')
    .map((a) => ({
      assessor: userRefById(db, a.user_id) ?? {
        id: a.user_id,
        display_name: 'Unknown user',
        avatar_url: null,
        initials: '?',
      },
      submitted_at: a.submitted_at ?? a.updated_at,
      edited_at: a.edited_at,
      answers: [...a.answers].sort(
        (x, y) => order.indexOf(x.question_id) - order.indexOf(y.question_id),
      ),
    }))
    .sort((a, b) => a.assessor.display_name.localeCompare(b.assessor.display_name))
  const score = isScored(db, bid) ? sectionScore(db, call, bid, section) : null
  return {
    bid_id: bid.id,
    section: { id: section.id, title: section.title },
    hidden: false,
    assessments,
    ai: aiScoresFor(db, bid, section),
    questions: questionStats(db, call, bid, section),
    section_score: score === null ? null : roundScore(score * 20, 1),
  }
}

export function comparisonOut(db: MockDb, call: MockBidCall, user: MockUser): BidComparison {
  const sections = sectionsOf(db, call)
  const price = priceSection(db, call)
  const all = bidsOf(db, call)
  const rows: (BidComparisonRow & { _total: number | null; _price: number | null })[] = all.map(
    (bid) => {
      const scored = isScored(db, bid)
      const cells: BidSectionScore[] = sections.map((section) => {
        const hidden = isPending(db, bid, section.id, user.id)
        const show = scored && !hidden && !bid.rejected
        const score = show ? sectionScore(db, call, bid, section) : null
        return {
          section_id: section.id,
          score: score === null ? null : roundScore(score * 20, 1),
          hidden,
          progress: progressFor(db, call, [bid], [section.id], null),
          disagreement: show ? sectionDisagreement(db, bid, section) : false,
        }
      })
      const totalHidden = cells.some((c) => c.hidden)
      const total = !totalHidden && scored ? bidTotal(db, call, bid) : null
      const ps = priceScore(db, call, bid)
      return {
        bid: { id: bid.id, bidder: bid.bidder, status: bidStatus(db, bid) },
        received_at: bid.received_at,
        late: call.deadline_at !== null && bid.received_at > call.deadline_at,
        price: bid.price,
        price_score: ps === null ? null : roundScore(ps, 2),
        sections: cells,
        total: total === null ? null : roundScore(total, 1),
        total_hidden: totalHidden,
        rank: null,
        tied: false,
        ai_included: db.bid.aiAssessments.some((a) => a.bid_id === bid.id && a.included),
        progress: bidProgress(db, call, bid),
        _total: total,
        _price: bid.price === null ? null : Number(bid.price),
      }
    },
  )
  const rankingHidden = rows.some((row, i) => row.total_hidden && !all[i]?.rejected)
  const byReceived = (a: (typeof rows)[number], b: (typeof rows)[number]) =>
    a.received_at.localeCompare(b.received_at) || a.bid.id.localeCompare(b.bid.id)
  let ordered: typeof rows
  if (rankingHidden) {
    ordered = [...rows].sort(byReceived)
  } else {
    const ranked = rows
      .filter((r) => r._total !== null && r.bid.status !== 'rejected')
      .sort(
        (a, b) =>
          (b.total ?? 0) - (a.total ?? 0) ||
          Number(a._price === null) - Number(b._price === null) ||
          (a._price ?? 0) - (b._price ?? 0) ||
          byReceived(a, b),
      )
    let rank = 0
    let previous: number | null = null
    ranked.forEach((row, index) => {
      if (row.total !== previous) {
        rank = index + 1
        previous = row.total
      }
      row.rank = rank
    })
    for (const row of ranked) row.tied = ranked.filter((r) => r.total === row.total).length > 1
    const others = rows
      .filter((r) => !ranked.includes(r) && r.bid.status !== 'rejected')
      .sort(byReceived)
    const rejected = rows.filter((r) => r.bid.status === 'rejected').sort(byReceived)
    ordered = [...ranked, ...others, ...rejected]
  }
  const lowest = lowestScoredPrice(db, call)
  const progress = callProgress(db, call)
  return {
    call: bidCallRef(call),
    currency: call.currency,
    sections: sections.map((s) => ({ id: s.id, title: s.title, weight: s.weight })),
    price_section_id: price?.id ?? null,
    lowest_price: lowest === null ? null : lowest.toFixed(2),
    ranking_hidden: rankingHidden,
    rows: ordered.map(stripPrivate),
    progress,
    complete: progress.total > 0 && progress.submitted >= progress.total,
  }
}

/** A row without the comparison's own sort keys. */
function stripPrivate(
  row: BidComparisonRow & { _total: number | null; _price: number | null },
): BidComparisonRow {
  const out: Partial<typeof row> = { ...row }
  delete out._total
  delete out._price
  return out as BidComparisonRow
}

export function aiAssessmentOut(
  db: MockDb,
  call: MockBidCall,
  bid: MockBid,
  assessment: MockBidAiAssessment,
  user: MockUser,
): BidAiAssessment {
  const sections = sectionsOf(db, call)
  const hidden = sections.filter((s) => isPending(db, bid, s.id, user.id)).map((s) => s.id)
  const hiddenQuestions = new Set(
    db.bid.questions.filter((q) => hidden.includes(q.section_id)).map((q) => q.id),
  )
  const scores = assessment.scores.filter((s) => !hiddenQuestions.has(s.question_id))
  const evidence = [
    ...assessment.scores.flatMap((s) => s.evidence),
    ...assessment.findings.flatMap((f) => f.evidence),
  ]
  return {
    id: assessment.id,
    bid_id: bid.id,
    agent: aiAgentUser(db, assessment.agent_id),
    submitted_at: assessment.submitted_at,
    included: assessment.included,
    scores: scores.map((s) => ({
      question_id: s.question_id,
      score: s.score,
      rationale: s.rationale,
      evidence: evidenceOut(db, s.evidence),
    })),
    hidden_section_ids: hidden,
    findings: assessment.findings
      .filter((f) => !mustHavesOf(db, call).find((m) => m.id === f.must_have_id)?.pricing)
      .map((f) => ({
        ai_assessment_id: assessment.id,
        must_have_id: f.must_have_id,
        agent: aiAgentUser(db, assessment.agent_id),
        finding: f.finding,
        rationale: f.rationale,
        evidence: evidenceOut(db, f.evidence),
        submitted_at: assessment.submitted_at,
      })),
    quotes_not_found: evidenceOut(db, evidence).filter((e) => !e.found).length,
  }
}

export function templateResponse(db: MockDb, projectId: string, user: MockUser): BidTemplate {
  const template = templateOf(db, projectId)
  const project = db.projects.find((p) => p.id === projectId)
  return {
    scale: [...template.scale],
    sections: template.sections.map((s) => ({
      title: s.title,
      guidance: s.guidance,
      weight: s.weight,
      questions: s.questions.map((q) => ({ ...q })),
    })),
    must_haves: template.must_haves.map((m) => ({ ...m })),
    updated_at: template.updated_at,
    updated_by: userRefById(db, template.updated_by_id),
    can_edit: Boolean(project && isProjectAdmin(db, project, user)),
  }
}

/* ------------------------------------------------------------------ */
/* My work, counts and notifications (section 11)                      */
/* ------------------------------------------------------------------ */

/** Assessments a person owes: their sections x the call's bids that aren't rejected. */
function owed(db: MockDb, call: MockBidCall, user: MockUser): { owed: number; total: number } {
  const mine = assessedSectionIds(db, call, user)
  let owedCount = 0
  let total = 0
  for (const bid of bidsOf(db, call)) {
    if (bid.rejected) continue
    for (const sectionId of mine) {
      total += 1
      if (!submittedBy(db, bid.id, sectionId, user.id)) owedCount += 1
    }
  }
  return { owed: owedCount, total }
}

function workCall(db: MockDb, call: MockBidCall): MockIdea | null {
  if (call.status !== 'assessing') return null
  const idea = ideaOfCall(db, call)
  if (!idea || idea.status === 'closed' || idea.held_for) return null
  if (projectOf(db, idea).archived_at !== null) return null
  return idea
}

export function bidsToAssess(db: MockDb, user: MockUser): WorkBidAssessment[] {
  const rows: WorkBidAssessment[] = []
  for (const call of db.bid.calls) {
    const idea = workCall(db, call)
    if (!idea) continue
    const { owed: count, total } = owed(db, call, user)
    if (count === 0) continue
    const mine = assessedSectionIds(db, call, user)
    rows.push({
      idea: ideaRef(db, idea),
      call: bidCallRef(call),
      sections: sectionsOf(db, call)
        .filter((s) => mine.includes(s.id))
        .map((s) => ({ id: s.id, title: s.title })),
      due_at: call.assessment_due_at,
      overdue: call.assessment_due_at !== null && Date.parse(call.assessment_due_at) < Date.now(),
      progress: { submitted: total - count, total },
    })
  }
  return rows.sort((a, b) => (a.due_at ?? '9999').localeCompare(b.due_at ?? '9999')).slice(0, 50)
}

export function bidAssessmentCounts(db: MockDb, user: MockUser): { due: number; overdue: number } {
  let due = 0
  let overdue = 0
  for (const call of db.bid.calls) {
    if (!workCall(db, call)) continue
    const { owed: count } = owed(db, call, user)
    due += count
    if (call.assessment_due_at && Date.parse(call.assessment_due_at) < Date.now()) overdue += count
  }
  return { due, overdue }
}

/** Inbox items of the bid types are shown only while their reason holds. */
export function bidNotificationVisible(
  db: MockDb,
  n: MockNotification,
  idea: MockIdea,
  viewer: MockUser,
): boolean {
  if (
    n.type !== 'assessor_assigned' &&
    n.type !== 'assessment_reminder' &&
    n.type !== 'assessments_complete'
  ) {
    return true
  }
  if (isResearchGuest(db, idea, viewer)) return false
  const call = db.bid.calls.find((c) => c.id === n.payload.call_id)
  if (!call) return false
  if (n.type === 'assessments_complete') return isCallManager(db, idea, viewer)
  return assessedSectionIds(db, call, viewer).length > 0
}

/** Assess runs name bids: only people who see the bids see them (review S9). */
export function runVisible(db: MockDb, run: MockAiRun, user: MockUser): boolean {
  if (run.kind !== 'assess_bid') return true
  const idea = db.ideas.find((i) => i.id === run.idea_id)
  return Boolean(idea && canViewBids(db, idea, user))
}
