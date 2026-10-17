/**
 * Public form settings, moderation and submitters (contract-phase4 §2
 * "Public form settings, moderation and submitters", §3.6, §3.9).
 */
import { recordAudit } from '@/mocks/access'
import { ID_KIND, newId } from '@/mocks/db'
import { ideaKey, isProjectAdmin, paginate, projectOf } from '@/mocks/domain'
import {
  allowOnly,
  conflict,
  created,
  failValidation,
  forbidden,
  noContent,
  notFound,
  queryLimit,
  readJson,
  route,
  tooManyAttempts,
  type RouteContext,
} from '@/mocks/http'
import { queueEmail } from '@/mocks/notifications'
import {
  canMessageSubmitter,
  conversationOf,
  messageBody,
  messageDelivery,
  retryAfter,
  sendBlocked,
  sentByLastHour,
  teamMessage,
  teamMessagesToday,
  TEAM_MESSAGES_PER_PERSON_PER_HOUR,
  type MockSubmissionMessage,
} from '@/mocks/submitter-messages'
import {
  awaitingModeration,
  eraseSubmission,
  formAvailable,
  ideaSubmission,
  INTRO_MAX_LENGTH,
  moderationItem,
  publicFormOf,
  publicFormSettings,
  submissionOf,
} from '@/mocks/public'

import { deleteIdeaRows, ensureNotArchived, viewIdea, viewProject } from '@/mocks/handlers/common'

function editableProject(ctx: RouteContext) {
  const project = viewProject(ctx)
  if (!isProjectAdmin(ctx.db, project, ctx.user)) forbidden()
  return project
}

/** The idea behind a public submission, for someone who may moderate it (`idea.moderate`). */
function moderatedIdea(ctx: RouteContext) {
  const idea = viewIdea(ctx)
  const submission = submissionOf(ctx.db, idea)
  if (!submission) notFound('This idea didn’t come in through the public form.')
  if (!isProjectAdmin(ctx.db, projectOf(ctx.db, idea), ctx.user)) forbidden()
  ensureNotArchived(projectOf(ctx.db, idea))
  if (idea.held_for !== 'moderation') {
    conflict('not_awaiting_moderation', 'This idea isn’t waiting for moderation.')
  }
  return { idea, submission }
}

/**
 * Phase 11: the conversation with the submitter, for holders of
 * `public.message_submitter` (contract-phase11 §2.1: 404 idea or no submission →
 * 403 the rule, c31 → 422 → 409 → 429).
 */
function conversationIdea(ctx: RouteContext) {
  const idea = viewIdea(ctx)
  const submission = submissionOf(ctx.db, idea)
  if (!submission) notFound('This idea didn’t come in through the public form.')
  if (!canMessageSubmitter(ctx.db, idea, ctx.user)) forbidden()
  return { idea, submission }
}

const SEND_CONFLICT: Record<string, string> = {
  project_archived: 'This project is archived.',
  submitter_erased: 'Their details were erased: there’s no one to write to.',
  public_submission_off: 'Public submission is off, so their tracking link doesn’t open.',
  conversation_full: 'This conversation has reached 100 messages.',
}

function optionalBool(body: Record<string, unknown>, field: string): boolean | undefined {
  const value = body[field]
  if (value === undefined || value === null) return undefined
  if (typeof value !== 'boolean') {
    failValidation([
      { loc: ['body', field], msg: 'Input should be a valid boolean', type: 'bool_type' },
    ])
  }
  return value
}

export const submissionHandlers = [
  route('get', '/projects/:slug/public-form', (ctx) =>
    publicFormSettings(ctx.db, editableProject(ctx)),
  ),

  route('patch', '/projects/:slug/public-form', async (ctx) => {
    const body = await readJson(ctx.request)
    allowOnly(body, ['enabled', 'require_email_verification', 'moderation_required', 'intro_md'])
    const enabled = optionalBool(body, 'enabled')
    const verification = optionalBool(body, 'require_email_verification')
    const moderation = optionalBool(body, 'moderation_required')
    let intro: string | undefined
    if (body.intro_md !== undefined && body.intro_md !== null) {
      if (typeof body.intro_md !== 'string' || body.intro_md.length > INTRO_MAX_LENGTH) {
        failValidation([
          {
            loc: ['body', 'intro_md'],
            msg: `String should have at most ${INTRO_MAX_LENGTH} characters`,
            type: 'string_too_long',
          },
        ])
      }
      intro = body.intro_md.trim()
    }
    const project = editableProject(ctx)
    ensureNotArchived(project)
    if (enabled && !formAvailable(ctx.db, project)) {
      conflict('public_submission_unavailable', 'Public forms aren’t available for this project.')
    }
    if (verification && !ctx.db.email.configured) {
      conflict('smtp_not_configured', 'Email isn’t set up, so addresses can’t be confirmed.')
    }
    const form = publicFormOf(ctx.db, project)
    const fields: string[] = []
    const set = (
      key: 'enabled' | 'require_email_verification' | 'moderation_required',
      value: boolean | undefined,
      field: string,
    ) => {
      if (value === undefined || form[key] === value) return
      form[key] = value
      fields.push(field)
    }
    set('enabled', enabled, 'public_submission_enabled')
    set('require_email_verification', verification, 'public_require_email_verification')
    set('moderation_required', moderation, 'public_moderation_required')
    if (intro !== undefined && intro !== form.intro_md) {
      form.intro_md = intro
      fields.push('public_intro_md')
    }
    if (fields.length) {
      recordAudit(
        ctx.db,
        ctx.user,
        'project.update',
        { type: 'project', id: project.id },
        { fields },
        project.id,
      )
    }
    return publicFormSettings(ctx.db, project)
  }),

  route('get', '/projects/:slug/moderation', (ctx) => {
    const limit = queryLimit(ctx.url)
    const project = viewProject(ctx)
    if (!isProjectAdmin(ctx.db, project, ctx.user)) forbidden()
    const waiting = awaitingModeration(ctx.db, project)
    const { page, next_cursor } = paginate(
      waiting,
      ctx.url.searchParams.get('cursor'),
      limit,
      `moderation:${project.id}`,
    )
    return {
      items: page.map((idea) => moderationItem(ctx.db, idea, ctx.user)),
      next_cursor,
      total: waiting.length,
    }
  }),

  route('get', '/ideas/:idea/submission', (ctx) => {
    const idea = viewIdea(ctx)
    const submission = submissionOf(ctx.db, idea)
    if (!submission) notFound('This idea didn’t come in through the public form.')
    return ideaSubmission(ctx.db, idea, submission, ctx.user)
  }),

  // Phase 11: newest first (the panel shows the page oldest at the top).
  route('get', '/ideas/:idea/submission/messages', (ctx) => {
    const limit = queryLimit(ctx.url)
    const { submission } = conversationIdea(ctx)
    const newestFirst = conversationOf(ctx.db, submission).reverse()
    const { page, next_cursor } = paginate(
      newestFirst,
      ctx.url.searchParams.get('cursor'),
      limit,
      `submission-messages:${submission.id}`,
    )
    return { items: page.map((m) => teamMessage(ctx.db, m)), next_cursor }
  }),

  route('post', '/ideas/:idea/submission/messages', async (ctx) => {
    const body = await readJson(ctx.request)
    const { idea, submission } = conversationIdea(ctx)
    allowOnly(body, ['body'])
    const text = messageBody(body)
    const now = Date.now()
    const blocked = sendBlocked(ctx.db, idea, submission, now)
    if (blocked === 'daily_limit') {
      tooManyAttempts(
        retryAfter(teamMessagesToday(ctx.db, submission, now), 24 * 3_600_000, now),
        'You’ve sent 20 messages to this person in the last 24 hours.',
      )
    }
    if (blocked) conflict(blocked, SEND_CONFLICT[blocked])
    const mine = sentByLastHour(ctx.db, ctx.user.id, now)
    if (mine.length >= TEAM_MESSAGES_PER_PERSON_PER_HOUR) {
      tooManyAttempts(
        retryAfter(mine, 3_600_000, now),
        'You’ve sent 30 messages to public submitters in the last hour.',
      )
    }
    const emailed = messageDelivery(ctx.db, submission) === 'email'
    const message: MockSubmissionMessage = {
      id: newId(ctx.db, ID_KIND.phase4),
      submission_id: submission.id,
      direction: 'team',
      author_id: ctx.user.id,
      body: text,
      emailed,
      created_at: new Date(now).toISOString(),
    }
    ctx.db.submissionMessages.push(message)
    if (emailed && submission.email) {
      const row = queueEmail(ctx.db, { type: 'submission_message', to_address: submission.email })
      row.idea_id = idea.id
    }
    // Never the text (contract-phase11 §9). Not in the feed or last_activity_at.
    recordAudit(
      ctx.db,
      ctx.user,
      'submission.message',
      { type: 'idea', id: idea.id },
      { rule: 'public.message_submitter', message_id: message.id, emailed },
      idea.project_id,
    )
    return created(teamMessage(ctx.db, message))
  }),

  route('post', '/ideas/:idea/submission/approve', (ctx) => {
    const { idea, submission } = moderatedIdea(ctx)
    idea.held_for = null
    idea.last_activity_at = new Date().toISOString()
    submission.reached_team_at = idea.last_activity_at
    recordAudit(
      ctx.db,
      ctx.user,
      'submission.approve',
      { type: 'idea', id: idea.id },
      { rule: 'idea.moderate' },
      idea.project_id,
    )
    return ideaSubmission(ctx.db, idea, submission, ctx.user)
  }),

  route('post', '/ideas/:idea/submission/reject', (ctx) => {
    const { idea } = moderatedIdea(ctx)
    // Deletes the idea (spam and abuse); the entry keeps its id and key.
    recordAudit(
      ctx.db,
      ctx.user,
      'submission.reject',
      { type: 'idea', id: idea.id },
      { rule: 'idea.moderate', key: ideaKey(ctx.db, idea) },
      idea.project_id,
    )
    deleteIdeaRows(ctx.db, idea)
    return noContent()
  }),

  route('post', '/ideas/:idea/submission/erase', (ctx) => {
    const idea = viewIdea(ctx)
    const submission = submissionOf(ctx.db, idea)
    if (!submission) notFound('This idea didn’t come in through the public form.')
    if (!isProjectAdmin(ctx.db, projectOf(ctx.db, idea), ctx.user)) forbidden()
    // Idempotent: audited the first time only.
    if (submission.erased_at === null) {
      eraseSubmission(ctx.db, submission, ctx.user)
      recordAudit(
        ctx.db,
        ctx.user,
        'submission.erase',
        { type: 'idea', id: idea.id },
        { rule: 'public.erase_submitter' },
        idea.project_id,
      )
    }
    return ideaSubmission(ctx.db, idea, submission, ctx.user)
  }),
]
