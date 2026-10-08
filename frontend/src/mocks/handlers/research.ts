/**
 * Phase 8 (contract-phase8): the project's proposal template and research
 * settings, each idea's checklist answers and "Similar ideas", plus the gate
 * every guarded request calls (`researchGate`). Check order as everywhere:
 * 401 → 422 shape → 404 → 403 → 422 business → 409.
 */
import type { IdeaStatus, ResearchStep } from '@/api/types'

import { recordAudit } from '@/mocks/access'
import { ID_KIND, newId, type MockIdea, type MockProject } from '@/mocks/db'
import { projectOf } from '@/mocks/domain'
import {
  allowOnly,
  conflict,
  failValidation,
  forbidden,
  notFound,
  problemResponse,
  readJson,
  route,
  type FieldIssue,
  type RouteContext,
} from '@/mocks/http'
import {
  activeItems,
  answerOf,
  closedFrom,
  ideaResearch,
  mayAnswer,
  mayOverride,
  MAX_RESEARCH_ITEMS,
  openRequired,
  OVERRIDE_REASON_MAX_LENGTH,
  RESEARCH_ANSWER_MAX_LENGTH,
  RESEARCH_HINT_MAX_LENGTH,
  RESEARCH_TITLE_MAX_LENGTH,
  researchSettingsOut,
  similarIdeas,
  visibleAnswer,
  type MockResearchItem,
} from '@/mocks/research'
import {
  activeSections,
  fillMissingSections,
  MAX_TEMPLATE_SECTIONS,
  MIN_TEMPLATE_SECTIONS,
  SECTION_KEY_PATTERN,
  sectionInUse,
  sectionKeyFor,
  TEMPLATE_HINT_MAX_LENGTH,
  TEMPLATE_TITLE_MAX_LENGTH,
  templateOut,
} from '@/mocks/templates'
import { crossesGate, gatedStatuses } from '@/lib/status'

import { ensureIdeaWritable, isUuid, standing, uuidParam, viewIdea, viewProject } from './common'

const STEPS: ResearchStep[] = ['off', 'before_evaluation', 'before_proposal']
/** One line: no line breaks or other control characters. */
const SINGLE_LINE = {
  test: (text: string) => {
    for (let i = 0; i < text.length; i += 1) {
      const code = text.charCodeAt(i)
      if (code < 0x20 || code === 0x7f || code === 0x2028 || code === 0x2029) return false
    }
    return true
  },
}

/* ------------------------------------------------------------------ */
/* The gate (contract-phase8 §3.5)                                     */
/* ------------------------------------------------------------------ */

export interface Override {
  override: boolean
  reason: string | null
}

/** `override_research` / `override_reason` of a guarded request (422 on a bad shape). */
export function overrideFields(body: Record<string, unknown>): Override {
  const flag = body.override_research
  if (flag !== undefined && flag !== null && typeof flag !== 'boolean') {
    failValidation([
      {
        loc: ['body', 'override_research'],
        msg: 'Input should be a valid boolean',
        type: 'bool_type',
      },
    ])
  }
  const raw = body.override_reason
  let reason: string | null = null
  if (raw !== undefined && raw !== null) {
    const text = typeof raw === 'string' ? raw.trim() : ''
    if (!text || text.length > OVERRIDE_REASON_MAX_LENGTH || !SINGLE_LINE.test(text)) {
      failValidation([
        {
          loc: ['body', 'override_reason'],
          msg: `One line of 1 to ${OVERRIDE_REASON_MAX_LENGTH} characters`,
          type: 'value_error',
        },
      ])
    }
    if (flag !== true) {
      failValidation([
        {
          loc: ['body', 'override_reason'],
          msg: 'A reason goes with override_research only',
          type: 'value_error',
        },
      ])
    }
    reason = text
  }
  return { override: flag === true, reason }
}

/** The 403 stage: only project and platform admins may send the flag. */
export function checkOverrideRule(ctx: RouteContext, idea: MockIdea, override: Override): void {
  if (override.override && !mayOverride(ctx.db, projectOf(ctx.db, idea), ctx.user)) {
    forbidden('forbidden', 'Only project admins can move an idea past research anyway.')
  }
}

/**
 * Last of the 409s: open required items block (409 `research_incomplete`) unless
 * the admin overrode, which is audited. Call only when the request is guarded.
 */
export function researchGate(
  ctx: RouteContext,
  idea: MockIdea,
  operation: string,
  toStatus: IdeaStatus,
  override: Override,
): boolean {
  const open = openRequired(ctx.db, idea)
  if (open.length === 0) return false
  const project = projectOf(ctx.db, idea)
  if (!override.override) {
    throw problemResponse(
      409,
      'research_incomplete',
      `Finish the research checklist first: ${open.length} required ${open.length === 1 ? 'item is' : 'items are'} open.`,
      {
        open_items: open.map((item) => ({ item_id: item.id, title: item.title })),
        can_override: mayOverride(ctx.db, project, ctx.user),
      },
    )
  }
  recordAudit(
    ctx.db,
    ctx.user,
    'idea.research_override',
    { type: 'idea', id: idea.id },
    {
      rule: 'idea.research_override',
      operation,
      from_status: idea.status,
      to_status: toStatus,
      open_items: open.length,
      ...(override.reason ? { reason: override.reason } : {}),
    },
    project.id,
  )
  return true
}

/** A status change the gate guards (closed ideas count from the status they were closed from). */
export function statusChangeGuarded(ctx: RouteContext, idea: MockIdea, to: IdeaStatus): boolean {
  const step = projectOf(ctx.db, idea).research_step
  const from = idea.status === 'closed' ? closedFrom(ctx.db, idea) : null
  return crossesGate(step, idea.status, to, from)
}

/* ------------------------------------------------------------------ */
/* Parsing                                                             */
/* ------------------------------------------------------------------ */

function lineField(
  item: Record<string, unknown>,
  loc: (string | number)[],
  field: string,
  { required, max }: { required: boolean; max: number },
): string {
  const raw = item[field]
  if (raw === undefined || raw === null) {
    if (required) failValidation([{ loc: [...loc, field], msg: 'Field required', type: 'missing' }])
    return ''
  }
  const text = typeof raw === 'string' ? raw.trim() : null
  const issue = (msg: string): FieldIssue => ({ loc: [...loc, field], msg, type: 'value_error' })
  if (text === null) failValidation([issue('Input should be a valid string')])
  if (required && !text) failValidation([issue('Field required')])
  if (text.length > max) failValidation([issue(`At most ${max} characters`)])
  if (!SINGLE_LINE.test(text)) failValidation([issue('Keep it to one line')])
  return text
}

function objectList(
  body: Record<string, unknown>,
  field: string,
  min: number,
  max: number,
): Record<string, unknown>[] {
  const list = body[field]
  if (!Array.isArray(list) || list.length < min || list.length > max) {
    failValidation([
      { loc: ['body', field], msg: `Between ${min} and ${max} items`, type: 'too_short' },
    ])
  }
  return list.map((raw: unknown, index) => {
    if (typeof raw !== 'object' || raw === null || Array.isArray(raw)) {
      failValidation([
        { loc: ['body', field, index], msg: 'Input should be an object', type: 'model_type' },
      ])
    }
    return raw as Record<string, unknown>
  })
}

function uniqueTitles(titles: string[], field: string): void {
  const seen = new Set<string>()
  titles.forEach((title, index) => {
    const lower = title.toLowerCase()
    if (seen.has(lower)) {
      failValidation([
        {
          loc: ['body', field, index, 'title'],
          msg: `Another one is called “${title}”`,
          type: 'value_error',
        },
      ])
    }
    seen.add(lower)
  })
}

function requireManage(ctx: RouteContext, project: MockProject): void {
  if (!standing(ctx.db, project, ctx.user).admin) forbidden()
}

function researchItem(ctx: RouteContext, idea: MockIdea): MockResearchItem {
  const itemId = uuidParam(ctx, 'itemId')
  const item = activeItems(ctx.db, idea.project_id).find((i) => i.id === itemId)
  if (!item) notFound('Checklist item not found.')
  return item
}

/** `idea.answer_research` with its conditions, in the contract's order. */
function checkAnswer(ctx: RouteContext, idea: MockIdea): void {
  if (!mayAnswer(ctx.db, idea, ctx.user)) {
    forbidden('forbidden', 'Only the owner and admins answer the research checklist.')
  }
  if (idea.status === 'closed') conflict('idea_closed', 'This idea is closed.')
  ensureIdeaWritable(ctx.db, idea)
  if (projectOf(ctx.db, idea).research_step === 'off') {
    conflict('research_step_off', 'This project has no research step.')
  }
}

/* ------------------------------------------------------------------ */
/* Handlers                                                            */
/* ------------------------------------------------------------------ */

export const researchHandlers = [
  /* Proposal template (contract-phase8 §2) ---------------------------- */
  route('get', '/projects/:slug/proposal-template', (ctx) =>
    templateOut(ctx.db, viewProject(ctx).id),
  ),

  route('put', '/projects/:slug/proposal-template', async (ctx) => {
    const body = await readJson(ctx.request)
    allowOnly(body, ['sections'])
    const list = objectList(body, 'sections', MIN_TEMPLATE_SECTIONS, MAX_TEMPLATE_SECTIONS)
    const parsed = list.map((item, index) => {
      allowOnly(item, ['key', 'title', 'hint'])
      const loc = ['body', 'sections', index]
      const key = item.key ?? null
      if (key !== null && (typeof key !== 'string' || !SECTION_KEY_PATTERN.test(key))) {
        failValidation([
          { loc: [...loc, 'key'], msg: 'Not a section key', type: 'string_pattern_mismatch' },
        ])
      }
      return {
        key,
        title: lineField(item, loc, 'title', { required: true, max: TEMPLATE_TITLE_MAX_LENGTH }),
        hint: lineField(item, loc, 'hint', { required: false, max: TEMPLATE_HINT_MAX_LENGTH }),
      }
    })
    uniqueTitles(
      parsed.map((s) => s.title),
      'sections',
    )
    const keys = parsed.flatMap((s) => (s.key ? [s.key] : []))
    if (new Set(keys).size !== keys.length) {
      failValidation([
        { loc: ['body', 'sections'], msg: 'Keys must be unique', type: 'value_error' },
      ])
    }
    const project = viewProject(ctx)
    requireManage(ctx, project)
    const db = ctx.db
    const rows = db.templateSections.filter((s) => s.project_id === project.id)
    for (const [index, section] of parsed.entries()) {
      if (section.key && !rows.some((row) => row.key === section.key)) {
        failValidation(
          [
            {
              loc: ['body', 'sections', index, 'key'],
              msg: 'Unknown section',
              type: 'unknown_section',
            },
          ],
          'unknown_section',
        )
      }
    }
    const before = JSON.stringify(templateOut(db, project.id))
    const now = new Date().toISOString()
    const details = {
      added: [] as string[],
      restored: [] as string[],
      archived: [] as string[],
      deleted: [] as string[],
      renamed: [] as string[],
      reordered: false,
    }
    const previousOrder = activeSections(db, project.id).map((s) => s.key)
    // Removed: archived when anything refers to the key, else deleted with its empty rows.
    for (const row of activeSections(db, project.id)) {
      if (parsed.some((s) => s.key === row.key)) continue
      if (sectionInUse(db, project.id, row.key)) {
        row.archived_at = now
        details.archived.push(row.key)
      } else {
        db.templateSections.splice(db.templateSections.indexOf(row), 1)
        const ideaIds = new Set(
          db.ideas.filter((i) => i.project_id === project.id).map((i) => i.id),
        )
        const proposals = new Set(
          db.proposals.filter((p) => ideaIds.has(p.idea_id)).map((p) => p.id),
        )
        db.proposalSections = db.proposalSections.filter(
          (s) => !(proposals.has(s.proposal_id) && s.key === row.key),
        )
        details.deleted.push(row.key)
      }
    }
    const taken = new Set(
      db.templateSections.filter((s) => s.project_id === project.id).map((s) => s.key),
    )
    for (const [position, section] of parsed.entries()) {
      const existing = section.key
        ? db.templateSections.find((s) => s.project_id === project.id && s.key === section.key)
        : undefined
      if (existing) {
        if (existing.archived_at !== null) details.restored.push(existing.key)
        else if (existing.title !== section.title || existing.hint !== section.hint) {
          details.renamed.push(existing.key)
        }
        Object.assign(existing, {
          title: section.title,
          hint: section.hint,
          position,
          archived_at: null,
        })
      } else {
        const key = sectionKeyFor(section.title, taken)
        taken.add(key)
        db.templateSections.push({
          id: newId(db, ID_KIND.phase8),
          project_id: project.id,
          key,
          title: section.title,
          hint: section.hint,
          position,
          archived_at: null,
        })
        details.added.push(key)
      }
    }
    fillMissingSections(db, project.id)
    const kept = activeSections(db, project.id)
      .map((s) => s.key)
      .filter((key) => previousOrder.includes(key))
    details.reordered = kept.join() !== previousOrder.filter((key) => kept.includes(key)).join()
    const after = templateOut(db, project.id)
    if (JSON.stringify(after) !== before) {
      recordAudit(
        db,
        ctx.user,
        'project.proposal_template_replace',
        { type: 'project', id: project.id },
        { rule: 'project.edit_proposal_template', ...details },
        project.id,
      )
    }
    return after
  }),

  /* Research settings (contract-phase8 §3.3) -------------------------- */
  route('get', '/projects/:slug/research', (ctx) => researchSettingsOut(ctx.db, viewProject(ctx))),

  route('put', '/projects/:slug/research', async (ctx) => {
    const body = await readJson(ctx.request)
    allowOnly(body, ['step', 'items'])
    const step = body.step as ResearchStep
    if (!STEPS.includes(step)) {
      failValidation([
        { loc: ['body', 'step'], msg: `Input should be ${STEPS.join(', ')}`, type: 'enum' },
      ])
    }
    const list =
      body.items === undefined || body.items === null
        ? []
        : objectList(body, 'items', 0, MAX_RESEARCH_ITEMS)
    const parsed = list.map((item, index) => {
      allowOnly(item, ['id', 'title', 'hint', 'required'])
      const loc = ['body', 'items', index]
      const id = item.id ?? null
      if (id !== null && !isUuid(id)) {
        failValidation([
          { loc: [...loc, 'id'], msg: 'Input should be a valid UUID', type: 'uuid_parsing' },
        ])
      }
      if (item.required !== undefined && typeof item.required !== 'boolean') {
        failValidation([
          { loc: [...loc, 'required'], msg: 'Input should be a valid boolean', type: 'bool_type' },
        ])
      }
      return {
        id: id === null ? null : id.toLowerCase(),
        title: lineField(item, loc, 'title', { required: true, max: RESEARCH_TITLE_MAX_LENGTH }),
        hint: lineField(item, loc, 'hint', { required: false, max: RESEARCH_HINT_MAX_LENGTH }),
        required: item.required !== false,
      }
    })
    uniqueTitles(
      parsed.map((i) => i.title),
      'items',
    )
    const ids = parsed.flatMap((i) => (i.id ? [i.id] : []))
    if (new Set(ids).size !== ids.length) {
      failValidation([{ loc: ['body', 'items'], msg: 'Ids must be unique', type: 'value_error' }])
    }
    if (step !== 'off' && parsed.length === 0) {
      failValidation([
        { loc: ['body', 'items'], msg: 'The checklist needs at least one item', type: 'too_short' },
      ])
    }
    const project = viewProject(ctx)
    requireManage(ctx, project)
    const db = ctx.db
    const rows = db.researchItems.filter((i) => i.project_id === project.id)
    if (step !== 'off') {
      for (const [index, item] of parsed.entries()) {
        if (item.id && !rows.some((row) => row.id === item.id)) {
          failValidation(
            [
              {
                loc: ['body', 'items', index, 'id'],
                msg: 'Unknown checklist item',
                type: 'unknown_research_item',
              },
            ],
            'unknown_research_item',
          )
        }
      }
    }
    const inResearch = db.ideas.filter(
      (idea) => idea.project_id === project.id && idea.status === 'research',
    ).length
    if (step !== project.research_step && inResearch > 0) {
      throw problemResponse(
        409,
        'ideas_in_research',
        `Move the ${inResearch} ${inResearch === 1 ? 'idea' : 'ideas'} in Research to another status first.`,
        { idea_count: inResearch },
      )
    }
    if (step !== project.research_step) {
      recordAudit(
        db,
        ctx.user,
        'project.research_step_change',
        { type: 'project', id: project.id },
        { rule: 'project.edit_research', from: project.research_step, to: step },
        project.id,
      )
      project.research_step = step
    }
    // While the step is off the checklist is kept as it is (items ignored).
    if (step !== 'off') {
      const before = JSON.stringify(researchSettingsOut(db, project).items)
      const counts = { added: 0, restored: 0, archived: 0, deleted: 0, changed: 0 }
      const now = new Date().toISOString()
      for (const row of activeItems(db, project.id)) {
        if (parsed.some((i) => i.id === row.id)) continue
        if (db.researchAnswers.some((a) => a.item_id === row.id)) {
          row.archived_at = now
          counts.archived += 1
        } else {
          db.researchItems.splice(db.researchItems.indexOf(row), 1)
          counts.deleted += 1
        }
      }
      for (const [position, item] of parsed.entries()) {
        const existing = item.id ? db.researchItems.find((row) => row.id === item.id) : undefined
        if (existing) {
          if (existing.archived_at !== null) counts.restored += 1
          else if (
            existing.title !== item.title ||
            existing.hint !== item.hint ||
            existing.required !== item.required
          ) {
            counts.changed += 1
          }
          Object.assign(existing, {
            title: item.title,
            hint: item.hint,
            required: item.required,
            position,
            archived_at: null,
          })
        } else {
          db.researchItems.push({
            id: newId(db, ID_KIND.phase8),
            project_id: project.id,
            title: item.title,
            hint: item.hint,
            required: item.required,
            position,
            archived_at: null,
          })
          counts.added += 1
        }
      }
      if (JSON.stringify(researchSettingsOut(db, project).items) !== before) {
        recordAudit(
          db,
          ctx.user,
          'project.research_checklist_replace',
          { type: 'project', id: project.id },
          { rule: 'project.edit_research', ...counts },
          project.id,
        )
      }
    }
    return researchSettingsOut(db, project)
  }),

  /* An idea's research (contract-phase8 §3.4, §3.6, §3.7) ------------- */
  route('get', '/ideas/:idea/research', (ctx) => {
    const idea = viewIdea(ctx)
    return ideaResearch(ctx.db, idea, ctx.user)
  }),

  route('put', '/ideas/:idea/research/items/:itemId', async (ctx) => {
    uuidParam(ctx, 'itemId')
    const body = await readJson(ctx.request)
    allowOnly(body, ['answer'])
    const raw = body.answer
    if (typeof raw !== 'string') {
      failValidation([{ loc: ['body', 'answer'], msg: 'Field required', type: 'missing' }])
    }
    if (raw.includes('\u0000') || /[\u{E0000}-\u{E007F}]/u.test(raw)) {
      failValidation([
        {
          loc: ['body', 'answer'],
          msg: 'Contains a character that isn’t allowed',
          type: 'value_error',
        },
      ])
    }
    const answer = visibleAnswer(raw)
    if (!answer || answer.length > RESEARCH_ANSWER_MAX_LENGTH) {
      failValidation([
        {
          loc: ['body', 'answer'],
          msg: `Write 1 to ${RESEARCH_ANSWER_MAX_LENGTH.toLocaleString('en')} characters`,
          type: answer ? 'string_too_long' : 'string_too_short',
        },
      ])
    }
    const idea = viewIdea(ctx)
    const item = researchItem(ctx, idea)
    checkAnswer(ctx, idea)
    const now = new Date().toISOString()
    const existing = answerOf(ctx.db, idea.id, item.id)
    if (!existing) {
      ctx.db.researchAnswers.push({
        idea_id: idea.id,
        item_id: item.id,
        answer,
        answered_by_id: ctx.user.id,
        answered_at: now,
        updated_by_id: ctx.user.id,
        updated_at: now,
      })
    } else if (existing.answer !== answer) {
      existing.answer = answer
      existing.updated_by_id = ctx.user.id
      existing.updated_at = now
    }
    return ideaResearch(ctx.db, idea, ctx.user)
  }),

  route('delete', '/ideas/:idea/research/items/:itemId', (ctx) => {
    uuidParam(ctx, 'itemId')
    const idea = viewIdea(ctx)
    const item = researchItem(ctx, idea)
    checkAnswer(ctx, idea)
    // Code review M1: past Research a required answer is kept (edits stay allowed).
    const step = projectOf(ctx.db, idea).research_step
    if (
      answerOf(ctx.db, idea.id, item.id) &&
      item.required &&
      gatedStatuses(step).includes(idea.status)
    ) {
      conflict(
        'research_answer_required',
        'This idea is past Research: a required item’s answer can be changed but not cleared.',
      )
    }
    ctx.db.researchAnswers = ctx.db.researchAnswers.filter(
      (a) => !(a.idea_id === idea.id && a.item_id === item.id),
    )
    return ideaResearch(ctx.db, idea, ctx.user)
  }),

  route('get', '/ideas/:idea/similar-ideas', (ctx) => {
    const idea = viewIdea(ctx)
    return { items: similarIdeas(ctx.db, idea, ctx.user) }
  }),
]
