/**
 * Proposals (contract-phase4 §2 "Proposals", §3.1–3.4): the Proposal tab,
 * section saves with per-section versions (409 `proposal_conflict` with the
 * section as saved now), margin threads and the two exports.
 */
import { HttpResponse } from 'msw'

import type { ProposalSectionKey } from '@/api/types'
import { ID_KIND, newId, type MockIdea, type MockUser } from '@/mocks/db'
import { ideaKey, projectOf } from '@/mocks/domain'
import {
  allowOnly,
  conflict,
  created,
  fail,
  failValidation,
  forbidden,
  noContent,
  notFound,
  problemResponse,
  readJson,
  route,
  stringField,
  tooManyAttempts,
  type RouteContext,
} from '@/mocks/http'
import {
  commentsOf,
  COMMENT_MAX_LENGTH,
  EXPORTS_PER_MINUTE,
  exportMarkdown,
  exportPdf,
  isListedThread,
  listedThreads,
  MAX_COMMENTS_PER_THREAD,
  MAX_THREADS_PER_PROPOSAL,
  PROPOSAL_TEMPLATE,
  proposalOf,
  proposalRules,
  proposalView,
  SECTION_KEYS,
  SECTION_MAX_LENGTH,
  sectionOut,
  threadOut,
  type MockProposal,
  type MockProposalThread,
} from '@/mocks/proposals'

import { emit, ensureNotArchived, param, uuidParam, viewIdea } from '@/mocks/handlers/common'

function sectionKey(ctx: RouteContext): ProposalSectionKey {
  const key = param(ctx, 'sectionKey')
  if (!SECTION_KEYS.includes(key as ProposalSectionKey)) {
    failValidation([
      {
        loc: ['path', 'section_key'],
        msg: `Input should be ${SECTION_KEYS.join(', ')}`,
        type: 'enum',
      },
    ])
  }
  return key as ProposalSectionKey
}

/** 409s shared by every proposal write: archived project, held idea (c19). */
function ensureWritable(ctx: RouteContext, idea: MockIdea): void {
  ensureNotArchived(projectOf(ctx.db, idea))
  if (idea.held_for) conflict('awaiting_moderation', 'This idea is waiting for moderation.')
}

function existingProposal(ctx: RouteContext, idea: MockIdea): MockProposal {
  const proposal = proposalOf(ctx.db, idea)
  if (!proposal) notFound('This idea has no proposal yet.')
  return proposal
}

function findThread(ctx: RouteContext, proposal: MockProposal): MockProposalThread {
  const id = uuidParam(ctx, 'threadId')
  const thread = ctx.db.proposalThreads.find((t) => t.id === id && t.proposal_id === proposal.id)
  if (!thread || !isListedThread(ctx.db, thread)) notFound('Thread not found.')
  return thread
}

function commentBody(body: Record<string, unknown>): string {
  return stringField(body, 'body_md', { required: true, max: COMMENT_MAX_LENGTH }) ?? ''
}

/** In-process limit: 10 exports a minute per user (Markdown and PDF together). */
function checkExportLimit(ctx: RouteContext, user: MockUser): void {
  const now = Date.now()
  const recent = (ctx.db.proposalExports[user.id] ?? []).filter((at) => now - at < 60_000)
  if (recent.length >= EXPORTS_PER_MINUTE) {
    tooManyAttempts(
      (60_000 - (now - (recent[0] ?? now))) / 1000,
      'Too many exports. Try again shortly.',
    )
  }
  recent.push(now)
  ctx.db.proposalExports[user.id] = recent
}

function attachment(
  body: BodyInit,
  contentType: string,
  filename: string,
  delayMs = 0,
): Promise<Response> {
  const response = new HttpResponse(body, {
    status: 200,
    headers: {
      'Content-Type': contentType,
      'Content-Disposition': `attachment; filename="${filename}"`,
    },
  })
  return new Promise((resolve) => setTimeout(() => resolve(response), delayMs))
}

export const proposalHandlers = [
  route('get', '/ideas/:idea/proposal', (ctx) => {
    const idea = viewIdea(ctx)
    return proposalView(ctx.db, idea, ctx.user)
  }),

  route('post', '/ideas/:idea/proposal', (ctx) => {
    const idea = viewIdea(ctx)
    const rules = proposalRules(ctx.db, idea, ctx.user)
    if (!rules.writer) forbidden('forbidden', 'Only the owner and admins can start a proposal.')
    ensureWritable(ctx, idea)
    if (proposalOf(ctx.db, idea)) conflict('proposal_exists', 'This idea already has a proposal.')
    if (!rules.c7) {
      conflict('proposal_not_available', 'Proposals open once the idea is shortlisted.')
    }
    const now = new Date().toISOString()
    const proposal: MockProposal = {
      id: newId(ctx.db, ID_KIND.phase4),
      idea_id: idea.id,
      created_at: now,
      created_by_id: ctx.user.id,
      updated_at: now,
    }
    ctx.db.proposals.push(proposal)
    for (const template of PROPOSAL_TEMPLATE) {
      ctx.db.proposalSections.push({
        proposal_id: proposal.id,
        key: template.key,
        body_md: template.key === 'summary' ? idea.summary : '',
        version: 1,
        updated_at: now,
        updated_by_id: null,
      })
    }
    // A Shortlisted idea moves to Proposal, exactly like change_idea_status (§3.1).
    if (idea.status === 'shortlisted') {
      emit(ctx.db, idea, 'status_changed', ctx.user.id, {
        from_status: idea.status,
        from_resolution: idea.resolution,
        to_status: 'proposal',
        to_resolution: null,
      })
      idea.status = 'proposal'
    }
    return created(proposalView(ctx.db, idea, ctx.user))
  }),

  route('put', '/ideas/:idea/proposal/sections/:sectionKey', async (ctx) => {
    const key = sectionKey(ctx)
    const body = await readJson(ctx.request)
    allowOnly(body, ['body_md', 'base_version'])
    const text = body.body_md
    if (typeof text !== 'string') {
      failValidation([
        { loc: ['body', 'body_md'], msg: 'Input should be a valid string', type: 'string_type' },
      ])
    }
    if (text.length > SECTION_MAX_LENGTH) {
      failValidation([
        {
          loc: ['body', 'body_md'],
          msg: `String should have at most ${SECTION_MAX_LENGTH} characters`,
          type: 'string_too_long',
        },
      ])
    }
    if (text.includes('\u0000')) {
      failValidation([{ loc: ['body', 'body_md'], msg: 'NUL is not allowed', type: 'value_error' }])
    }
    const base = body.base_version
    if (typeof base !== 'number' || !Number.isInteger(base) || base < 1) {
      failValidation([
        {
          loc: ['body', 'base_version'],
          msg: 'Input should be greater than or equal to 1',
          type: 'greater_than_equal',
        },
      ])
    }
    const idea = viewIdea(ctx)
    const proposal = existingProposal(ctx, idea)
    const rules = proposalRules(ctx.db, idea, ctx.user)
    if (!rules.writer) forbidden('forbidden', 'Only the owner and admins can edit the proposal.')
    ensureWritable(ctx, idea)
    if (!rules.c7) {
      conflict(
        'proposal_not_available',
        'The proposal is read-only while the idea isn’t shortlisted.',
      )
    }
    const section = ctx.db.proposalSections.find(
      (s) => s.proposal_id === proposal.id && s.key === key,
    )
    if (!section) notFound()
    // Identical text: nothing changes, even from an older version (a retried save).
    if (section.body_md === text) return sectionOut(ctx.db, section)
    if (section.version !== base) {
      throw problemResponse(409, 'proposal_conflict', 'Someone else changed this section.', {
        current: sectionOut(ctx.db, section),
      })
    }
    const now = new Date().toISOString()
    section.body_md = text
    section.version += 1
    section.updated_at = now
    section.updated_by_id = ctx.user.id
    proposal.updated_at = now
    return sectionOut(ctx.db, section)
  }),

  route('get', '/ideas/:idea/proposal/markdown', (ctx) => {
    const idea = viewIdea(ctx)
    existingProposal(ctx, idea)
    checkExportLimit(ctx, ctx.user)
    return attachment(
      exportMarkdown(ctx.db, idea, ctx.user),
      'text/markdown; charset=utf-8',
      `${ideaKey(ctx.db, idea)}-proposal.md`,
    )
  }),

  route('get', '/ideas/:idea/proposal/pdf', (ctx) => {
    const idea = viewIdea(ctx)
    existingProposal(ctx, idea)
    checkExportLimit(ctx, ctx.user)
    // A PDF takes a moment to render: long enough to see the progress state.
    const slow =
      typeof window !== 'undefined' && localStorage.getItem('soundings-mock-latency') !== 'none'
    const bytes = exportPdf(ctx.db, idea)
    return attachment(
      bytes.buffer as ArrayBuffer,
      'application/pdf',
      `${ideaKey(ctx.db, idea)}-proposal.pdf`,
      slow ? 1200 : 0,
    )
  }),

  route('get', '/ideas/:idea/proposal/threads', (ctx) => {
    const idea = viewIdea(ctx)
    const proposal = existingProposal(ctx, idea)
    return {
      items: listedThreads(ctx.db, proposal).map((thread) =>
        threadOut(ctx.db, idea, thread, ctx.user),
      ),
    }
  }),

  route('post', '/ideas/:idea/proposal/threads', async (ctx) => {
    const body = await readJson(ctx.request)
    allowOnly(body, ['section_key', 'body_md'])
    const key = body.section_key
    if (typeof key !== 'string' || !SECTION_KEYS.includes(key as ProposalSectionKey)) {
      failValidation([
        {
          loc: ['body', 'section_key'],
          msg: `Input should be ${SECTION_KEYS.join(', ')}`,
          type: 'enum',
        },
      ])
    }
    const text = commentBody(body)
    const idea = viewIdea(ctx)
    const proposal = existingProposal(ctx, idea)
    if (!proposalRules(ctx.db, idea, ctx.user).commenter) forbidden()
    ensureWritable(ctx, idea)
    const threads = ctx.db.proposalThreads.filter((t) => t.proposal_id === proposal.id)
    if (threads.length >= MAX_THREADS_PER_PROPOSAL) {
      conflict('too_many_comments', 'This proposal has as many threads as it can hold.')
    }
    const now = new Date().toISOString()
    const thread: MockProposalThread = {
      id: newId(ctx.db, ID_KIND.phase4),
      proposal_id: proposal.id,
      section_key: key as ProposalSectionKey,
      created_at: now,
      resolved_at: null,
      resolved_by_id: null,
    }
    ctx.db.proposalThreads.push(thread)
    ctx.db.proposalComments.push({
      id: newId(ctx.db, ID_KIND.phase4),
      thread_id: thread.id,
      author_id: ctx.user.id,
      body_md: text,
      created_at: now,
      deleted_at: null,
    })
    return created(threadOut(ctx.db, idea, thread, ctx.user))
  }),

  route('post', '/ideas/:idea/proposal/threads/:threadId/comments', async (ctx) => {
    const body = await readJson(ctx.request)
    allowOnly(body, ['body_md'])
    const text = commentBody(body)
    const idea = viewIdea(ctx)
    const proposal = existingProposal(ctx, idea)
    const thread = findThread(ctx, proposal)
    if (!proposalRules(ctx.db, idea, ctx.user).commenter) forbidden()
    ensureWritable(ctx, idea)
    if (commentsOf(ctx.db, thread).length >= MAX_COMMENTS_PER_THREAD) {
      conflict('too_many_comments', 'This thread has as many comments as it can hold.')
    }
    ctx.db.proposalComments.push({
      id: newId(ctx.db, ID_KIND.phase4),
      thread_id: thread.id,
      author_id: ctx.user.id,
      body_md: text,
      created_at: new Date().toISOString(),
      deleted_at: null,
    })
    // A reply reopens a resolved thread.
    thread.resolved_at = null
    thread.resolved_by_id = null
    return created(threadOut(ctx.db, idea, thread, ctx.user))
  }),

  route('put', '/ideas/:idea/proposal/threads/:threadId/resolved', (ctx) => {
    const idea = viewIdea(ctx)
    const thread = findThread(ctx, existingProposal(ctx, idea))
    if (!proposalRules(ctx.db, idea, ctx.user).commenter) forbidden()
    ensureWritable(ctx, idea)
    if (!thread.resolved_at) {
      thread.resolved_at = new Date().toISOString()
      thread.resolved_by_id = ctx.user.id
    }
    return threadOut(ctx.db, idea, thread, ctx.user)
  }),

  route('delete', '/ideas/:idea/proposal/threads/:threadId/resolved', (ctx) => {
    const idea = viewIdea(ctx)
    const thread = findThread(ctx, existingProposal(ctx, idea))
    if (!proposalRules(ctx.db, idea, ctx.user).commenter) forbidden()
    ensureWritable(ctx, idea)
    thread.resolved_at = null
    thread.resolved_by_id = null
    return threadOut(ctx.db, idea, thread, ctx.user)
  }),

  route('delete', '/ideas/:idea/proposal/threads/:threadId/comments/:commentId', (ctx) => {
    const idea = viewIdea(ctx)
    const proposal = existingProposal(ctx, idea)
    const threadId = uuidParam(ctx, 'threadId')
    const commentId = uuidParam(ctx, 'commentId')
    const thread = ctx.db.proposalThreads.find(
      (t) => t.id === threadId && t.proposal_id === proposal.id,
    )
    const comment = thread
      ? ctx.db.proposalComments.find((c) => c.id === commentId && c.thread_id === thread.id)
      : undefined
    if (!thread || !comment) notFound('Comment not found.')
    const rules = proposalRules(ctx.db, idea, ctx.user)
    const own = comment.author_id === ctx.user.id && rules.memberish
    if (!own && !rules.admin) fail(403, 'not_author', 'You can only delete your own comments.')
    ensureWritable(ctx, idea)
    if (comment.deleted_at === null) {
      comment.deleted_at = new Date().toISOString()
      comment.body_md = ''
    }
    return noContent()
  }),
]
