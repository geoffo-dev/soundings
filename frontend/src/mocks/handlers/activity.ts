import { ID_KIND, newId, type MockComment } from '@/mocks/db'
import {
  activityItem,
  canViewIdea,
  isProjectAdmin,
  paginate,
  projectOf,
  rowsForIdea,
} from '@/mocks/domain'
import {
  allowOnly,
  created,
  failValidation,
  forbidden,
  noContent,
  notFound,
  queryLimit,
  readJson,
  route,
  stringField,
  type RouteContext,
} from '@/mocks/http'

import {
  addWatcher,
  emit,
  ensureIdeaWritable,
  standing,
  uuidParam,
  viewIdea,
} from '@/mocks/handlers/common'
import { notifyMentions, rewriteMentions } from '@/mocks/notifications'
import {
  isLiveResearcher,
  isResearchGuest,
  RESEARCH_GUEST_ACTIVITY_TYPES,
} from '@/mocks/researchers'

/** Mentions rewritten as the API stores them (contract-phase3 §3.8), or the 422. */
function storedBody(ctx: RouteContext, text: string): string {
  const result = rewriteMentions(ctx.db, text)
  if (result.ok) return result.body
  if (result.code === 'too_many_mentions') {
    failValidation(
      [{ loc: ['body', 'body_md'], msg: 'Mention at most 20 people', type: 'too_many_mentions' }],
      'too_many_mentions',
    )
  }
  failValidation([
    {
      loc: ['body', 'body_md'],
      msg: 'String should have at most 10000 characters (after mentions are written out)',
      type: 'string_too_long',
    },
  ])
}

function findComment(ctx: RouteContext): MockComment {
  const id = uuidParam(ctx, 'commentId')
  const comment = ctx.db.comments.find((c) => c.id === id)
  const idea = comment && ctx.db.ideas.find((i) => i.id === comment.idea_id)
  if (!comment || !idea || comment.deleted_at !== null || !canViewIdea(ctx.db, idea, ctx.user)) {
    notFound('Comment not found.')
  }
  return comment
}

export const activityHandlers = [
  route('get', '/ideas/:idea/activity', (ctx) => {
    const limit = queryLimit(ctx.url)
    const idea = viewIdea(ctx)
    // Phase 8b (review M2): a guest researcher reads only the allow-listed types.
    const guest = isResearchGuest(ctx.db, idea, ctx.user)
    const events = [...rowsForIdea(ctx.db.events, idea.id)]
      .filter((event) => !guest || RESEARCH_GUEST_ACTIVITY_TYPES.includes(event.type))
      .sort((a, b) => b.created_at.localeCompare(a.created_at) || b.id.localeCompare(a.id))
    const { page, next_cursor } = paginate(
      events,
      ctx.url.searchParams.get('cursor'),
      limit,
      `activity:${idea.id}`,
    )
    return {
      items: page.flatMap((event) => activityItem(ctx.db, event, ctx.user) ?? []),
      next_cursor,
    }
  }),

  route('post', '/ideas/:idea/comments', async (ctx) => {
    const body = await readJson(ctx.request)
    allowOnly(body, ['body_md'])
    const text = stringField(body, 'body_md', { required: true, max: 10_000 }) ?? ''
    const idea = viewIdea(ctx)
    const who = standing(ctx.db, projectOf(ctx.db, idea), ctx.user, idea)
    // Phase 8b: +Rsr comments too, with or without a role.
    if (!who.admin && !who.memberish && !isLiveResearcher(ctx.db, idea, ctx.user)) forbidden()
    ensureIdeaWritable(ctx.db, idea)
    const comment: MockComment = {
      id: newId(ctx.db, ID_KIND.comment),
      idea_id: idea.id,
      author_id: ctx.user.id,
      body_md: storedBody(ctx, text),
      created_at: new Date().toISOString(),
      edited_at: null,
      deleted_at: null,
    }
    ctx.db.comments.push(comment)
    addWatcher(ctx.db, idea.id, ctx.user.id)
    emit(ctx.db, idea, 'comment', ctx.user.id, {}, comment.id)
    const event = ctx.db.events[ctx.db.events.length - 1]
    return created(event ? activityItem(ctx.db, event, ctx.user) : null)
  }),

  route('patch', '/comments/:commentId', async (ctx) => {
    const body = await readJson(ctx.request)
    allowOnly(body, ['body_md'])
    const text = stringField(body, 'body_md', { required: true, max: 10_000 }) ?? ''
    const comment = findComment(ctx)
    const idea = ctx.db.ideas.find((i) => i.id === comment.idea_id)
    if (!idea) notFound()
    const who = standing(ctx.db, projectOf(ctx.db, idea), ctx.user, idea)
    if (comment.author_id !== ctx.user.id)
      forbidden('not_author', 'You can only edit your own comments.')
    if (!who.admin && !who.memberish && !isLiveResearcher(ctx.db, idea, ctx.user)) forbidden()
    ensureIdeaWritable(ctx.db, idea)
    const stored = storedBody(ctx, text)
    if (stored !== comment.body_md) {
      const previous = comment.body_md
      comment.body_md = stored
      comment.edited_at = new Date().toISOString()
      // Only people the edit newly mentions hear about it (contract-phase3 §3.8).
      notifyMentions(ctx.db, idea, comment, ctx.user.id, previous)
    }
    const event = ctx.db.events.find((e) => e.comment_id === comment.id)
    return event ? activityItem(ctx.db, event, ctx.user) : notFound()
  }),

  route('delete', '/comments/:commentId', (ctx) => {
    const comment = findComment(ctx)
    const idea = ctx.db.ideas.find((i) => i.id === comment.idea_id)
    if (!idea) notFound()
    const project = projectOf(ctx.db, idea)
    const admin = isProjectAdmin(ctx.db, project, ctx.user)
    const who = standing(ctx.db, project, ctx.user, idea)
    const own =
      comment.author_id === ctx.user.id &&
      (who.admin || who.memberish || isLiveResearcher(ctx.db, idea, ctx.user))
    if (!own && !admin) forbidden('not_author', 'You can only delete your own comments.')
    ensureIdeaWritable(ctx.db, idea)
    comment.deleted_at = new Date().toISOString()
    comment.body_md = ''
    return noContent()
  }),
]
