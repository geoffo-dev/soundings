/**
 * Public form settings, moderation and submitters (contract-phase4 §2
 * "Public form settings, moderation and submitters", §3.6, §3.9).
 */
import { recordAudit } from '@/mocks/access'
import { ideaKey, isProjectAdmin, paginate, projectOf } from '@/mocks/domain'
import {
  allowOnly,
  conflict,
  failValidation,
  forbidden,
  noContent,
  notFound,
  queryLimit,
  readJson,
  route,
  type RouteContext,
} from '@/mocks/http'
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
