/**
 * Phase 10 (contract-phase10): calls for bids, the project's bid template, bids and
 * their documents, must-haves, assessors and assessments, the comparison, the AI
 * assessor, the award and the report. 34 operations. Check order as the contract's
 * section 2.1: 401 → 404 (idea, call) → 403 (the call-level rule) → 404 (bid, section,
 * document of another call; a rejected bid for an assessor; a pricing document without
 * the price) → 403 c29 → 422 → 409 (archived, held, closed, then the call's state).
 */
import type { BidCallStatus, BidDocumentType, BidQuestionType, MustHaveKind } from '@/api/types'

import { recordAudit } from '@/mocks/access'
import { activeAssessRun, cancelAssessRuns, createAssessRun } from '@/mocks/bid-runs'
import {
  aiAssessmentOut,
  aiBlockedReason,
  assessAgents,
  assessedSectionIds,
  assessorEligible,
  BID_CALL_STORAGE_MAX_BYTES,
  BID_DOCUMENT_MAX_BYTES,
  BID_DOCUMENT_TYPES,
  BID_DOCUMENTS_PER_BID_MAX,
  BID_FILENAME_MAX_LENGTH,
  BID_TEXT_PAGE_CHARS,
  bidCallOut,
  bidCallSummary,
  bidDetailOut,
  bidOut,
  bidsOf,
  callOf,
  callPermissions,
  callProgress,
  canSeePrices,
  canViewBids,
  comparisonOut,
  documentOut,
  documentsOf,
  isCallManager,
  isFinished,
  isPending,
  isScored,
  mustHavesOf,
  mustHaveStates,
  myAssessmentOut,
  priceQuestion,
  questionsOf,
  sectionAssessmentsOut,
  sectionsOf,
  templateLocked,
  templateOf,
  templateResponse,
  type MockBid,
  type MockBidCall,
  type MockBidDocument,
  type MockBidMustHave,
  type MockBidQuestion,
  type MockBidSection,
  type MockTemplateMustHave,
  type MockTemplateSection,
} from '@/mocks/bids'
import { ID_KIND, newId, type MockDb, type MockIdea, type MockUser } from '@/mocks/db'
import { findUser, ideaKey, isProjectAdmin, projectOf } from '@/mocks/domain'
import { agentById, runOut } from '@/mocks/ai'
import {
  allowOnly,
  conflict,
  created,
  failValidation,
  forbidden,
  json,
  noContent,
  notFound,
  problemResponse,
  queryBool,
  queryUuid,
  readJson,
  route,
  tooManyAttempts,
  type FieldIssue,
  type RouteContext,
} from '@/mocks/http'
import { notify } from '@/mocks/notifications'
import { proposalOf } from '@/mocks/proposals'

import { emit, isUuid, uuidParam, viewIdea, viewProject } from './common'

const HOUR = 3_600_000
const AI_REQUESTS_PER_HOUR = 20

/* ------------------------------------------------------------------ */
/* Lookups in the contract's order                                     */
/* ------------------------------------------------------------------ */

interface CallContext {
  idea: MockIdea
  call: MockBidCall
}

/** 404 the idea (a guest researcher at any bid route), then the call. */
function loadCall(ctx: RouteContext): CallContext {
  const idea = viewIdea(ctx)
  const call = callOf(ctx.db, idea)
  if (!call) notFound('This idea has no call for bids.')
  return { idea, call }
}

function requireManager(ctx: RouteContext, idea: MockIdea): void {
  if (!isCallManager(ctx.db, idea, ctx.user)) {
    forbidden('forbidden', 'Only the idea’s owner and admins can do this.')
  }
}

function requireViewBids(ctx: RouteContext, idea: MockIdea): void {
  if (!canViewBids(ctx.db, idea, ctx.user)) {
    forbidden('forbidden', 'Only the call’s managers and assessors can see its bids.')
  }
}

/** A bid of this call; a rejected one is 404 for an assessor who isn't a manager. */
function findBid(ctx: RouteContext, { idea, call }: CallContext): MockBid {
  const id = uuidParam(ctx, 'bidId')
  const bid = ctx.db.bid.bids.find((b) => b.id === id && b.call_id === call.id)
  if (!bid) notFound('Bid not found.')
  if (bid.rejected && !isCallManager(ctx.db, idea, ctx.user)) notFound('Bid not found.')
  return bid
}

function findSection(ctx: RouteContext, call: MockBidCall): MockBidSection {
  const id = uuidParam(ctx, 'sectionId')
  const section = ctx.db.bid.sections.find((s) => s.id === id && s.call_id === call.id)
  if (!section) notFound('Section not found.')
  return section
}

function findDocument(ctx: RouteContext, call: MockBidCall, bid: MockBid): MockBidDocument {
  const id = uuidParam(ctx, 'documentId')
  const doc = ctx.db.bid.documents.find((d) => d.id === id && d.bid_id === bid.id)
  if (!doc || (doc.pricing && !canSeePrices(ctx.db, call, ctx.user))) {
    notFound('Document not found.')
  }
  return doc
}

/** c29: you assess this section (403 `not_section_assessor`). */
function requireSectionAssessor(ctx: RouteContext, call: MockBidCall, section: MockBidSection) {
  if (!assessedSectionIds(ctx.db, call, ctx.user).includes(section.id)) {
    forbidden('not_section_assessor', 'You don’t assess this section.')
  }
}

/** The idea's 409s: archived, held for moderation, closed (c5). */
function ensureIdeaOpen(db: MockDb, idea: MockIdea, { allowClosed = false } = {}): void {
  if (projectOf(db, idea).archived_at !== null) {
    conflict('project_archived', 'This project is archived.')
  }
  if (idea.held_for) conflict('awaiting_moderation', 'This idea is waiting for moderation.')
  if (!allowClosed && idea.status === 'closed') conflict('idea_closed', 'This idea is closed.')
}

function ensureNotFinished(call: MockBidCall): void {
  if (isFinished(call)) {
    conflict('bid_call_finished', 'This call for bids is finished: it is read-only.')
  }
}

function touch(call: MockBidCall): void {
  call.updated_at = new Date().toISOString()
}

function audit(
  ctx: RouteContext,
  idea: MockIdea,
  action: Parameters<typeof recordAudit>[2],
  details: Record<string, unknown>,
) {
  recordAudit(ctx.db, ctx.user, action, { type: 'idea', id: idea.id }, details, idea.project_id)
}

function callView(ctx: RouteContext, idea: MockIdea) {
  const call = callOf(ctx.db, idea)
  const { db, user } = ctx
  const manager = isCallManager(db, idea, user)
  return {
    summary: call ? bidCallSummary(db, call) : null,
    call: call && canViewBids(db, idea, user) ? bidCallOut(db, call, user) : null,
    ai_agents: manager ? assessAgents(db, idea).map((agent) => agentRefOut(db, agent.id)) : [],
    permissions: callPermissions(db, idea, call, user),
  }
}

function agentRefOut(db: MockDb, agentId: string) {
  const agent = agentById(db, agentId)
  const user = agent ? findUser(db, agent.user_id) : undefined
  return {
    id: agentId,
    display_name: user?.display_name ?? 'AI agent',
    purposes: agent?.purposes ?? [],
    user_id: agent?.user_id ?? agentId,
  }
}

/* ------------------------------------------------------------------ */
/* Body fields                                                         */
/* ------------------------------------------------------------------ */

// eslint-disable-next-line no-control-regex -- refusing control characters is the point
const CONTROL = /[\u0000-\u001f\u007f\u2028\u2029\u202a-\u202e\u2066-\u2069]/

function issue(loc: (string | number)[], msg: string, type = 'value_error'): FieldIssue {
  return { loc: ['body', ...loc], msg, type }
}

function text(
  value: unknown,
  loc: (string | number)[],
  { min = 0, max, line = false }: { min?: number; max: number; line?: boolean },
): string {
  if (typeof value !== 'string')
    failValidation([issue(loc, 'Input should be a valid string', 'string_type')])
  const trimmed = value.trim()
  if (trimmed.length < min)
    failValidation([
      issue(loc, `At least ${min} character${min === 1 ? '' : 's'}`, 'string_too_short'),
    ])
  if (trimmed.length > max)
    failValidation([issue(loc, `At most ${max} characters`, 'string_too_long')])
  if (line && CONTROL.test(trimmed)) failValidation([issue(loc, 'One line of text', 'value_error')])
  return trimmed
}

function optionalText(value: unknown, loc: (string | number)[], max: number, line = false): string {
  return value === undefined || value === null ? '' : text(value, loc, { max, line })
}

function int(value: unknown, loc: (string | number)[], min: number, max: number): number {
  if (typeof value !== 'number' || !Number.isInteger(value) || value < min || value > max) {
    failValidation([issue(loc, `A whole number from ${min} to ${max}`, 'int_parsing')])
  }
  return value
}

function list(value: unknown, loc: (string | number)[], min: number, max: number): unknown[] {
  if (!Array.isArray(value))
    failValidation([issue(loc, 'Input should be a valid list', 'list_type')])
  if (value.length < min)
    failValidation([issue(loc, `At least ${min} item${min === 1 ? '' : 's'}`, 'too_short')])
  if (value.length > max) failValidation([issue(loc, `At most ${max} items`, 'too_long')])
  return value
}

function record(value: unknown, loc: (string | number)[]): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    failValidation([issue(loc, 'Input should be an object', 'model_type')])
  }
  return value as Record<string, unknown>
}

function onlyKeys(body: Record<string, unknown>, loc: (string | number)[], keys: string[]) {
  const extra = Object.keys(body).filter((key) => !keys.includes(key))
  if (extra.length) {
    failValidation(
      extra.map((key) => issue([...loc, key], 'Extra inputs are not permitted', 'extra_forbidden')),
    )
  }
}

/** A `DueAt`: ISO with an offset, at most a year back and five years ahead (null allowed). */
function dueAt(value: unknown, loc: (string | number)[]): string | null {
  if (value === null || value === undefined) return null
  if (
    typeof value !== 'string' ||
    !/[zZ]|[+-]\d\d:?\d\d$/.test(value) ||
    Number.isNaN(Date.parse(value))
  ) {
    failValidation([issue(loc, 'A date and time with an offset', 'datetime_parsing')])
  }
  const at = Date.parse(value)
  if (at < Date.now() - 366 * 24 * HOUR || at > Date.now() + 5 * 366 * 24 * HOUR) {
    failValidation([issue(loc, 'Too far in the past or the future', 'value_error')])
  }
  return new Date(at).toISOString()
}

/* ------------------------------------------------------------------ */
/* Templates (contract-phase10 §4)                                     */
/* ------------------------------------------------------------------ */

interface ParsedQuestion {
  id: string | null
  text: string
  guidance: string
  type: BidQuestionType
  weight: number
}
interface ParsedSection {
  id: string | null
  title: string
  guidance: string
  weight: number
  questions: ParsedQuestion[]
}
interface ParsedMustHave {
  id: string | null
  text: string
  kind: MustHaveKind
  pricing: boolean
}
interface ParsedTemplate {
  scale: string[]
  sections: ParsedSection[]
  must_haves: ParsedMustHave[]
}

const QUESTION_TYPES: BidQuestionType[] = ['score', 'price', 'comment']
const MUST_HAVE_KINDS: MustHaveKind[] = ['document', 'confirmation']

function optionalId(value: unknown, loc: (string | number)[], withIds: boolean): string | null {
  if (!withIds || value === undefined || value === null) return null
  if (!isUuid(value)) failValidation([issue(loc, 'Input should be a valid UUID', 'uuid_parsing')])
  return value.toLowerCase()
}

function parseTemplate(body: Record<string, unknown>, withIds: boolean): ParsedTemplate {
  onlyKeys(body, [], ['scale', 'sections', 'must_haves'])
  const scale = list(body.scale, ['scale'], 6, 6).map((label, i) =>
    text(label, ['scale', i], { min: 1, max: 80, line: true }),
  )
  const sections = list(body.sections, ['sections'], 1, 8).map((raw, i): ParsedSection => {
    const s = record(raw, ['sections', i])
    onlyKeys(
      s,
      ['sections', i],
      [...(withIds ? ['id'] : []), 'title', 'guidance', 'weight', 'questions'],
    )
    const questions = list(s.questions, ['sections', i, 'questions'], 1, 15).map(
      (rawQ, j): ParsedQuestion => {
        const q = record(rawQ, ['sections', i, 'questions', j])
        const loc = ['sections', i, 'questions', j]
        onlyKeys(q, loc, [...(withIds ? ['id'] : []), 'text', 'guidance', 'type', 'weight'])
        const type = (q.type ?? 'score') as BidQuestionType
        if (!QUESTION_TYPES.includes(type))
          failValidation([issue([...loc, 'type'], 'score, price or comment', 'enum')])
        let weight: number
        if (type === 'comment') {
          if (q.weight !== undefined && q.weight !== null && q.weight !== 0) {
            failValidation([issue([...loc, 'weight'], 'Comment questions aren’t scored: weight 0')])
          }
          weight = 0
        } else {
          weight =
            q.weight === undefined || q.weight === null
              ? 1
              : int(q.weight, [...loc, 'weight'], 1, 100)
        }
        return {
          id: optionalId(q.id, [...loc, 'id'], withIds),
          text: text(q.text, [...loc, 'text'], { min: 1, max: 300, line: true }),
          guidance: optionalText(q.guidance, [...loc, 'guidance'], 1000),
          type,
          weight,
        }
      },
    )
    if (!questions.some((q) => q.type === 'score')) {
      failValidation([
        issue(['sections', i, 'questions'], 'Every section needs at least one score question'),
      ])
    }
    return {
      id: optionalId(s.id, ['sections', i, 'id'], withIds),
      title: text(s.title, ['sections', i, 'title'], { min: 1, max: 60, line: true }),
      guidance: optionalText(s.guidance, ['sections', i, 'guidance'], 500),
      weight: int(s.weight, ['sections', i, 'weight'], 1, 100),
      questions,
    }
  })
  const mustHaves = list(body.must_haves ?? [], ['must_haves'], 0, 20).map(
    (raw, i): ParsedMustHave => {
      const m = record(raw, ['must_haves', i])
      onlyKeys(m, ['must_haves', i], [...(withIds ? ['id'] : []), 'text', 'kind', 'pricing'])
      const kind = m.kind as MustHaveKind
      if (!MUST_HAVE_KINDS.includes(kind))
        failValidation([issue(['must_haves', i, 'kind'], 'document or confirmation', 'enum')])
      const pricing = m.pricing === true
      if (pricing && kind !== 'document') {
        failValidation([
          issue(['must_haves', i, 'pricing'], 'Only a document must-have can be a pricing one'),
        ])
      }
      return {
        id: optionalId(m.id, ['must_haves', i, 'id'], withIds),
        text: text(m.text, ['must_haves', i, 'text'], { min: 1, max: 200, line: true }),
        kind,
        pricing,
      }
    },
  )
  if (sections.reduce((sum, s) => sum + s.weight, 0) !== 100) {
    failValidation([issue(['sections'], 'The section weights must add up to 100')])
  }
  const titles = sections.map((s) => s.title.toLowerCase())
  if (new Set(titles).size !== titles.length)
    failValidation([issue(['sections'], 'Section titles must be unique')])
  if (sections.flatMap((s) => s.questions).filter((q) => q.type === 'price').length > 1) {
    failValidation([issue(['sections'], 'A template has at most one price question')])
  }
  const texts = mustHaves.map((m) => m.text.toLowerCase())
  if (new Set(texts).size !== texts.length)
    failValidation([issue(['must_haves'], 'Must-haves must be unique')])
  if (withIds) {
    const ids = [
      ...sections.map((s) => s.id),
      ...sections.flatMap((s) => s.questions.map((q) => q.id)),
      ...mustHaves.map((m) => m.id),
    ].filter((v): v is string => v !== null)
    if (new Set(ids).size !== ids.length)
      failValidation([issue([], 'An id appears more than once')])
  }
  return { scale, sections, must_haves: mustHaves }
}

/** Replaces the call's copy (items with an id keep it; new ones get one; the rest go). */
function replaceCallTemplate(db: MockDb, call: MockBidCall, parsed: ParsedTemplate): boolean {
  const known = {
    sections: new Set(sectionsOf(db, call).map((s) => s.id)),
    questions: new Set(db.bid.questions.filter((q) => q.call_id === call.id).map((q) => q.id)),
    mustHaves: new Set(mustHavesOf(db, call).map((m) => m.id)),
  }
  const unknown = (set: Set<string>, value: string | null) => value !== null && !set.has(value)
  parsed.sections.forEach((s, i) => {
    if (unknown(known.sections, s.id))
      failValidation(
        [issue(['sections', i, 'id'], 'Not a section of this call', 'unknown_template_item')],
        'unknown_template_item',
      )
    s.questions.forEach((q, j) => {
      if (unknown(known.questions, q.id))
        failValidation(
          [
            issue(
              ['sections', i, 'questions', j, 'id'],
              'Not a question of this call',
              'unknown_template_item',
            ),
          ],
          'unknown_template_item',
        )
    })
  })
  parsed.must_haves.forEach((m, i) => {
    if (unknown(known.mustHaves, m.id))
      failValidation(
        [issue(['must_haves', i, 'id'], 'Not a must-have of this call', 'unknown_template_item')],
        'unknown_template_item',
      )
  })
  const before = JSON.stringify(templateSnapshot(db, call))
  const keepSections = new Set<string>()
  const keepQuestions = new Set<string>()
  const keepMustHaves = new Set<string>()
  const sections: MockBidSection[] = []
  const questions: MockBidQuestion[] = []
  parsed.sections.forEach((s, position) => {
    const id = s.id ?? newId(db, ID_KIND.phase5)
    keepSections.add(id)
    sections.push({
      id,
      call_id: call.id,
      position,
      title: s.title,
      guidance: s.guidance,
      weight: s.weight,
    })
    s.questions.forEach((q, qPosition) => {
      const qid = q.id ?? newId(db, ID_KIND.phase5)
      keepQuestions.add(qid)
      questions.push({
        id: qid,
        call_id: call.id,
        section_id: id,
        position: qPosition,
        text: q.text,
        guidance: q.guidance,
        type: q.type,
        weight: q.weight,
      })
    })
  })
  const mustHaves: MockBidMustHave[] = parsed.must_haves.map((m, position) => {
    const id = m.id ?? newId(db, ID_KIND.phase5)
    keepMustHaves.add(id)
    return { id, call_id: call.id, position, text: m.text, kind: m.kind, pricing: m.pricing }
  })
  const bidIds = new Set(bidsOf(db, call).map((b) => b.id))
  db.bid.sections = [...db.bid.sections.filter((s) => s.call_id !== call.id), ...sections]
  db.bid.questions = [...db.bid.questions.filter((q) => q.call_id !== call.id), ...questions]
  db.bid.mustHaves = [...db.bid.mustHaves.filter((m) => m.call_id !== call.id), ...mustHaves]
  db.bid.assessors = db.bid.assessors.filter(
    (a) => a.call_id !== call.id || keepSections.has(a.section_id),
  )
  db.bid.assessments = db.bid.assessments.filter(
    (a) => a.call_id !== call.id || keepSections.has(a.section_id),
  )
  db.bid.decisions = db.bid.decisions.filter(
    (d) => !bidIds.has(d.bid_id) || keepMustHaves.has(d.must_have_id),
  )
  for (const doc of db.bid.documents) {
    if (bidIds.has(doc.bid_id) && doc.must_have_id && !keepMustHaves.has(doc.must_have_id)) {
      doc.must_have_id = null
    }
    // A pricing must-have's files stay pricing documents.
    const mustHave = mustHaves.find((m) => m.id === doc.must_have_id)
    if (mustHave?.pricing) doc.pricing = true
  }
  call.scale = [...parsed.scale]
  for (const assessment of db.bid.assessments) {
    if (assessment.call_id !== call.id) continue
    assessment.answers = assessment.answers.filter((a) => keepQuestions.has(a.question_id))
  }
  const changed = before !== JSON.stringify(templateSnapshot(db, call))
  if (changed) {
    // Any change clears the AI's assessments (they answered the old questions).
    db.bid.aiAssessments = db.bid.aiAssessments.filter((a) => !bidIds.has(a.bid_id))
    cancelAssessRuns(db, [...bidIds])
  }
  return changed
}

function templateSnapshot(db: MockDb, call: MockBidCall) {
  return {
    scale: call.scale,
    sections: sectionsOf(db, call).map((s) => ({
      id: s.id,
      title: s.title,
      guidance: s.guidance,
      weight: s.weight,
      questions: questionsOf(db, s).map((q) => ({ ...q, position: undefined })),
    })),
    mustHaves: mustHavesOf(db, call).map((m) => ({ ...m, position: undefined })),
  }
}

function copyTemplate(db: MockDb, call: MockBidCall, projectId: string): void {
  const template = templateOf(db, projectId)
  call.scale = [...template.scale]
  template.sections.forEach((s: MockTemplateSection, position) => {
    const sectionId = newId(db, ID_KIND.phase5)
    db.bid.sections.push({
      id: sectionId,
      call_id: call.id,
      position,
      title: s.title,
      guidance: s.guidance,
      weight: s.weight,
    })
    s.questions.forEach((q, qPosition) => {
      db.bid.questions.push({
        id: newId(db, ID_KIND.phase5),
        call_id: call.id,
        section_id: sectionId,
        position: qPosition,
        ...q,
      })
    })
  })
  template.must_haves.forEach((m: MockTemplateMustHave, position) => {
    db.bid.mustHaves.push({ id: newId(db, ID_KIND.phase5), call_id: call.id, position, ...m })
  })
}

/* ------------------------------------------------------------------ */
/* Assessments complete (section 8 progress, section 11)               */
/* ------------------------------------------------------------------ */

function checkComplete(ctx: RouteContext, idea: MockIdea, call: MockBidCall): void {
  if (call.complete_notified || call.status !== 'assessing') return
  const progress = callProgress(ctx.db, call)
  if (progress.total === 0 || progress.submitted < progress.total) return
  call.complete_notified = true
  const bids = bidsOf(ctx.db, call).filter((b) => !b.rejected).length
  const people = [
    ...new Set([idea.owner_id, call.created_by_id].filter((v): v is string => Boolean(v))),
  ]
  notify(
    ctx.db,
    idea,
    null,
    people.map((userId) => ({
      userId,
      type: 'assessments_complete' as const,
      payload: { call_id: call.id, bid_count: bids, assessment_count: progress.submitted },
      dedupeKey: `assessments_complete:${call.id}`,
    })),
  )
}

/* ------------------------------------------------------------------ */
/* Documents: sniffing the bytes (section 6.1)                         */
/* ------------------------------------------------------------------ */

function startsWith(bytes: Uint8Array, prefix: number[]): boolean {
  return prefix.every((b, i) => bytes[i] === b)
}

function latin1(bytes: Uint8Array, limit = 200_000): string {
  let out = ''
  for (let i = 0; i < Math.min(bytes.length, limit); i++) out += String.fromCharCode(bytes[i] ?? 0)
  return out
}

/** The type the bytes are (the mock's simplified version of the API's sniffing). */
function sniff(bytes: Uint8Array, filename: string): BidDocumentType {
  if (bytes.length === 0) throw unsupported()
  const lower = filename.toLowerCase()
  if (startsWith(bytes, [0x25, 0x50, 0x44, 0x46, 0x2d])) return 'pdf'
  if (startsWith(bytes, [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])) return 'png'
  if (startsWith(bytes, [0xff, 0xd8, 0xff])) return 'jpeg'
  if (startsWith(bytes, [0x50, 0x4b, 0x03, 0x04])) {
    const names = latin1(bytes)
    if (
      /vbaProject\.bin|vbaData\.xml|activeX\/|oleObject[^/]*\.bin|macroEnabled|\.(docm|xlsm|pptm|xlsb)\b|(^|\/)(Basic|Scripts)\//.test(
        names,
      )
    ) {
      throw macro()
    }
    if (names.includes('wordprocessingml.document.main+xml') || lower.endsWith('.docx'))
      return 'docx'
    if (names.includes('spreadsheetml.sheet.main+xml') || lower.endsWith('.xlsx')) return 'xlsx'
    if (names.includes('presentationml.presentation.main+xml') || lower.endsWith('.pptx'))
      return 'pptx'
    if (names.includes('opendocument.text') || lower.endsWith('.odt')) return 'odt'
    if (names.includes('opendocument.spreadsheet') || lower.endsWith('.ods')) return 'ods'
    throw unsupported()
  }
  if (startsWith(bytes, [0xd0, 0xcf, 0x11, 0xe0])) throw unsupported() // OLE: encrypted Office or .doc
  if (bytes.includes(0)) throw unsupported()
  return lower.endsWith('.csv') ? 'csv' : 'txt'
}

function unsupported(): Response {
  return problemResponse(415, 'unsupported_document_type', 'That file type can’t be uploaded.')
}

function macro(): Response {
  return problemResponse(
    415,
    'macro_document',
    'Files with macros or active content can’t be uploaded.',
  )
}

async function sha256(bytes: Uint8Array): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', bytes.slice().buffer)
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, '0')).join('')
}

function filenameParam(ctx: RouteContext): string {
  const raw = ctx.url.searchParams.get('filename')
  const loc = ['query', 'filename']
  if (raw === null || raw.trim() === '')
    failValidation([{ loc, msg: 'Field required', type: 'missing' }])
  const name = raw.trim()
  if (name.length > BID_FILENAME_MAX_LENGTH)
    failValidation([{ loc, msg: 'At most 200 characters', type: 'string_too_long' }])
  if (/[/\\]/.test(name))
    failValidation([{ loc, msg: 'A file name, without folders (no / or \\)', type: 'value_error' }])
  if (name.startsWith('.'))
    failValidation([{ loc, msg: 'The file name can’t start with a dot', type: 'value_error' }])
  if (CONTROL.test(name) || /[\u{e0000}-\u{e007f}]/u.test(name))
    failValidation([{ loc, msg: 'One line of text', type: 'value_error' }])
  return name
}

/** The stored name ends with the type's extension (the stem cut to fit 200 characters). */
function storedName(name: string, type: BidDocumentType): string {
  const { ext } = BID_DOCUMENT_TYPES[type]
  if (ext.some((e) => name.toLowerCase().endsWith(e))) return name
  const extension = ext[0] ?? ''
  return name.slice(0, BID_FILENAME_MAX_LENGTH - extension.length) + extension
}

function decodeText(bytes: Uint8Array): string {
  try {
    return new TextDecoder('utf-8', { fatal: true }).decode(bytes)
  } catch {
    return new TextDecoder('windows-1252').decode(bytes)
  }
}

/** The pretend extraction worker: a moment later, the text (or why not). */
function extractLater(db: MockDb, doc: MockBidDocument): void {
  const finish = () => {
    if (!db.bid.documents.includes(doc)) return
    const name = doc.filename.toLowerCase()
    if (name.includes('damaged')) {
      doc.extraction = { state: 'failed', error: 'damaged', text: '', truncated: false }
    } else if (name.includes('encrypted')) {
      doc.extraction = { state: 'failed', error: 'encrypted', text: '', truncated: false }
    } else if (doc.type === 'png' || doc.type === 'jpeg') {
      doc.extraction = { state: 'no_text', error: null, text: '', truncated: false }
    } else if (doc.type === 'txt' || doc.type === 'csv') {
      const value = decodeText(doc.bytes).replaceAll(String.fromCharCode(0), '')
      doc.extraction = value.trim()
        ? {
            state: 'done',
            error: null,
            text: value.slice(0, 2_000_000),
            truncated: value.length > 2_000_000,
          }
        : { state: 'no_text', error: null, text: '', truncated: false }
    } else {
      doc.extraction = {
        state: 'done',
        error: null,
        text: `${doc.filename}\n\nThe text of this document as the extraction read it (mock). It would hold the bidder's own words, shown as plain text.`,
        truncated: false,
      }
    }
    if (name.includes('active')) doc.active_content = true
  }
  if (typeof window === 'undefined') finish()
  else setTimeout(finish, 1500)
}

/* ------------------------------------------------------------------ */
/* Bids                                                                */
/* ------------------------------------------------------------------ */

function bidFields(
  ctx: RouteContext,
  call: MockBidCall,
  body: Record<string, unknown>,
  { update, stored }: { update: boolean; stored?: string },
) {
  allowOnly(body, ['bidder', 'contact_name', 'contact_email', 'received_at', 'price', 'notes'])
  const bidder = text(body.bidder, ['bidder'], { min: 1, max: 120, line: true })
  const contactName = optionalText(body.contact_name, ['contact_name'], 120, true)
  let contactEmail: string | null = null
  if (
    body.contact_email !== undefined &&
    body.contact_email !== null &&
    body.contact_email !== ''
  ) {
    contactEmail = text(body.contact_email, ['contact_email'], { max: 254, line: true })
    if (!/^[^@\s]+@[^@\s]+$/.test(contactEmail))
      failValidation([issue(['contact_email'], 'An email address', 'string_pattern_mismatch')])
  }
  let receivedAt = new Date().toISOString()
  if (update && (body.received_at === undefined || body.received_at === null)) {
    failValidation([issue(['received_at'], 'Field required', 'missing')])
  }
  if (body.received_at !== undefined && body.received_at !== null) {
    if (
      typeof body.received_at !== 'string' ||
      Number.isNaN(Date.parse(body.received_at)) ||
      !/[zZ]|[+-]\d\d:?\d\d$/.test(body.received_at)
    ) {
      failValidation([issue(['received_at'], 'A date and time with an offset', 'datetime_parsing')])
    }
    receivedAt = new Date(body.received_at).toISOString()
    if (receivedAt !== stored) {
      const at = Date.parse(receivedAt)
      if (at > Date.now() + 5 * 60_000 || at < Date.now() - 366 * 24 * HOUR) {
        failValidation([
          issue(['received_at'], 'received_at must be in the past year (not in the future)'),
        ])
      }
    }
  }
  let price: string | null = null
  if (body.price !== undefined && body.price !== null && body.price !== '') {
    const raw = typeof body.price === 'number' ? String(body.price) : body.price
    if (typeof raw !== 'string' || !/^\d{1,12}(\.\d{1,2})?$/.test(raw) || Number(raw) <= 0) {
      failValidation([
        issue(['price'], 'A price above 0 with at most 2 decimals', 'decimal_parsing'),
      ])
    }
    if (!priceQuestion(ctx.db, call))
      failValidation(
        [issue(['price'], 'This call has no price question', 'price_not_asked')],
        'price_not_asked',
      )
    price = Number(raw).toFixed(2)
  }
  const notes = optionalText(body.notes, ['notes'], 2000)
  return {
    bidder,
    contact_name: contactName,
    contact_email: contactEmail,
    received_at: receivedAt,
    price,
    notes,
  }
}

/* ------------------------------------------------------------------ */
/* Report (section 13)                                                 */
/* ------------------------------------------------------------------ */

function escapeMd(value: string): string {
  return value.replace(/([\\`*_{}[\]()#+\-.!|<>~])/g, '\\$1')
}

function reportMarkdown(db: MockDb, idea: MockIdea, call: MockBidCall, user: MockUser): string {
  const comparison = comparisonOut(db, call, user)
  const lines: string[] = [
    `# ${escapeMd(call.title)}`,
    '',
    `Bid evaluation report for ${ideaKey(db, idea)} · ${call.status} · ${comparison.currency}`,
    '',
  ]
  if (comparison.ranking_hidden) {
    lines.push('_The ranking shows once you have submitted your assessments._', '')
  }
  lines.push(
    `| Rank | Bidder | ${comparison.sections.map((s) => `${escapeMd(s.title)} (${s.weight}%)`).join(' | ')} | Total |`,
  )
  lines.push(`|---|---|${comparison.sections.map(() => '---').join('|')}|---|`)
  for (const row of comparison.rows) {
    if (row.bid.status === 'rejected') continue
    const cells = row.sections.map((s) =>
      s.hidden ? 'Hidden until you submit' : (s.score?.toFixed(1) ?? '—'),
    )
    lines.push(
      `| ${row.rank ?? '—'} | ${escapeMd(row.bid.bidder)} | ${cells.join(' | ')} | ${row.total_hidden ? 'Hidden' : (row.total?.toFixed(1) ?? '—')} |`,
    )
  }
  const rejected = bidsOf(db, call).filter((b) => b.rejected)
  if (rejected.length) {
    lines.push('', '## Rejected bids', '')
    for (const bid of rejected)
      lines.push(`- ${escapeMd(bid.bidder)}: ${escapeMd(bid.rejection?.reason ?? '')}`)
  }
  if (call.status === 'awarded') {
    const awarded = db.bid.bids.find((b) => b.id === call.awarded_bid_id)
    lines.push(
      '',
      '## Award',
      '',
      `Awarded to ${escapeMd(awarded?.bidder ?? 'a bid')}.${call.award_reason ? ` ${escapeMd(call.award_reason)}` : ''}`,
    )
  }
  return lines.join('\n') + '\n'
}

function attachment(body: BodyInit, contentType: string, filename: string): Response {
  return new Response(body, {
    status: 200,
    headers: {
      'Content-Type': contentType,
      'Content-Disposition': `attachment; filename="${filename}"`,
      'X-Content-Type-Options': 'nosniff',
      'Cache-Control': 'private, no-store',
    },
  })
}

/* ------------------------------------------------------------------ */
/* AI requests (section 9.1)                                           */
/* ------------------------------------------------------------------ */

function hourlyAllowance(db: MockDb, user: MockUser): number {
  const now = Date.now()
  const recent = (db.aiRequests[user.id] ?? []).filter((at) => now - at < HOUR)
  db.aiRequests[user.id] = recent
  return AI_REQUESTS_PER_HOUR - recent.length
}

function countRequest(db: MockDb, user: MockUser): void {
  ;(db.aiRequests[user.id] ??= []).push(Date.now())
}

function agentField(ctx: RouteContext, idea: MockIdea, body: Record<string, unknown>) {
  allowOnly(body, ['agent_id'])
  if (!isUuid(body.agent_id))
    failValidation([issue(['agent_id'], 'Input should be a valid UUID', 'uuid_parsing')])
  const agent = assessAgents(ctx.db, idea).find((a) => a.id === String(body.agent_id).toLowerCase())
  if (!ctx.db.aiSettings.enabled) conflict('ai_unavailable', 'AI assistance is off.')
  if (!agent) conflict('ai_unavailable', 'That agent can’t assess bids for this idea now.')
  return agent
}

function ensureAssessable(call: MockBidCall): void {
  ensureNotFinished(call)
  if (call.status !== 'open' && call.status !== 'assessing') {
    conflict(
      'bid_call_not_assessable',
      'AI can assess bids while the call is open or being assessed.',
    )
  }
}

/* ------------------------------------------------------------------ */
/* Handlers                                                            */
/* ------------------------------------------------------------------ */

const LIFECYCLE: Record<BidCallStatus, BidCallStatus[]> = {
  draft: ['open'],
  open: ['assessing'],
  assessing: ['open'],
  awarded: [],
  cancelled: [],
}

export const bidHandlers = [
  /* The project's template ------------------------------------------------ */
  route('get', '/projects/:slug/bid-template', (ctx) => {
    const project = viewProject(ctx)
    return templateResponse(ctx.db, project.id, ctx.user)
  }),

  route('put', '/projects/:slug/bid-template', async (ctx) => {
    const project = viewProject(ctx)
    if (!isProjectAdmin(ctx.db, project, ctx.user)) {
      forbidden('forbidden', 'Only project admins can change the bid template.')
    }
    const parsed = parseTemplate(await readJson(ctx.request), false)
    const template = templateOf(ctx.db, project.id)
    template.scale = parsed.scale
    template.sections = parsed.sections.map((s) => ({
      title: s.title,
      guidance: s.guidance,
      weight: s.weight,
      questions: s.questions.map((q) => ({
        text: q.text,
        guidance: q.guidance,
        type: q.type,
        weight: q.weight,
      })),
    }))
    template.must_haves = parsed.must_haves.map((m) => ({
      text: m.text,
      kind: m.kind,
      pricing: m.pricing,
    }))
    template.updated_at = new Date().toISOString()
    template.updated_by_id = ctx.user.id
    recordAudit(
      ctx.db,
      ctx.user,
      'project.bid_template_replace',
      { type: 'project', id: project.id },
      {
        sections: parsed.sections.length,
        must_haves: parsed.must_haves.length,
      },
      project.id,
    )
    return templateResponse(ctx.db, project.id, ctx.user)
  }),

  /* The call ---------------------------------------------------------------- */
  route('get', '/ideas/:idea/bid-call', (ctx) => {
    const idea = viewIdea(ctx)
    return callView(ctx, idea)
  }),

  route('post', '/ideas/:idea/bid-call', async (ctx) => {
    const idea = viewIdea(ctx)
    requireManager(ctx, idea)
    const body = await readJson(ctx.request)
    allowOnly(body, ['title', 'description', 'currency'])
    const title = text(body.title, ['title'], { min: 1, max: 120, line: true })
    const description = optionalText(body.description, ['description'], 2000)
    const currency = body.currency === undefined ? 'GBP' : body.currency
    if (typeof currency !== 'string' || !/^[A-Z]{3}$/.test(currency)) {
      failValidation([
        issue(['currency'], 'Three capital letters (ISO 4217)', 'string_pattern_mismatch'),
      ])
    }
    ensureIdeaOpen(ctx.db, idea)
    if (callOf(ctx.db, idea)) conflict('bid_call_exists', 'This idea already has a call for bids.')
    if (idea.status !== 'proposal' || !proposalOf(ctx.db, idea)) {
      conflict(
        'bid_call_not_available',
        'A call for bids needs the idea in Proposal, with a proposal.',
      )
    }
    const now = new Date().toISOString()
    const call: MockBidCall = {
      id: newId(ctx.db, ID_KIND.phase5),
      idea_id: idea.id,
      title,
      description,
      currency,
      status: 'draft',
      deadline_at: null,
      assessment_due_at: null,
      ai_assessor_id: null,
      scale: [],
      created_by_id: ctx.user.id,
      created_at: now,
      updated_at: now,
      awarded_at: null,
      awarded_bid_id: null,
      award_reason: null,
      cancelled_at: null,
      cancel_reason: null,
      complete_notified: false,
    }
    ctx.db.bid.calls.push(call)
    copyTemplate(ctx.db, call, idea.project_id)
    emit(ctx.db, idea, 'bid_call_changed', ctx.user.id, {
      call_id: call.id,
      from_status: null,
      to_status: 'draft',
    })
    audit(ctx, idea, 'bid_call.create', { call_id: call.id })
    return created(callView(ctx, idea))
  }),

  route('put', '/ideas/:idea/bid-call', async (ctx) => {
    const { idea, call } = loadCall(ctx)
    requireManager(ctx, idea)
    const body = await readJson(ctx.request)
    allowOnly(body, ['title', 'description', 'currency', 'deadline_at', 'ai_assessor_id'])
    const title = text(body.title, ['title'], { min: 1, max: 120, line: true })
    const description = optionalText(body.description, ['description'], 2000)
    if (typeof body.currency !== 'string' || !/^[A-Z]{3}$/.test(body.currency)) {
      failValidation([
        issue(['currency'], 'Three capital letters (ISO 4217)', 'string_pattern_mismatch'),
      ])
    }
    if (!('deadline_at' in body))
      failValidation([issue(['deadline_at'], 'Field required', 'missing')])
    const deadline = dueAt(body.deadline_at, ['deadline_at'])
    let assessorId: string | null = null
    if (body.ai_assessor_id !== null && body.ai_assessor_id !== undefined) {
      if (!isUuid(body.ai_assessor_id))
        failValidation([issue(['ai_assessor_id'], 'Input should be a valid UUID', 'uuid_parsing')])
      assessorId = body.ai_assessor_id.toLowerCase()
    }
    ensureIdeaOpen(ctx.db, idea)
    ensureNotFinished(call)
    if (deadline !== call.deadline_at) {
      if (call.status === 'assessing')
        conflict('bid_call_not_open', 'The deadline is fixed once the call is closed to new bids.')
      if (call.status === 'open' && deadline === null)
        conflict('bid_call_deadline_required', 'An open call needs a deadline.')
    }
    if (assessorId !== call.ai_assessor_id && assessorId !== null) {
      if (!assessAgents(ctx.db, idea).some((a) => a.id === assessorId)) {
        conflict('ai_unavailable', 'That agent can’t assess bids for this idea now.')
      }
    }
    const fields = [
      title !== call.title && 'title',
      description !== call.description && 'description',
      body.currency !== call.currency && 'currency',
      deadline !== call.deadline_at && 'deadline_at',
      assessorId !== call.ai_assessor_id && 'ai_assessor_id',
    ].filter((f): f is string => Boolean(f))
    call.title = title
    call.description = description
    call.currency = body.currency
    call.deadline_at = deadline
    call.ai_assessor_id = assessorId
    if (fields.length) {
      touch(call)
      audit(ctx, idea, 'bid_call.update', { call_id: call.id, fields })
    }
    return callView(ctx, idea)
  }),

  route('delete', '/ideas/:idea/bid-call', (ctx) => {
    const { idea, call } = loadCall(ctx)
    requireManager(ctx, idea)
    const allowed =
      call.status === 'draft' ||
      call.status === 'cancelled' ||
      (call.status === 'awarded' && ctx.user.is_platform_admin)
    if (!allowed) conflict('bid_call_active', 'Only a draft or cancelled call can be deleted.')
    const db = ctx.db
    const bids = new Set(bidsOf(db, call).map((b) => b.id))
    db.bid.calls = db.bid.calls.filter((c) => c !== call)
    db.bid.sections = db.bid.sections.filter((s) => s.call_id !== call.id)
    db.bid.questions = db.bid.questions.filter((q) => q.call_id !== call.id)
    db.bid.mustHaves = db.bid.mustHaves.filter((m) => m.call_id !== call.id)
    db.bid.assessors = db.bid.assessors.filter((a) => a.call_id !== call.id)
    db.bid.assessments = db.bid.assessments.filter((a) => a.call_id !== call.id)
    db.bid.bids = db.bid.bids.filter((b) => b.call_id !== call.id)
    db.bid.decisions = db.bid.decisions.filter((d) => !bids.has(d.bid_id))
    db.bid.documents = db.bid.documents.filter((d) => !bids.has(d.bid_id))
    db.bid.aiAssessments = db.bid.aiAssessments.filter((a) => !bids.has(a.bid_id))
    db.aiRuns = db.aiRuns.filter(
      (r) => !(r.kind === 'assess_bid' && r.bid_id && bids.has(r.bid_id)),
    )
    audit(ctx, idea, 'bid_call.delete', { call_id: call.id, bid_count: bids.size })
    return noContent()
  }),

  route('post', '/ideas/:idea/bid-call/status', async (ctx) => {
    const { idea, call } = loadCall(ctx)
    requireManager(ctx, idea)
    const body = await readJson(ctx.request)
    allowOnly(body, ['status'])
    const to = body.status as BidCallStatus
    if (to !== 'open' && to !== 'assessing')
      failValidation([issue(['status'], 'open or assessing', 'enum')])
    ensureIdeaOpen(ctx.db, idea)
    ensureNotFinished(call)
    const from = call.status
    if (!LIFECYCLE[from].includes(to))
      conflict('invalid_bid_call_transition', 'The call can’t move there from where it is.')
    if (to === 'open' && from === 'draft' && !call.deadline_at) {
      conflict('bid_call_deadline_required', 'Set a deadline before opening the call.')
    }
    if (to === 'open' && from === 'assessing' && templateLocked(ctx.db, call)) {
      conflict('assessments_submitted', 'Assessments have been submitted: the call can’t reopen.')
    }
    call.status = to
    touch(call)
    emit(ctx.db, idea, 'bid_call_changed', ctx.user.id, {
      call_id: call.id,
      from_status: from,
      to_status: to,
    })
    audit(ctx, idea, 'bid_call.status_change', {
      call_id: call.id,
      from_status: from,
      to_status: to,
    })
    return callView(ctx, idea)
  }),

  route('post', '/ideas/:idea/bid-call/cancellation', async (ctx) => {
    const { idea, call } = loadCall(ctx)
    requireManager(ctx, idea)
    const body = await readJson(ctx.request)
    allowOnly(body, ['reason'])
    const reason = optionalText(body.reason, ['reason'], 500)
    ensureIdeaOpen(ctx.db, idea)
    ensureNotFinished(call)
    const from = call.status
    call.status = 'cancelled'
    call.cancelled_at = new Date().toISOString()
    call.cancel_reason = reason || null
    touch(call)
    cancelAssessRuns(
      ctx.db,
      bidsOf(ctx.db, call).map((b) => b.id),
    )
    emit(ctx.db, idea, 'bid_call_changed', ctx.user.id, {
      call_id: call.id,
      from_status: from,
      to_status: 'cancelled',
    })
    audit(ctx, idea, 'bid_call.status_change', {
      call_id: call.id,
      from_status: from,
      to_status: 'cancelled',
      reason_given: Boolean(reason),
    })
    return callView(ctx, idea)
  }),

  route('put', '/ideas/:idea/bid-call/template', async (ctx) => {
    const { idea, call } = loadCall(ctx)
    requireManager(ctx, idea)
    const parsed = parseTemplate(await readJson(ctx.request), true)
    ensureIdeaOpen(ctx.db, idea)
    ensureNotFinished(call)
    if (templateLocked(ctx.db, call)) {
      conflict(
        'bid_call_template_locked',
        'An assessment has been submitted: the template can’t change any more.',
      )
    }
    const changed = replaceCallTemplate(ctx.db, call, parsed)
    if (changed) {
      touch(call)
      audit(ctx, idea, 'bid_call.template_replace', {
        call_id: call.id,
        sections: parsed.sections.length,
        must_haves: parsed.must_haves.length,
      })
    }
    return bidCallOut(ctx.db, call, ctx.user).template
  }),

  route('put', '/ideas/:idea/bid-call/assessors', async (ctx) => {
    const { idea, call } = loadCall(ctx)
    requireManager(ctx, idea)
    const body = await readJson(ctx.request)
    allowOnly(body, ['sections', 'due_at'])
    const sections = list(body.sections, ['sections'], 1, 8).map((raw, i) => {
      const s = record(raw, ['sections', i])
      onlyKeys(s, ['sections', i], ['section_id', 'user_ids'])
      if (!isUuid(s.section_id))
        failValidation([
          issue(['sections', i, 'section_id'], 'Input should be a valid UUID', 'uuid_parsing'),
        ])
      const ids = list(s.user_ids, ['sections', i, 'user_ids'], 0, 10).map((u, j) => {
        if (!isUuid(u))
          failValidation([
            issue(['sections', i, 'user_ids', j], 'Input should be a valid UUID', 'uuid_parsing'),
          ])
        return u.toLowerCase()
      })
      return { section_id: s.section_id.toLowerCase(), user_ids: [...new Set(ids)] }
    })
    if (new Set(sections.map((s) => s.section_id)).size !== sections.length) {
      failValidation([issue(['sections'], 'A section appears more than once')])
    }
    const due = dueAt(body.due_at, ['due_at'])
    const callSections = sectionsOf(ctx.db, call)
    for (const [i, s] of sections.entries()) {
      if (!callSections.some((c) => c.id === s.section_id)) {
        failValidation(
          [issue(['sections', i, 'section_id'], 'Not a section of this call', 'unknown_section')],
          'unknown_section',
        )
      }
    }
    if (callSections.some((c) => !sections.some((s) => s.section_id === c.id))) {
      failValidation(
        [issue(['sections'], 'Every section of the call, once', 'unknown_section')],
        'unknown_section',
      )
    }
    for (const [i, s] of sections.entries()) {
      for (const [j, userId] of s.user_ids.entries()) {
        if (!assessorEligible(ctx.db, idea, userId)) {
          const name = findUser(ctx.db, userId)?.display_name ?? 'That person'
          failValidation(
            [
              issue(
                ['sections', i, 'user_ids', j],
                `${name} can’t assess bids on this idea`,
                'assessor_not_eligible',
              ),
            ],
            'assessor_not_eligible',
          )
        }
      }
    }
    const bids = bidsOf(ctx.db, call)
    // Removing: yourself while you owe the section (rejected bids included), then
    // anyone who submitted it.
    for (const section of callSections) {
      const next = sections.find((s) => s.section_id === section.id)?.user_ids ?? []
      const current = ctx.db.bid.assessors
        .filter((a) => a.section_id === section.id)
        .map((a) => a.user_id)
      for (const userId of current.filter((u) => !next.includes(u))) {
        if (userId === ctx.user.id && bids.some((b) => isPending(ctx.db, b, section.id, userId))) {
          forbidden(
            'cannot_remove_self',
            'You still owe assessments of this section: submit them, or ask another call manager.',
          )
        }
        if (
          ctx.db.bid.assessments.some(
            (a) => a.section_id === section.id && a.user_id === userId && a.status === 'submitted',
          )
        ) {
          const name = findUser(ctx.db, userId)?.display_name ?? 'This person'
          conflict(
            'assessor_has_submitted',
            `${name} has submitted assessments of ${section.title}: they stay.`,
          )
        }
      }
    }
    ensureIdeaOpen(ctx.db, idea)
    ensureNotFinished(call)
    const now = new Date().toISOString()
    const added = new Map<string, string[]>()
    let removed = 0
    for (const s of sections) {
      const current = ctx.db.bid.assessors.filter((a) => a.section_id === s.section_id)
      for (const row of current) {
        if (!s.user_ids.includes(row.user_id)) {
          removed += 1
          ctx.db.bid.assessors = ctx.db.bid.assessors.filter((a) => a !== row)
          ctx.db.bid.assessments = ctx.db.bid.assessments.filter(
            (a) =>
              !(a.section_id === s.section_id && a.user_id === row.user_id && a.status === 'draft'),
          )
        }
      }
      for (const userId of s.user_ids) {
        if (current.some((a) => a.user_id === userId)) continue
        ctx.db.bid.assessors.push({
          call_id: call.id,
          section_id: s.section_id,
          user_id: userId,
          assigned_at: now,
        })
        added.set(userId, [...(added.get(userId) ?? []), s.section_id])
      }
    }
    const dueChanged = due !== call.assessment_due_at
    call.assessment_due_at = due
    touch(call)
    const request = newId(ctx.db, ID_KIND.phase5)
    notify(
      ctx.db,
      idea,
      ctx.user.id,
      [...added.keys()].map((userId) => ({
        userId,
        type: 'assessor_assigned' as const,
        payload: {
          call_id: call.id,
          sections: callSections
            .filter((c) =>
              ctx.db.bid.assessors.some((a) => a.section_id === c.id && a.user_id === userId),
            )
            .map((c) => c.title),
          due_at: due,
        },
        dedupeKey: `assessor_assigned:${call.id}:${request}`,
      })),
    )
    audit(ctx, idea, 'bid_call.assessors_change', {
      call_id: call.id,
      added: [...added.values()].reduce((n, v) => n + v.length, 0),
      removed,
      due_changed: dueChanged,
    })
    checkComplete(ctx, idea, call)
    return callView(ctx, idea)
  }),

  /* Comparison, AI batch, award, report ------------------------------------- */
  route('get', '/ideas/:idea/bid-call/comparison', (ctx) => {
    const { idea, call } = loadCall(ctx)
    requireManager(ctx, idea)
    return comparisonOut(ctx.db, call, ctx.user)
  }),

  route('post', '/ideas/:idea/bid-call/ai-assessments', async (ctx) => {
    const { idea, call } = loadCall(ctx)
    requireManager(ctx, idea)
    const agent = agentField(ctx, idea, await readJson(ctx.request))
    ensureIdeaOpen(ctx.db, idea)
    ensureAssessable(call)
    let allowance = hourlyAllowance(ctx.db, ctx.user)
    const items = []
    let createdCount = 0
    let skipped = 0
    for (const bid of bidsOf(ctx.db, call)) {
      if (bid.rejected) continue
      const active = activeAssessRun(ctx.db, bid, agent.id)
      if (active) {
        items.push(active)
        continue
      }
      if (allowance <= 0) {
        skipped += 1
        continue
      }
      allowance -= 1
      countRequest(ctx.db, ctx.user)
      items.push(createAssessRun(ctx.db, idea, call, bid, agent, ctx.user))
      createdCount += 1
      audit(ctx, idea, 'ai_run.request', {
        rule: 'ai.assess_bid',
        agent_id: agent.id,
        kind: 'assess_bid',
        bid_id: bid.id,
      })
    }
    if (createdCount === 0 && skipped > 0) {
      tooManyAttempts(
        HOUR / 1000,
        'You asked AI agents 20 times in the last hour. Try again later.',
      )
    }
    return {
      items: items.map((run) => runOut(ctx.db, run, ctx.user)),
      created: createdCount,
      skipped,
    }
  }),

  route('post', '/ideas/:idea/bid-call/award', async (ctx) => {
    const { idea, call } = loadCall(ctx)
    requireManager(ctx, idea)
    const body = await readJson(ctx.request)
    allowOnly(body, ['bid_id', 'reason'])
    if (!isUuid(body.bid_id))
      failValidation([issue(['bid_id'], 'Input should be a valid UUID', 'uuid_parsing')])
    const reason = optionalText(body.reason, ['reason'], 500)
    const bid = ctx.db.bid.bids.find(
      (b) => b.id === String(body.bid_id).toLowerCase() && b.call_id === call.id,
    )
    if (!bid) notFound('Bid not found.')
    ensureIdeaOpen(ctx.db, idea)
    ensureNotFinished(call)
    if (call.status !== 'assessing')
      conflict('bid_call_not_assessing', 'Close the call to new bids before awarding it.')
    if (bid.rejected) conflict('bid_rejected', 'This bid is rejected.')
    if (!isScored(ctx.db, bid))
      conflict('bid_not_qualified', 'Only a bid that meets every must-have can be awarded.')
    call.status = 'awarded'
    call.awarded_at = new Date().toISOString()
    call.awarded_bid_id = bid.id
    call.award_reason = reason || null
    touch(call)
    cancelAssessRuns(
      ctx.db,
      bidsOf(ctx.db, call).map((b) => b.id),
    )
    emit(ctx.db, idea, 'bid_call_changed', ctx.user.id, {
      call_id: call.id,
      from_status: 'assessing',
      to_status: 'awarded',
    })
    audit(ctx, idea, 'bid_call.award', {
      call_id: call.id,
      bid_id: bid.id,
      reason_given: Boolean(reason),
    })
    return callView(ctx, idea)
  }),

  route('get', '/ideas/:idea/bid-call/report/markdown', (ctx) => {
    const { idea, call } = loadCall(ctx)
    requireManager(ctx, idea)
    return attachment(
      reportMarkdown(ctx.db, idea, call, ctx.user),
      'text/markdown; charset=utf-8',
      `${ideaKey(ctx.db, idea)}-bid-evaluation.md`,
    )
  }),

  route('get', '/ideas/:idea/bid-call/report/pdf', (ctx) => {
    const { idea, call } = loadCall(ctx)
    requireManager(ctx, idea)
    const markdown = reportMarkdown(ctx.db, idea, call, ctx.user)
    const bytes = new TextEncoder().encode(
      `%PDF-1.4\n% mock bid evaluation report\n${markdown}\n%%EOF\n`,
    )
    return attachment(
      bytes.buffer,
      'application/pdf',
      `${ideaKey(ctx.db, idea)}-bid-evaluation.pdf`,
    )
  }),

  /* Bids ---------------------------------------------------------------- */
  route('get', '/ideas/:idea/bid-call/bids', (ctx) => {
    const { idea, call } = loadCall(ctx)
    requireViewBids(ctx, idea)
    const manager = isCallManager(ctx.db, idea, ctx.user)
    return {
      items: bidsOf(ctx.db, call)
        .filter((bid) => manager || !bid.rejected)
        .map((bid) => bidOut(ctx.db, call, bid, ctx.user)),
    }
  }),

  route('post', '/ideas/:idea/bid-call/bids', async (ctx) => {
    const { idea, call } = loadCall(ctx)
    requireManager(ctx, idea)
    const fields = bidFields(ctx, call, await readJson(ctx.request), { update: false })
    ensureIdeaOpen(ctx.db, idea)
    ensureNotFinished(call)
    if (call.status !== 'open')
      conflict('bid_call_not_open', 'Bids are entered while the call is open.')
    if (bidsOf(ctx.db, call).length >= 50)
      conflict('too_many_bids', 'A call takes at most 50 bids.')
    const now = new Date().toISOString()
    const bid: MockBid = {
      id: newId(ctx.db, ID_KIND.phase5),
      call_id: call.id,
      ...fields,
      entered_by_id: ctx.user.id,
      created_at: now,
      updated_at: now,
      rejection: null,
      rejected: false,
      auto_ai_run_at: null,
    }
    ctx.db.bid.bids.push(bid)
    audit(ctx, idea, 'bid.create', { call_id: call.id, bid_id: bid.id })
    return created(bidOut(ctx.db, call, bid, ctx.user))
  }),

  route('get', '/ideas/:idea/bid-call/bids/:bidId', (ctx) => {
    const loaded = loadCall(ctx)
    requireViewBids(ctx, loaded.idea)
    const bid = findBid(ctx, loaded)
    return bidDetailOut(ctx.db, loaded.idea, loaded.call, bid, ctx.user)
  }),

  route('put', '/ideas/:idea/bid-call/bids/:bidId', async (ctx) => {
    const loaded = loadCall(ctx)
    requireManager(ctx, loaded.idea)
    const bid = findBid(ctx, loaded)
    const fields = bidFields(ctx, loaded.call, await readJson(ctx.request), {
      update: true,
      stored: bid.received_at,
    })
    ensureIdeaOpen(ctx.db, loaded.idea)
    ensureNotFinished(loaded.call)
    Object.assign(bid, fields)
    bid.updated_at = new Date().toISOString()
    audit(ctx, loaded.idea, 'bid.update', { call_id: loaded.call.id, bid_id: bid.id })
    return bidOut(ctx.db, loaded.call, bid, ctx.user)
  }),

  route('delete', '/ideas/:idea/bid-call/bids/:bidId', (ctx) => {
    const loaded = loadCall(ctx)
    requireManager(ctx, loaded.idea)
    const bid = findBid(ctx, loaded)
    ensureIdeaOpen(ctx.db, loaded.idea)
    ensureNotFinished(loaded.call)
    if (loaded.call.status !== 'draft' && loaded.call.status !== 'open') {
      conflict('bid_call_not_open', 'Bids can be deleted while the call is open.')
    }
    const db = ctx.db
    db.bid.bids = db.bid.bids.filter((b) => b !== bid)
    db.bid.documents = db.bid.documents.filter((d) => d.bid_id !== bid.id)
    db.bid.decisions = db.bid.decisions.filter((d) => d.bid_id !== bid.id)
    db.bid.assessments = db.bid.assessments.filter((a) => a.bid_id !== bid.id)
    db.bid.aiAssessments = db.bid.aiAssessments.filter((a) => a.bid_id !== bid.id)
    db.aiRuns = db.aiRuns.filter((r) => r.bid_id !== bid.id)
    audit(ctx, loaded.idea, 'bid.delete', { call_id: loaded.call.id, bid_id: bid.id })
    return noContent()
  }),

  route('put', '/ideas/:idea/bid-call/bids/:bidId/rejection', async (ctx) => {
    const loaded = loadCall(ctx)
    requireManager(ctx, loaded.idea)
    const bid = findBid(ctx, loaded)
    const body = await readJson(ctx.request)
    allowOnly(body, ['reason'])
    const reason = text(body.reason, ['reason'], { min: 1, max: 500 })
    ensureIdeaOpen(ctx.db, loaded.idea)
    ensureNotFinished(loaded.call)
    bid.rejected = true
    bid.rejection = {
      reason,
      rejected_by_id: ctx.user.id,
      rejected_at: new Date().toISOString(),
      reinstated_at: null,
      reinstated_by_id: null,
    }
    bid.updated_at = new Date().toISOString()
    cancelAssessRuns(ctx.db, [bid.id])
    audit(ctx, loaded.idea, 'bid.reject', { call_id: loaded.call.id, bid_id: bid.id })
    checkComplete(ctx, loaded.idea, loaded.call)
    return bidOut(ctx.db, loaded.call, bid, ctx.user)
  }),

  route('delete', '/ideas/:idea/bid-call/bids/:bidId/rejection', (ctx) => {
    const loaded = loadCall(ctx)
    requireManager(ctx, loaded.idea)
    const bid = findBid(ctx, loaded)
    ensureIdeaOpen(ctx.db, loaded.idea)
    ensureNotFinished(loaded.call)
    if (bid.rejected && bid.rejection) {
      bid.rejected = false
      bid.rejection.reinstated_at = new Date().toISOString()
      bid.rejection.reinstated_by_id = ctx.user.id
      bid.updated_at = new Date().toISOString()
      audit(ctx, loaded.idea, 'bid.reinstate', { call_id: loaded.call.id, bid_id: bid.id })
    }
    return bidOut(ctx.db, loaded.call, bid, ctx.user)
  }),

  route('put', '/ideas/:idea/bid-call/bids/:bidId/must-haves/:mustHaveId', async (ctx) => {
    const loaded = loadCall(ctx)
    requireManager(ctx, loaded.idea)
    const bid = findBid(ctx, loaded)
    const id = uuidParam(ctx, 'mustHaveId')
    const mustHave = mustHavesOf(ctx.db, loaded.call).find((m) => m.id === id)
    if (!mustHave || (mustHave.pricing && !canSeePrices(ctx.db, loaded.call, ctx.user))) {
      notFound('Must-have not found.')
    }
    const body = await readJson(ctx.request)
    allowOnly(body, ['result', 'note'])
    if (!('result' in body)) failValidation([issue(['result'], 'Field required', 'missing')])
    const result = body.result
    if (result !== null && result !== 'met' && result !== 'not_met') {
      failValidation([issue(['result'], 'met, not_met or null', 'enum')])
    }
    const note = optionalText(body.note, ['note'], 500)
    ensureIdeaOpen(ctx.db, loaded.idea)
    ensureNotFinished(loaded.call)
    const linked = documentsOf(ctx.db, bid).some((d) => d.must_have_id === mustHave.id)
    if (result === 'met' && mustHave.kind === 'document' && !linked) {
      conflict('document_missing', 'Upload the document first.')
    }
    ctx.db.bid.decisions = ctx.db.bid.decisions.filter(
      (d) => !(d.bid_id === bid.id && d.must_have_id === mustHave.id),
    )
    if (result !== null) {
      ctx.db.bid.decisions.push({
        bid_id: bid.id,
        must_have_id: mustHave.id,
        result,
        decided_by_id: ctx.user.id,
        decided_at: new Date().toISOString(),
        note,
      })
    }
    audit(ctx, loaded.idea, 'bid.must_have_decide', {
      call_id: loaded.call.id,
      bid_id: bid.id,
      must_have_id: mustHave.id,
      result,
    })
    return mustHaveStates(ctx.db, loaded.call, bid, ctx.user).find(
      (state) => state.must_have.id === mustHave.id,
    )
  }),

  /* Documents ------------------------------------------------------------ */
  route('post', '/ideas/:idea/bid-call/bids/:bidId/documents', async (ctx) => {
    const loaded = loadCall(ctx)
    requireManager(ctx, loaded.idea)
    const bid = findBid(ctx, loaded)
    const { db } = ctx
    const buffer = new Uint8Array(await ctx.request.arrayBuffer())
    if (buffer.byteLength > BID_DOCUMENT_MAX_BYTES) {
      throw problemResponse(413, 'content_too_large', 'Files can be at most 25 MB.')
    }
    const filename = filenameParam(ctx)
    const type = sniff(buffer, filename)
    const mustHaveId = queryUuid(ctx.url, 'must_have_id')
    const mustHave = mustHaveId
      ? mustHavesOf(db, loaded.call).find((m) => m.id === mustHaveId)
      : undefined
    if (mustHaveId && mustHave?.kind !== 'document') {
      failValidation(
        [
          {
            loc: ['query', 'must_have_id'],
            msg: 'A document must-have of this call',
            type: 'invalid_must_have',
          },
        ],
        'invalid_must_have',
      )
    }
    let pricing = mustHave?.pricing ?? false
    if (ctx.url.searchParams.has('pricing')) {
      pricing = queryBool(ctx.url, 'pricing')
      if (mustHave?.pricing && !pricing) {
        failValidation(
          [
            {
              loc: ['query', 'pricing'],
              msg: 'A pricing must-have’s files are pricing documents',
              type: 'invalid_must_have',
            },
          ],
          'invalid_must_have',
        )
      }
    }
    ensureIdeaOpen(db, loaded.idea)
    ensureNotFinished(loaded.call)
    const docs = documentsOf(db, bid)
    if (docs.length >= BID_DOCUMENTS_PER_BID_MAX)
      conflict('too_many_documents', 'A bid takes at most 30 documents.')
    const used = db.bid.documents
      .filter((d) => bidsOf(db, loaded.call).some((b) => b.id === d.bid_id))
      .reduce((sum, d) => sum + d.size_bytes + d.extraction.text.length, 0)
    if (used + buffer.byteLength > BID_CALL_STORAGE_MAX_BYTES)
      conflict('call_storage_full', 'This call’s documents take 500 MB already.')
    const hash = await sha256(buffer)
    if (docs.some((d) => d.sha256 === hash))
      conflict('duplicate_document', 'This file is already on the bid.')
    const doc: MockBidDocument = {
      id: newId(db, ID_KIND.phase5),
      bid_id: bid.id,
      filename: storedName(filename, type),
      type,
      size_bytes: buffer.byteLength,
      sha256: hash,
      must_have_id: mustHave?.id ?? null,
      pricing,
      active_content: false,
      uploaded_by_id: ctx.user.id,
      uploaded_at: new Date().toISOString(),
      bytes: buffer,
      extraction: { state: 'pending', error: null, text: '', truncated: false },
    }
    db.bid.documents.push(doc)
    extractLater(db, doc)
    audit(ctx, loaded.idea, 'bid_document.upload', {
      call_id: loaded.call.id,
      bid_id: bid.id,
      document_id: doc.id,
      pricing,
    })
    return created(documentOut(db, doc))
  }),

  route('put', '/ideas/:idea/bid-call/bids/:bidId/documents/:documentId', async (ctx) => {
    const loaded = loadCall(ctx)
    requireManager(ctx, loaded.idea)
    const bid = findBid(ctx, loaded)
    const doc = findDocument(ctx, loaded.call, bid)
    const body = await readJson(ctx.request)
    allowOnly(body, ['must_have_id', 'pricing'])
    if (typeof body.pricing !== 'boolean')
      failValidation([issue(['pricing'], 'Input should be a boolean', 'bool_type')])
    let mustHaveId: string | null = null
    if (body.must_have_id !== null && body.must_have_id !== undefined) {
      if (!isUuid(body.must_have_id))
        failValidation([issue(['must_have_id'], 'Input should be a valid UUID', 'uuid_parsing')])
      mustHaveId = body.must_have_id.toLowerCase()
    }
    const mustHave = mustHaveId
      ? mustHavesOf(ctx.db, loaded.call).find((m) => m.id === mustHaveId)
      : undefined
    if (mustHaveId && mustHave?.kind !== 'document') {
      failValidation(
        [issue(['must_have_id'], 'A document must-have of this call', 'invalid_must_have')],
        'invalid_must_have',
      )
    }
    if (mustHave?.pricing && !body.pricing) {
      failValidation(
        [
          issue(
            ['pricing'],
            'A pricing must-have’s files are pricing documents',
            'invalid_must_have',
          ),
        ],
        'invalid_must_have',
      )
    }
    ensureIdeaOpen(ctx.db, loaded.idea)
    ensureNotFinished(loaded.call)
    const changed = [
      doc.must_have_id !== mustHaveId && 'must_have_id',
      doc.pricing !== body.pricing && 'pricing',
    ].filter((f): f is string => Boolean(f))
    if (!doc.pricing && body.pricing) {
      // The AI may have read it: its assessments of the bid go, its runs stop.
      ctx.db.bid.aiAssessments = ctx.db.bid.aiAssessments.filter((a) => a.bid_id !== bid.id)
      cancelAssessRuns(ctx.db, [bid.id])
    }
    doc.must_have_id = mustHaveId
    doc.pricing = body.pricing
    if (changed.length) {
      audit(ctx, loaded.idea, 'bid_document.update', {
        call_id: loaded.call.id,
        bid_id: bid.id,
        document_id: doc.id,
        changed,
        pricing: doc.pricing,
      })
    }
    return documentOut(ctx.db, doc)
  }),

  route('delete', '/ideas/:idea/bid-call/bids/:bidId/documents/:documentId', (ctx) => {
    const loaded = loadCall(ctx)
    requireManager(ctx, loaded.idea)
    const bid = findBid(ctx, loaded)
    const doc = findDocument(ctx, loaded.call, bid)
    ensureIdeaOpen(ctx.db, loaded.idea)
    ensureNotFinished(loaded.call)
    ctx.db.bid.documents = ctx.db.bid.documents.filter((d) => d !== doc)
    // A must-have that lost its last file is missing again, a person's "met" included.
    if (
      doc.must_have_id &&
      !documentsOf(ctx.db, bid).some((d) => d.must_have_id === doc.must_have_id)
    ) {
      ctx.db.bid.decisions = ctx.db.bid.decisions.filter(
        (d) => !(d.bid_id === bid.id && d.must_have_id === doc.must_have_id && d.result === 'met'),
      )
    }
    audit(ctx, loaded.idea, 'bid_document.delete', {
      call_id: loaded.call.id,
      bid_id: bid.id,
      document_id: doc.id,
    })
    return noContent()
  }),

  route('get', '/ideas/:idea/bid-call/bids/:bidId/documents/:documentId/content', (ctx) => {
    const loaded = loadCall(ctx)
    requireViewBids(ctx, loaded.idea)
    const bid = findBid(ctx, loaded)
    const doc = findDocument(ctx, loaded.call, bid)
    const response = attachment(
      doc.bytes.slice().buffer,
      BID_DOCUMENT_TYPES[doc.type].media,
      doc.filename.replace(/[^\w.-]+/g, '_'),
    )
    response.headers.set('Content-Security-Policy', "default-src 'none'; sandbox")
    return response
  }),

  route('get', '/ideas/:idea/bid-call/bids/:bidId/documents/:documentId/text', (ctx) => {
    const loaded = loadCall(ctx)
    requireViewBids(ctx, loaded.idea)
    const bid = findBid(ctx, loaded)
    const doc = findDocument(ctx, loaded.call, bid)
    const raw = ctx.url.searchParams.get('page') ?? '1'
    const page = Number(raw)
    if (!Number.isInteger(page) || page < 1 || page > 100) {
      failValidation([{ loc: ['query', 'page'], msg: 'A page from 1 to 100', type: 'int_parsing' }])
    }
    const done = doc.extraction.state === 'done'
    const pages = done
      ? Math.max(1, Math.ceil(doc.extraction.text.length / BID_TEXT_PAGE_CHARS))
      : 0
    if (done && page > pages) notFound('No such page.')
    if (!done && page > 1) notFound('No such page.')
    return {
      document_id: doc.id,
      state: doc.extraction.state,
      page,
      page_count: pages,
      text: done
        ? doc.extraction.text.slice((page - 1) * BID_TEXT_PAGE_CHARS, page * BID_TEXT_PAGE_CHARS)
        : '',
      truncated: doc.extraction.truncated,
    }
  }),

  /* Assessments ------------------------------------------------------------ */
  route('get', '/ideas/:idea/bid-call/bids/:bidId/sections/:sectionId/assessment', (ctx) => {
    const loaded = loadCall(ctx)
    requireViewBids(ctx, loaded.idea)
    const bid = findBid(ctx, loaded)
    const section = findSection(ctx, loaded.call)
    requireSectionAssessor(ctx, loaded.call, section)
    return myAssessmentOut(ctx.db, loaded.call, bid, section, ctx.user)
  }),

  route('put', '/ideas/:idea/bid-call/bids/:bidId/sections/:sectionId/assessment', async (ctx) => {
    const loaded = loadCall(ctx)
    requireViewBids(ctx, loaded.idea)
    const bid = findBid(ctx, loaded)
    const section = findSection(ctx, loaded.call)
    requireSectionAssessor(ctx, loaded.call, section)
    const body = await readJson(ctx.request)
    allowOnly(body, ['answers', 'submit'])
    const questions = questionsOf(ctx.db, section)
    const answers = list(body.answers, ['answers'], 0, 15).map((raw, i) => {
      const a = record(raw, ['answers', i])
      onlyKeys(a, ['answers', i], ['question_id', 'score', 'comment'])
      if (!isUuid(a.question_id))
        failValidation([
          issue(['answers', i, 'question_id'], 'Input should be a valid UUID', 'uuid_parsing'),
        ])
      const question = questions.find((q) => q.id === String(a.question_id).toLowerCase())
      if (!question)
        failValidation(
          [
            issue(
              ['answers', i, 'question_id'],
              'Not a question of this section',
              'unknown_question',
            ),
          ],
          'unknown_question',
        )
      if (question.type === 'price')
        failValidation(
          [
            issue(
              ['answers', i, 'question_id'],
              'The price is scored automatically',
              'not_assessable',
            ),
          ],
          'not_assessable',
        )
      let score: number | null = null
      if (a.score !== undefined && a.score !== null) {
        if (question.type === 'comment')
          failValidation([issue(['answers', i, 'score'], 'Comment questions take no score')])
        score = int(a.score, ['answers', i, 'score'], 0, 5)
      }
      return {
        question_id: question.id,
        score,
        comment: optionalText(a.comment, ['answers', i, 'comment'], 2000),
      }
    })
    if (new Set(answers.map((a) => a.question_id)).size !== answers.length) {
      failValidation([issue(['answers'], 'A question appears more than once')])
    }
    const submit = body.submit === true
    if (submit) {
      const missing = questions.filter(
        (q) =>
          q.type === 'score' && !answers.some((a) => a.question_id === q.id && a.score !== null),
      )
      if (missing.length)
        failValidation(
          [issue(['answers'], 'Score every question to submit', 'assessment_incomplete')],
          'assessment_incomplete',
        )
    }
    ensureIdeaOpen(ctx.db, loaded.idea)
    ensureNotFinished(loaded.call)
    if (loaded.call.status !== 'assessing')
      conflict('bid_call_not_assessing', 'Assessments open once the call is closed to new bids.')
    if (bid.rejected) conflict('bid_rejected', 'This bid is rejected.')
    const now = new Date().toISOString()
    let own = ctx.db.bid.assessments.find(
      (a) => a.bid_id === bid.id && a.section_id === section.id && a.user_id === ctx.user.id,
    )
    const firstSubmission = submit && own?.status !== 'submitted'
    if (!own) {
      own = {
        id: newId(ctx.db, ID_KIND.phase5),
        call_id: loaded.call.id,
        bid_id: bid.id,
        section_id: section.id,
        user_id: ctx.user.id,
        status: 'draft',
        answers: [],
        submitted_at: null,
        edited_at: null,
        updated_at: now,
      }
      ctx.db.bid.assessments.push(own)
    }
    if (own.status === 'submitted') {
      // Editable after submitting; it stays submitted (complete answers needed).
      const missing = questions.filter(
        (q) =>
          q.type === 'score' && !answers.some((a) => a.question_id === q.id && a.score !== null),
      )
      if (missing.length)
        failValidation(
          [issue(['answers'], 'Score every question', 'assessment_incomplete')],
          'assessment_incomplete',
        )
      own.edited_at = now
    }
    own.answers = answers
    own.updated_at = now
    if (submit) {
      own.status = 'submitted'
      own.submitted_at ??= now
    }
    if (firstSubmission) {
      audit(ctx, loaded.idea, 'bid_assessment.submit', {
        call_id: loaded.call.id,
        bid_id: bid.id,
        section_id: section.id,
      })
      checkComplete(ctx, loaded.idea, loaded.call)
    }
    return myAssessmentOut(ctx.db, loaded.call, bid, section, ctx.user)
  }),

  route('get', '/ideas/:idea/bid-call/bids/:bidId/sections/:sectionId/assessments', (ctx) => {
    const loaded = loadCall(ctx)
    requireViewBids(ctx, loaded.idea)
    const bid = findBid(ctx, loaded)
    const section = findSection(ctx, loaded.call)
    if (!isCallManager(ctx.db, loaded.idea, ctx.user))
      requireSectionAssessor(ctx, loaded.call, section)
    return sectionAssessmentsOut(ctx.db, loaded.call, bid, section, ctx.user)
  }),

  /* The AI on one bid ------------------------------------------------------- */
  route('post', '/ideas/:idea/bid-call/bids/:bidId/ai-assessment', async (ctx) => {
    const loaded = loadCall(ctx)
    requireManager(ctx, loaded.idea)
    const bid = findBid(ctx, loaded)
    const agent = agentField(ctx, loaded.idea, await readJson(ctx.request))
    ensureIdeaOpen(ctx.db, loaded.idea)
    ensureAssessable(loaded.call)
    if (bid.rejected) conflict('bid_rejected', 'This bid is rejected.')
    const active = activeAssessRun(ctx.db, bid, agent.id)
    if (active) return json(runOut(ctx.db, active, ctx.user))
    if (hourlyAllowance(ctx.db, ctx.user) <= 0) {
      tooManyAttempts(
        HOUR / 1000,
        'You asked AI agents 20 times in the last hour. Try again later.',
      )
    }
    countRequest(ctx.db, ctx.user)
    const run = createAssessRun(ctx.db, loaded.idea, loaded.call, bid, agent, ctx.user)
    audit(ctx, loaded.idea, 'ai_run.request', {
      rule: 'ai.assess_bid',
      agent_id: agent.id,
      kind: 'assess_bid',
      bid_id: bid.id,
      run_id: run.id,
    })
    return created(runOut(ctx.db, run, ctx.user))
  }),

  route('get', '/ideas/:idea/bid-call/bids/:bidId/ai-assessments', (ctx) => {
    const loaded = loadCall(ctx)
    requireManager(ctx, loaded.idea)
    const bid = findBid(ctx, loaded)
    const manage =
      !isFinished(loaded.call) &&
      aiBlockedReason(ctx.db, loaded.idea, loaded.call, ctx.user) !== 'not_allowed'
    return {
      items: ctx.db.bid.aiAssessments
        .filter((a) => a.bid_id === bid.id)
        .map((a) => aiAssessmentOut(ctx.db, loaded.call, bid, a, ctx.user)),
      can_include: manage && projectOf(ctx.db, loaded.idea).archived_at === null,
    }
  }),

  route(
    'put',
    '/ideas/:idea/bid-call/bids/:bidId/ai-assessments/:aiAssessmentId/include-in-totals',
    async (ctx) => {
      const loaded = loadCall(ctx)
      requireManager(ctx, loaded.idea)
      const bid = findBid(ctx, loaded)
      const id = uuidParam(ctx, 'aiAssessmentId')
      const assessment = ctx.db.bid.aiAssessments.find((a) => a.id === id && a.bid_id === bid.id)
      // A manager who owes an assessment of the bid can't see (or include) the AI's scores.
      const owes = sectionsOf(ctx.db, loaded.call).some((s) =>
        isPending(ctx.db, bid, s.id, ctx.user.id),
      )
      if (!assessment || owes) notFound('AI assessment not found.')
      const body = await readJson(ctx.request)
      allowOnly(body, ['include'])
      if (typeof body.include !== 'boolean')
        failValidation([issue(['include'], 'Input should be a boolean', 'bool_type')])
      ensureIdeaOpen(ctx.db, loaded.idea)
      ensureNotFinished(loaded.call)
      if (assessment.included !== body.include) {
        assessment.included = body.include
        audit(ctx, loaded.idea, 'bid_assessment.include_ai', {
          call_id: loaded.call.id,
          bid_id: bid.id,
          ai_assessment_id: assessment.id,
          include: body.include,
        })
      }
      return aiAssessmentOut(ctx.db, loaded.call, bid, assessment, ctx.user)
    },
  ),
]
