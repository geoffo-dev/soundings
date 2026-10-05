/**
 * Proposal suggestions (contract-phase5 §2 "Proposal suggestions", §3.4): the
 * whole text of one section, suggested by a member (or an MCP client / AI agent
 * with a key) and accepted or discarded by the owner or an admin. Accepting is
 * a normal versioned section save (409 `proposal_conflict` with `current`).
 */
import type { ProposalSectionKey } from '@/api/types'
import { ID_KIND, newId, type MockIdea } from '@/mocks/db'
import { projectOf } from '@/mocks/domain'
import {
  allowOnly,
  conflict,
  created,
  failValidation,
  forbidden,
  notFound,
  problemResponse,
  readJson,
  route,
  type RouteContext,
} from '@/mocks/http'
import {
  proposalOf,
  proposalRules,
  SECTION_KEYS,
  sectionOut,
  type MockProposal,
} from '@/mocks/proposals'
import {
  MAX_PENDING_SUGGESTIONS,
  pendingSuggestions,
  SUGGESTION_MAX_LENGTH,
  suggestionOut,
  type MockSuggestion,
} from '@/mocks/suggestions'

import { ensureNotArchived, uuidParam, viewIdea } from './common'

function existingProposal(ctx: RouteContext, idea: MockIdea): MockProposal {
  const proposal = proposalOf(ctx.db, idea)
  if (!proposal) notFound('This idea has no proposal yet.')
  return proposal
}

/** 409s shared by suggestion writes: archived project, held idea (c19), then c7. */
function ensureOpen(ctx: RouteContext, idea: MockIdea, c7: boolean): void {
  ensureNotArchived(projectOf(ctx.db, idea))
  if (idea.held_for) conflict('awaiting_moderation', 'This idea is waiting for moderation.')
  if (!c7) {
    conflict(
      'proposal_not_available',
      'The proposal is read-only while the idea isn’t shortlisted.',
    )
  }
}

function findSuggestion(ctx: RouteContext, proposal: MockProposal): MockSuggestion {
  const id = uuidParam(ctx, 'suggestionId')
  const suggestion = ctx.db.proposalSuggestions.find(
    (s) => s.id === id && s.proposal_id === proposal.id,
  )
  if (!suggestion) notFound('Suggestion not found.')
  return suggestion
}

function positiveInt(body: Record<string, unknown>, field: string, required: boolean) {
  const value = body[field]
  if ((value === undefined || value === null) && !required) return null
  if (typeof value !== 'number' || !Number.isInteger(value) || value < 1) {
    failValidation([
      {
        loc: ['body', field],
        msg: 'Input should be greater than or equal to 1',
        type: 'greater_than_equal',
      },
    ])
  }
  return value
}

export const suggestionHandlers = [
  route('get', '/ideas/:idea/proposal/suggestions', (ctx) => {
    const idea = viewIdea(ctx)
    const proposal = existingProposal(ctx, idea)
    const rules = proposalRules(ctx.db, idea, ctx.user)
    const open = rules.open && rules.c7
    return {
      items: pendingSuggestions(ctx.db, proposal).map((s) => suggestionOut(ctx.db, s)),
      permissions: {
        can_suggest: (rules.memberish || rules.admin) && open,
        can_decide: rules.writer && open,
      },
    }
  }),

  route('post', '/ideas/:idea/proposal/suggestions', async (ctx) => {
    const body = await readJson(ctx.request)
    allowOnly(body, ['section_key', 'body_md', 'base_version'])
    const sectionKey = body.section_key
    if (!SECTION_KEYS.includes(sectionKey as ProposalSectionKey)) {
      failValidation([
        {
          loc: ['body', 'section_key'],
          msg: `Input should be ${SECTION_KEYS.join(', ')}`,
          type: 'enum',
        },
      ])
    }
    const text = body.body_md
    if (
      typeof text !== 'string' ||
      !text.trim() ||
      text.length > SUGGESTION_MAX_LENGTH ||
      text.includes('\u0000')
    ) {
      failValidation([
        {
          loc: ['body', 'body_md'],
          msg: `Write 1 to ${SUGGESTION_MAX_LENGTH} characters`,
          type: 'value_error',
        },
      ])
    }
    const base = positiveInt(body, 'base_version', false)
    const idea = viewIdea(ctx)
    const proposal = existingProposal(ctx, idea)
    const rules = proposalRules(ctx.db, idea, ctx.user)
    if (!(rules.memberish || rules.admin)) {
      forbidden('forbidden', 'Members and admins can suggest text.')
    }
    ensureOpen(ctx, idea, rules.c7)
    const key = sectionKey as ProposalSectionKey
    const section = ctx.db.proposalSections.find(
      (s) => s.proposal_id === proposal.id && s.key === key,
    )
    if (!section) notFound()
    if (base !== null && base > section.version) {
      failValidation([
        {
          loc: ['body', 'base_version'],
          msg: 'Above the section’s current version',
          type: 'value_error',
        },
      ])
    }
    const now = new Date().toISOString()
    // One pending per author and section: a new one replaces the older one.
    for (const earlier of pendingSuggestions(ctx.db, proposal)) {
      if (earlier.author_id === ctx.user.id && earlier.section_key === key) {
        earlier.status = 'discarded'
        earlier.decided_at = now
        earlier.decided_by_id = ctx.user.id
      }
    }
    if (pendingSuggestions(ctx.db, proposal).length >= MAX_PENDING_SUGGESTIONS) {
      conflict('too_many_suggestions', 'This proposal has 50 pending suggestions.')
    }
    const suggestion: MockSuggestion = {
      id: newId(ctx.db, ID_KIND.phase5),
      proposal_id: proposal.id,
      section_key: key,
      author_id: ctx.user.id,
      body_md: text,
      base_version: base ?? section.version,
      source: ctx.user.is_service_account ? 'ai' : 'api',
      status: 'pending',
      created_at: now,
      decided_at: null,
      decided_by_id: null,
    }
    ctx.db.proposalSuggestions.push(suggestion)
    return created(suggestionOut(ctx.db, suggestion))
  }),

  route('post', '/ideas/:idea/proposal/suggestions/:suggestionId/accept', async (ctx) => {
    uuidParam(ctx, 'suggestionId')
    const body = await readJson(ctx.request)
    allowOnly(body, ['base_version'])
    const base = positiveInt(body, 'base_version', true) ?? 1
    const idea = viewIdea(ctx)
    const proposal = existingProposal(ctx, idea)
    const suggestion = findSuggestion(ctx, proposal)
    const rules = proposalRules(ctx.db, idea, ctx.user)
    if (!rules.writer) forbidden('forbidden', 'Only the owner and admins can accept suggestions.')
    ensureOpen(ctx, idea, rules.c7)
    if (suggestion.status !== 'pending') {
      conflict('suggestion_not_pending', 'This suggestion was already accepted or discarded.')
    }
    const section = ctx.db.proposalSections.find(
      (s) => s.proposal_id === proposal.id && s.key === suggestion.section_key,
    )
    if (!section) notFound()
    const now = new Date().toISOString()
    // Exactly a section save: equal text is a no-op, an older base a conflict.
    if (section.body_md !== suggestion.body_md) {
      if (section.version !== base) {
        throw problemResponse(409, 'proposal_conflict', 'Someone else changed this section.', {
          current: sectionOut(ctx.db, section),
        })
      }
      section.body_md = suggestion.body_md
      section.version += 1
      section.updated_at = now
      section.updated_by_id = ctx.user.id
      proposal.updated_at = now
    }
    suggestion.status = 'accepted'
    suggestion.decided_at = now
    suggestion.decided_by_id = ctx.user.id
    return {
      suggestion: suggestionOut(ctx.db, suggestion),
      section: sectionOut(ctx.db, section),
    }
  }),

  route('post', '/ideas/:idea/proposal/suggestions/:suggestionId/discard', (ctx) => {
    uuidParam(ctx, 'suggestionId')
    const idea = viewIdea(ctx)
    const proposal = existingProposal(ctx, idea)
    const suggestion = findSuggestion(ctx, proposal)
    const rules = proposalRules(ctx.db, idea, ctx.user)
    if (!rules.writer) forbidden('forbidden', 'Only the owner and admins can discard suggestions.')
    ensureOpen(ctx, idea, rules.c7)
    if (suggestion.status === 'accepted') {
      conflict('suggestion_not_pending', 'This suggestion was already accepted.')
    }
    if (suggestion.status === 'pending') {
      suggestion.status = 'discarded'
      suggestion.decided_at = new Date().toISOString()
      suggestion.decided_by_id = ctx.user.id
    }
    return suggestionOut(ctx.db, suggestion)
  }),
]
