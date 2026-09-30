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
    const events = [...rowsForIdea(ctx.db.events, idea.id)].sort(
      (a, b) => b.created_at.localeCompare(a.created_at) || b.id.localeCompare(a.id),
    )
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
    if (!who.admin && !who.memberish) forbidden()
    ensureIdeaWritable(ctx.db, idea)
    const comment: MockComment = {
      id: newId(ctx.db, ID_KIND.comment),
      idea_id: idea.id,
      author_id: ctx.user.id,
      body_md: text,
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
    if (!who.admin && !who.memberish) forbidden()
    ensureIdeaWritable(ctx.db, idea)
    if (text !== comment.body_md) {
      comment.body_md = text
      comment.edited_at = new Date().toISOString()
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
    const own = comment.author_id === ctx.user.id && (who.admin || who.memberish)
    if (!own && !admin) forbidden('not_author', 'You can only delete your own comments.')
    ensureIdeaWritable(ctx.db, idea)
    comment.deleted_at = new Date().toISOString()
    comment.body_md = ''
    return noContent()
  }),
]
