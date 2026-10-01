import type { IdeaSort, IdeaStatus, Resolution } from '@/api/types'

import { ID_KIND, newId, type MockIdea } from '@/mocks/db'
import {
  board,
  countVotes,
  evaluationOf,
  evaluationOpen,
  findUser,
  ideaDetail,
  ideaSummary,
  isAssigned,
  paginate,
  projectOf,
  queryFingerprint,
  queryProjectIdeas,
  RESOLUTIONS,
  rowsForIdea,
  STATUSES,
  tagNames,
  type ListQuery,
} from '@/mocks/domain'
import {
  allowOnly,
  conflict,
  created,
  failValidation,
  forbidden,
  json,
  noContent,
  notFound,
  queryBool,
  queryEnum,
  queryLimit,
  queryList,
  readJson,
  route,
  stringField,
  type RouteContext,
} from '@/mocks/http'

import {
  addWatcher,
  deleteIdeaRows,
  emit,
  ensureIdeaWritable,
  ensureNotArchived,
  isEligibleAssignee,
  isUuid,
  parseTags,
  resolveTags,
  standing,
  uuidParam,
  viewIdea,
  viewProject,
} from '@/mocks/handlers/common'

const SORTS: IdeaSort[] = [
  'score',
  '-score',
  'updated',
  '-updated',
  'created',
  '-created',
  'votes',
  '-votes',
  'title',
  '-title',
]

function parseFilters(url: URL, { withStatus }: { withStatus: boolean }) {
  const query: ListQuery & { sort: IdeaSort } = { sort: '-updated' }
  if (withStatus) {
    query.status = queryEnum(url, 'status', STATUSES)
    query.resolution = queryEnum(url, 'resolution', RESOLUTIONS)
  }
  const owner = url.searchParams.get('owner')
  if (owner) {
    if (owner !== 'me' && owner !== 'none' && !isUuid(owner)) {
      failValidation([
        { loc: ['query', 'owner'], msg: 'A user id, "me" or "none"', type: 'value_error' },
      ])
    }
    query.owner = owner === 'me' || owner === 'none' ? owner : owner.toLowerCase()
  }
  const tags = queryList(url, 'tag')
  if (tags.length > 10) {
    failValidation([{ loc: ['query', 'tag'], msg: 'At most 10 tags', type: 'too_long' }])
  }
  if (tags.length) query.tag = tags
  query.needs_evaluators = queryBool(url, 'needs_evaluators')
  query.high_disagreement = queryBool(url, 'high_disagreement')
  const q = url.searchParams.get('q')
  if (q !== null) {
    if (q.length < 1 || q.length > 200) {
      failValidation([
        { loc: ['query', 'q'], msg: 'Search text is 1–200 characters', type: 'string_too_short' },
      ])
    }
    query.q = q
  }
  const sort = url.searchParams.get('sort')
  if (sort !== null) {
    if (!SORTS.includes(sort as IdeaSort)) {
      failValidation([
        { loc: ['query', 'sort'], msg: `Input should be one of ${SORTS.join(', ')}`, type: 'enum' },
      ])
    }
    query.sort = sort as IdeaSort
  }
  return query
}

function parseDueAt(value: unknown, field = 'due_at'): string | null {
  if (value === null) return null
  const text = typeof value === 'string' ? value : ''
  if (!/(Z|[+-]\d{2}:?\d{2})$/i.test(text) || Number.isNaN(Date.parse(text))) {
    failValidation([
      {
        loc: ['body', field],
        msg: 'Input should be a datetime with a timezone offset',
        type: 'timezone_aware',
      },
    ])
  }
  return new Date(text).toISOString()
}

function manageIdea(ctx: RouteContext) {
  const idea = viewIdea(ctx)
  const project = projectOf(ctx.db, idea)
  const who = standing(ctx.db, project, ctx.user, idea)
  return { idea, project, who }
}

function detail(ctx: RouteContext, idea: MockIdea) {
  return ideaDetail(ctx.db, idea, ctx.user)
}

function voteState(ctx: RouteContext, idea: MockIdea) {
  return {
    vote_count: countVotes(ctx.db, idea.id),
    has_voted: ctx.db.votes.has(`${idea.id}:${ctx.user.id}`),
  }
}

export const ideaHandlers = [
  route('get', '/projects/:slug/ideas', (ctx) => {
    const query = parseFilters(ctx.url, { withStatus: true })
    const limit = queryLimit(ctx.url)
    const project = viewProject(ctx)
    const ideas = queryProjectIdeas(ctx.db, project, ctx.user, query)
    const fingerprint = queryFingerprint(`project:${project.id}`, query)
    const { page, next_cursor } = paginate(
      ideas,
      ctx.url.searchParams.get('cursor'),
      limit,
      fingerprint,
    )
    return {
      items: page.map((idea) => ideaSummary(ctx.db, idea, ctx.user)),
      next_cursor,
      total: ideas.length,
    }
  }),

  route('get', '/projects/:slug/board', (ctx) => {
    const query = parseFilters(ctx.url, { withStatus: false })
    const limit = queryLimit(ctx.url)
    const project = viewProject(ctx)
    return board(ctx.db, project, ctx.user, query, limit)
  }),

  route('post', '/projects/:slug/ideas', async (ctx) => {
    const body = await readJson(ctx.request)
    allowOnly(body, ['title', 'summary', 'description_md', 'tags'])
    const errors: { loc: string[]; msg: string; type: string }[] = []
    const check = (field: string, max: number, required: boolean) => {
      try {
        return stringField(body, field, { required, max })
      } catch (error) {
        if (!(error instanceof Response)) throw error
        errors.push({
          loc: ['body', field],
          msg: required && !body[field] ? 'Field required' : `At most ${max} characters`,
          type: required && !body[field] ? 'missing' : 'string_too_long',
        })
        return undefined
      }
    }
    const title = check('title', 200, true)
    const summary = check('summary', 500, true)
    const description = check('description_md', 50_000, false) ?? ''
    if (errors.length) failValidation(errors)
    const tags = parseTags(body.tags) ?? []
    const project = viewProject(ctx)
    const who = standing(ctx.db, project, ctx.user)
    if (!ctx.user.is_platform_admin && !who.memberish) forbidden()
    ensureNotArchived(project)
    const now = new Date().toISOString()
    const idea: MockIdea = {
      id: newId(ctx.db, ID_KIND.idea),
      project_id: project.id,
      number: project.next_idea_number++,
      title: title ?? '',
      summary: summary ?? '',
      description_md: description,
      status: 'new',
      resolution: null,
      owner_id: null,
      submitted_by: ctx.user.id,
      created_at: now,
      last_activity_at: now,
      evaluation_due_at: null,
      evaluation_closed_at: null,
      tag_ids: resolveTags(ctx.db, project.id, tags),
    }
    ctx.db.ideas.push(idea)
    addWatcher(ctx.db, idea.id, ctx.user.id)
    emit(ctx.db, idea, 'idea_created', ctx.user.id)
    return created(detail(ctx, idea))
  }),

  route('get', '/ideas/:idea', (ctx) => detail(ctx, viewIdea(ctx))),

  route('patch', '/ideas/:idea', async (ctx) => {
    const body = await readJson(ctx.request)
    allowOnly(body, ['title', 'summary', 'description_md', 'tags'])
    const title = stringField(body, 'title', { max: 200, min: 1 })
    const summary = stringField(body, 'summary', { max: 500, min: 1 })
    const description = stringField(body, 'description_md', { max: 50_000 })
    const tags = parseTags(body.tags)
    const { idea, who } = manageIdea(ctx)
    if (!who.admin) {
      if (who.owner) {
        if (idea.status === 'closed') conflict('idea_closed')
      } else if (idea.submitted_by === ctx.user.id && who.memberish) {
        if (idea.status !== 'new') conflict('idea_not_new')
      } else forbidden('not_submitter', 'Only the submitter, the owner or an admin can edit.')
    }
    ensureIdeaWritable(ctx.db, idea)
    const fields: string[] = []
    if (title !== undefined && title !== idea.title) {
      idea.title = title
      fields.push('title')
    }
    if (summary !== undefined && summary !== idea.summary) {
      idea.summary = summary
      fields.push('summary')
    }
    if (description !== undefined && description !== idea.description_md) {
      idea.description_md = description
      fields.push('description_md')
    }
    if (tags !== undefined) {
      const before = tagNames(ctx.db, idea).join('\n').toLowerCase()
      idea.tag_ids = resolveTags(ctx.db, idea.project_id, tags)
      if (tagNames(ctx.db, idea).join('\n').toLowerCase() !== before) fields.push('tags')
    }
    if (fields.length) emit(ctx.db, idea, 'idea_edited', ctx.user.id, { fields })
    return detail(ctx, idea)
  }),

  route('delete', '/ideas/:idea', (ctx) => {
    const { idea, who } = manageIdea(ctx)
    if (!who.admin) forbidden()
    ensureIdeaWritable(ctx.db, idea, { allowHeld: true })
    const db = ctx.db
    deleteIdeaRows(db, idea)
    return noContent()
  }),

  route('post', '/ideas/:idea/status', async (ctx) => {
    const body = await readJson(ctx.request)
    allowOnly(body, ['status', 'resolution'])
    const status = body.status as IdeaStatus
    if (!STATUSES.includes(status)) {
      failValidation([
        { loc: ['body', 'status'], msg: `Input should be ${STATUSES.join(', ')}`, type: 'enum' },
      ])
    }
    const resolution = (body.resolution ?? null) as Resolution | null
    if (resolution !== null && !RESOLUTIONS.includes(resolution)) {
      failValidation([
        {
          loc: ['body', 'resolution'],
          msg: `Input should be ${RESOLUTIONS.join(', ')}`,
          type: 'enum',
        },
      ])
    }
    if (status === 'closed' && !resolution) {
      failValidation([
        { loc: ['body', 'resolution'], msg: 'Closing an idea needs a resolution', type: 'missing' },
      ])
    }
    if (status !== 'closed' && resolution) {
      failValidation([
        {
          loc: ['body', 'resolution'],
          msg: 'Only closed ideas have a resolution',
          type: 'value_error',
        },
      ])
    }
    const { idea, who } = manageIdea(ctx)
    if (!who.manager) forbidden()
    ensureIdeaWritable(ctx.db, idea)
    if (idea.status === status && idea.resolution === resolution) return detail(ctx, idea)
    const from = { from_status: idea.status, from_resolution: idea.resolution }
    idea.status = status
    idea.resolution = resolution
    emit(ctx.db, idea, 'status_changed', ctx.user.id, {
      ...from,
      to_status: status,
      to_resolution: resolution,
    })
    return detail(ctx, idea)
  }),

  route('put', '/ideas/:idea/owner', async (ctx) => {
    const body = await readJson(ctx.request)
    allowOnly(body, ['user_id'])
    if (!('user_id' in body)) {
      failValidation([{ loc: ['body', 'user_id'], msg: 'Field required', type: 'missing' }])
    }
    const target = body.user_id
    if (target !== null && !isUuid(target)) {
      failValidation([
        { loc: ['body', 'user_id'], msg: 'Input should be a valid UUID', type: 'uuid_parsing' },
      ])
    }
    const { idea, who } = manageIdea(ctx)
    const targetId = target === null ? null : target.toLowerCase()
    if (!who.admin) {
      // The owner may only step down.
      if (!(who.owner && targetId === null)) forbidden()
    }
    if (targetId !== null) {
      const user = findUser(ctx.db, targetId)
      if (!user?.is_active) {
        failValidation(
          [{ loc: ['body', 'user_id'], msg: 'Unknown or inactive user', type: 'user_not_found' }],
          'user_not_found',
        )
      }
      if (!isEligibleAssignee(ctx.db, idea.project_id, targetId)) {
        failValidation(
          [
            {
              loc: ['body', 'user_id'],
              msg: 'Owners need a member or admin role',
              type: 'assignee_not_eligible',
            },
          ],
          'assignee_not_eligible',
        )
      }
    }
    ensureIdeaWritable(ctx.db, idea)
    if (idea.owner_id !== targetId) {
      emit(ctx.db, idea, 'owner_changed', ctx.user.id, {
        from_owner_id: idea.owner_id,
        to_owner_id: targetId,
        volunteered: false,
      })
      idea.owner_id = targetId
      if (targetId) addWatcher(ctx.db, idea.id, targetId)
    }
    return detail(ctx, idea)
  }),

  route('post', '/ideas/:idea/volunteer', (ctx) => {
    const { idea, project, who } = manageIdea(ctx)
    if (!who.admin && who.role !== 'member') forbidden()
    if (!who.admin && !project.allow_volunteer_owners) {
      forbidden('volunteering_disabled', 'A project admin assigns owners in this project.')
    }
    if (!who.memberish) {
      failValidation(
        [
          {
            loc: ['body'],
            msg: 'Owners need a member or admin role',
            type: 'assignee_not_eligible',
          },
        ],
        'assignee_not_eligible',
      )
    }
    ensureIdeaWritable(ctx.db, idea)
    if (idea.owner_id !== null) conflict('idea_has_owner')
    if (idea.status === 'closed') conflict('idea_closed')
    emit(ctx.db, idea, 'owner_changed', ctx.user.id, {
      from_owner_id: null,
      to_owner_id: ctx.user.id,
      volunteered: true,
    })
    idea.owner_id = ctx.user.id
    addWatcher(ctx.db, idea.id, ctx.user.id)
    return detail(ctx, idea)
  }),

  route('post', '/ideas/:idea/evaluators', async (ctx) => {
    const body = await readJson(ctx.request)
    allowOnly(body, ['user_ids', 'due_at'])
    const ids = body.user_ids
    if (!Array.isArray(ids) || ids.length < 1 || ids.length > 20 || !ids.every(isUuid)) {
      failValidation([{ loc: ['body', 'user_ids'], msg: '1 to 20 user ids', type: 'too_short' }])
    }
    const dueAt = body.due_at === undefined ? undefined : parseDueAt(body.due_at)
    const { idea, project, who } = manageIdea(ctx)
    if (!who.manager) forbidden()
    const userIds = [...new Set(ids.map((id) => id.toLowerCase()))]
    for (const id of userIds) {
      if (!findUser(ctx.db, id)?.is_active) {
        failValidation(
          [{ loc: ['body', 'user_ids'], msg: 'Unknown or inactive user', type: 'user_not_found' }],
          'user_not_found',
        )
      }
      if (!isEligibleAssignee(ctx.db, idea.project_id, id)) {
        failValidation(
          [
            {
              loc: ['body', 'user_ids'],
              msg: 'Evaluators need a member or admin role',
              type: 'assignee_not_eligible',
            },
          ],
          'assignee_not_eligible',
        )
      }
    }
    ensureIdeaWritable(ctx.db, idea)
    if (!evaluationOpen(idea)) conflict('evaluation_closed')
    const firstInvite = rowsForIdea(ctx.db.assignments, idea.id).length === 0
    const now = new Date().toISOString()
    for (const id of userIds) {
      if (isAssigned(ctx.db, idea.id, id)) continue
      ctx.db.assignments.push({ idea_id: idea.id, user_id: id, invited_at: now })
      addWatcher(ctx.db, idea.id, id)
      emit(ctx.db, idea, 'evaluator_added', ctx.user.id, { evaluator_id: id })
    }
    if (dueAt !== undefined && dueAt !== idea.evaluation_due_at) {
      emit(ctx.db, idea, 'due_date_changed', ctx.user.id, {
        from_due_at: idea.evaluation_due_at,
        to_due_at: dueAt,
      })
      idea.evaluation_due_at = dueAt
    } else if (dueAt === undefined && firstInvite && idea.evaluation_due_at === null) {
      idea.evaluation_due_at = new Date(
        Date.now() + project.default_evaluation_days * 86_400_000,
      ).toISOString()
    }
    return detail(ctx, idea)
  }),

  route('delete', '/ideas/:idea/evaluators/:userId', (ctx) => {
    const userId = uuidParam(ctx, 'userId')
    const { idea, who } = manageIdea(ctx)
    if (!who.manager) forbidden()
    if (userId === ctx.user.id) {
      forbidden('cannot_remove_self', 'Submit your evaluation, or ask someone else to remove you.')
    }
    const index = ctx.db.assignments.findIndex((a) => a.idea_id === idea.id && a.user_id === userId)
    if (index < 0) notFound('Not an evaluator of this idea.')
    const evaluation = evaluationOf(ctx.db, idea.id, userId)
    if (evaluation?.status === 'submitted') conflict('evaluator_has_submitted')
    ensureIdeaWritable(ctx.db, idea)
    ctx.db.assignments.splice(index, 1)
    if (evaluation) ctx.db.evaluations.splice(ctx.db.evaluations.indexOf(evaluation), 1)
    emit(ctx.db, idea, 'evaluator_removed', ctx.user.id, { evaluator_id: userId })
    return detail(ctx, idea)
  }),

  route('put', '/ideas/:idea/evaluation/due-date', async (ctx) => {
    const body = await readJson(ctx.request)
    allowOnly(body, ['due_at'])
    if (!('due_at' in body)) {
      failValidation([{ loc: ['body', 'due_at'], msg: 'Field required', type: 'missing' }])
    }
    const dueAt = parseDueAt(body.due_at)
    const { idea, who } = manageIdea(ctx)
    if (!who.manager) forbidden()
    ensureIdeaWritable(ctx.db, idea)
    if (!evaluationOpen(idea)) conflict('evaluation_closed')
    if (dueAt !== idea.evaluation_due_at) {
      emit(ctx.db, idea, 'due_date_changed', ctx.user.id, {
        from_due_at: idea.evaluation_due_at,
        to_due_at: dueAt,
      })
      idea.evaluation_due_at = dueAt
    }
    return detail(ctx, idea)
  }),

  route('post', '/ideas/:idea/evaluation/close', (ctx) => {
    const { idea, who } = manageIdea(ctx)
    if (!who.manager) forbidden()
    ensureIdeaWritable(ctx.db, idea)
    if (idea.status === 'closed') conflict('idea_closed')
    if (idea.evaluation_closed_at === null) {
      idea.evaluation_closed_at = new Date().toISOString()
      emit(ctx.db, idea, 'evaluation_closed', ctx.user.id)
    }
    return detail(ctx, idea)
  }),

  route('post', '/ideas/:idea/evaluation/reopen', (ctx) => {
    const { idea, who } = manageIdea(ctx)
    if (!who.manager) forbidden()
    ensureIdeaWritable(ctx.db, idea)
    if (idea.status === 'closed') conflict('idea_closed')
    if (idea.evaluation_closed_at !== null) {
      idea.evaluation_closed_at = null
      emit(ctx.db, idea, 'evaluation_reopened', ctx.user.id)
    }
    return detail(ctx, idea)
  }),

  route('put', '/ideas/:idea/vote', (ctx) => {
    const { idea, who } = manageIdea(ctx)
    if (!who.admin && !who.memberish) forbidden()
    ensureIdeaWritable(ctx.db, idea)
    ctx.db.votes.add(`${idea.id}:${ctx.user.id}`)
    return voteState(ctx, idea)
  }),

  route('delete', '/ideas/:idea/vote', (ctx) => {
    const { idea, who } = manageIdea(ctx)
    if (!who.admin && !who.memberish) forbidden()
    ensureIdeaWritable(ctx.db, idea)
    ctx.db.votes.delete(`${idea.id}:${ctx.user.id}`)
    return voteState(ctx, idea)
  }),

  route('put', '/ideas/:idea/watch', (ctx) => {
    const idea = viewIdea(ctx)
    ctx.db.watchers.add(`${idea.id}:${ctx.user.id}`)
    return json({ watching: true })
  }),

  route('delete', '/ideas/:idea/watch', (ctx) => {
    const idea = viewIdea(ctx)
    ctx.db.watchers.delete(`${idea.id}:${ctx.user.id}`)
    return json({ watching: false })
  }),
]
