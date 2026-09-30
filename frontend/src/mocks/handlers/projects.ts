import type { ProjectRole, ProjectVisibility, StatusLabels } from '@/api/types'

import { defaultRubric, ID_KIND, newId, type MockCriterion } from '@/mocks/db'
import {
  activeCriteria,
  canViewIdea,
  canViewProject,
  DEFAULT_STATUS_LABELS,
  findUser,
  member,
  projectDetail,
  projectSummary,
  rubricCriterion,
} from '@/mocks/domain'
import {
  allowOnly,
  conflict,
  created,
  failValidation,
  forbidden,
  noContent,
  notFound,
  queryBool,
  readJson,
  route,
  stringField,
  type RouteContext,
} from '@/mocks/http'

import { isUuid, standing, uuidParam, viewProject } from '@/mocks/handlers/common'

const ROLES: ProjectRole[] = ['admin', 'member', 'viewer']
const VISIBILITIES: ProjectVisibility[] = ['private', 'internal']
const LABEL_KEYS = Object.keys(DEFAULT_STATUS_LABELS) as (keyof StatusLabels)[]

function requireManage(ctx: RouteContext) {
  const project = viewProject(ctx)
  if (!standing(ctx.db, project, ctx.user).admin) forbidden()
  return project
}

function parseRole(value: unknown, field = 'role'): ProjectRole {
  if (!ROLES.includes(value as ProjectRole)) {
    failValidation([
      { loc: ['body', field], msg: "Input should be 'admin', 'member' or 'viewer'", type: 'enum' },
    ])
  }
  return value as ProjectRole
}

function adminCount(ctx: RouteContext, projectId: string): number {
  return ctx.db.members.filter((m) => m.project_id === projectId && m.role === 'admin').length
}

export const projectHandlers = [
  route('get', '/projects', ({ url, db, user }) => {
    const includeArchived = queryBool(url, 'include_archived')
    return db.projects
      .filter((project) => canViewProject(db, project, user))
      .filter((project) => includeArchived || project.archived_at === null)
      .sort((a, b) => a.name.localeCompare(b.name))
      .map((project) => projectSummary(db, project, user))
  }),

  route('post', '/projects', async (ctx) => {
    const { request, db, user } = ctx
    const body = await readJson(request)
    allowOnly(body, ['name', 'slug', 'key', 'description', 'visibility', 'admin_user_id'])
    const name = stringField(body, 'name', { required: true, max: 80 }) ?? ''
    const slug = stringField(body, 'slug', { required: true, min: 2, max: 48 }) ?? ''
    if (!/^[a-z0-9]+(-[a-z0-9]+)*$/.test(slug)) {
      failValidation([
        {
          loc: ['body', 'slug'],
          msg: 'Use lower-case letters, digits and single dashes',
          type: 'string_pattern_mismatch',
        },
      ])
    }
    const key = stringField(body, 'key', { required: true }) ?? ''
    if (!/^[A-Z][A-Z0-9]{1,5}$/.test(key)) {
      failValidation([
        {
          loc: ['body', 'key'],
          msg: 'Use 2–6 upper-case letters or digits, starting with a letter',
          type: 'string_pattern_mismatch',
        },
      ])
    }
    const description = stringField(body, 'description', { max: 1000 }) ?? ''
    const visibility = (body.visibility ?? 'private') as ProjectVisibility
    if (!VISIBILITIES.includes(visibility)) {
      failValidation([
        {
          loc: ['body', 'visibility'],
          msg: "Input should be 'private' or 'internal'",
          type: 'enum',
        },
      ])
    }
    const adminId = body.admin_user_id ?? null
    if (adminId !== null && !isUuid(adminId)) {
      failValidation([
        {
          loc: ['body', 'admin_user_id'],
          msg: 'Input should be a valid UUID',
          type: 'uuid_parsing',
        },
      ])
    }
    if (!user.is_platform_admin) forbidden('forbidden', 'Only platform admins can create projects.')
    const admin = adminId === null ? user : findUser(db, adminId.toLowerCase())
    if (!admin?.is_active) {
      failValidation(
        [
          {
            loc: ['body', 'admin_user_id'],
            msg: 'Unknown or inactive user',
            type: 'user_not_found',
          },
        ],
        'user_not_found',
      )
    }
    if (db.projects.some((p) => p.slug === slug)) conflict('slug_taken', 'That URL name is taken.')
    if (db.projects.some((p) => p.key === key)) conflict('key_taken', 'That idea key is taken.')
    const now = new Date().toISOString()
    const project = {
      id: newId(db, ID_KIND.project),
      slug,
      key,
      name,
      description,
      visibility,
      allow_volunteer_owners: true,
      default_evaluation_days: 7,
      archived_at: null,
      created_at: now,
      status_labels: {},
      next_idea_number: 1,
    }
    db.projects.push(project)
    db.criteria.push(...defaultRubric(project.id, () => newId(db, ID_KIND.criterion)))
    db.members.push({ project_id: project.id, user_id: admin.id, role: 'admin', joined_at: now })
    return created(projectDetail(db, project, user))
  }),

  route('get', '/projects/:slug', (ctx) => projectDetail(ctx.db, viewProject(ctx), ctx.user)),

  route('patch', '/projects/:slug', async (ctx) => {
    const body = await readJson(ctx.request)
    allowOnly(body, [
      'name',
      'description',
      'visibility',
      'allow_volunteer_owners',
      'default_evaluation_days',
      'status_labels',
      'archived',
    ])
    const name = stringField(body, 'name', { max: 80, min: 1 })
    const description = stringField(body, 'description', { max: 1000 })
    const days = body.default_evaluation_days
    if (
      days !== undefined &&
      days !== null &&
      (!Number.isInteger(days) || (days as number) < 1 || (days as number) > 90)
    ) {
      failValidation([
        {
          loc: ['body', 'default_evaluation_days'],
          msg: 'Input should be between 1 and 90',
          type: 'less_than_equal',
        },
      ])
    }
    if (body.visibility != null && !VISIBILITIES.includes(body.visibility as ProjectVisibility)) {
      failValidation([
        {
          loc: ['body', 'visibility'],
          msg: "Input should be 'private' or 'internal'",
          type: 'enum',
        },
      ])
    }
    const labels = body.status_labels
    if (labels != null) {
      if (typeof labels !== 'object' || Array.isArray(labels)) {
        failValidation([
          { loc: ['body', 'status_labels'], msg: 'Input should be an object', type: 'model_type' },
        ])
      }
      for (const [key, value] of Object.entries(labels as Record<string, unknown>)) {
        if (!LABEL_KEYS.includes(key as keyof StatusLabels)) {
          failValidation([
            {
              loc: ['body', 'status_labels', key],
              msg: 'Extra inputs are not permitted',
              type: 'extra_forbidden',
            },
          ])
        }
        if (
          value !== null &&
          (typeof value !== 'string' || !value.trim() || value.trim().length > 24)
        ) {
          failValidation([
            {
              loc: ['body', 'status_labels', key],
              msg: 'Labels are 1–24 characters',
              type: 'string_too_long',
            },
          ])
        }
      }
    }
    const project = requireManage(ctx)
    if (name !== undefined) project.name = name
    if (description !== undefined) project.description = description
    if (body.visibility != null) project.visibility = body.visibility as ProjectVisibility
    if (typeof body.allow_volunteer_owners === 'boolean') {
      project.allow_volunteer_owners = body.allow_volunteer_owners
    }
    if (typeof days === 'number') project.default_evaluation_days = days
    if (labels != null) {
      for (const [key, value] of Object.entries(labels as Record<string, string | null>)) {
        const label = key as keyof StatusLabels
        const trimmed = value?.trim()
        if (!trimmed || trimmed === DEFAULT_STATUS_LABELS[label]) {
          const { [label]: _removed, ...rest } = project.status_labels
          project.status_labels = rest
        } else project.status_labels = { ...project.status_labels, [label]: trimmed }
      }
    }
    if (body.archived === true && project.archived_at === null) {
      project.archived_at = new Date().toISOString()
    }
    if (body.archived === false) project.archived_at = null
    return projectDetail(ctx.db, project, ctx.user)
  }),

  route('get', '/projects/:slug/members', (ctx) => {
    const project = viewProject(ctx)
    return ctx.db.members
      .filter((m) => m.project_id === project.id)
      .map((m) => member(ctx.db, project.id, m.user_id))
      .filter((m) => m !== null)
      .sort(
        (a, b) =>
          Number(b.role === 'admin') - Number(a.role === 'admin') ||
          a.user.display_name.localeCompare(b.user.display_name),
      )
  }),

  route('post', '/projects/:slug/members', async (ctx) => {
    const body = await readJson(ctx.request)
    allowOnly(body, ['user_id', 'role'])
    if (!isUuid(body.user_id)) {
      failValidation([
        { loc: ['body', 'user_id'], msg: 'Input should be a valid UUID', type: 'uuid_parsing' },
      ])
    }
    const role = parseRole(body.role ?? 'member')
    const project = requireManage(ctx)
    const target = findUser(ctx.db, body.user_id.toLowerCase())
    if (!target?.is_active) {
      failValidation(
        [{ loc: ['body', 'user_id'], msg: 'Unknown or inactive user', type: 'user_not_found' }],
        'user_not_found',
      )
    }
    if (ctx.db.members.some((m) => m.project_id === project.id && m.user_id === target.id)) {
      conflict('already_member', 'Already a member.')
    }
    ctx.db.members.push({
      project_id: project.id,
      user_id: target.id,
      role,
      joined_at: new Date().toISOString(),
    })
    return created(member(ctx.db, project.id, target.id))
  }),

  route('patch', '/projects/:slug/members/:userId', async (ctx) => {
    const userId = uuidParam(ctx, 'userId')
    const body = await readJson(ctx.request)
    allowOnly(body, ['role'])
    const role = parseRole(body.role)
    const project = requireManage(ctx)
    const row = ctx.db.members.find((m) => m.project_id === project.id && m.user_id === userId)
    if (!row) return notFound('Not a member.')
    if (row.role === 'admin' && role !== 'admin' && adminCount(ctx, project.id) <= 1) {
      conflict('last_admin', 'A project needs at least one admin.')
    }
    row.role = role
    return member(ctx.db, project.id, userId)
  }),

  route('delete', '/projects/:slug/members/:userId', (ctx) => {
    const userId = uuidParam(ctx, 'userId')
    const project = requireManage(ctx)
    const index = ctx.db.members.findIndex(
      (m) => m.project_id === project.id && m.user_id === userId,
    )
    const row = ctx.db.members[index]
    if (!row) return notFound('Not a member.')
    if (row.role === 'admin' && adminCount(ctx, project.id) <= 1) {
      conflict('last_admin', 'A project needs at least one admin.')
    }
    ctx.db.members.splice(index, 1)
    return noContent()
  }),

  route('put', '/projects/:slug/rubric', async (ctx) => {
    const body = await readJson(ctx.request)
    allowOnly(body, ['criteria'])
    const list = body.criteria
    if (!Array.isArray(list) || list.length < 3 || list.length > 6) {
      failValidation([
        { loc: ['body', 'criteria'], msg: 'A rubric has 3 to 6 criteria', type: 'too_short' },
      ])
    }
    const seen = new Set<string>()
    const parsed = list.map((raw: unknown, index) => {
      const item = (typeof raw === 'object' && raw !== null ? raw : {}) as Record<string, unknown>
      const name = typeof item.name === 'string' ? item.name.trim() : ''
      if (!name || name.length > 60) {
        failValidation([
          { loc: ['body', 'criteria', index, 'name'], msg: 'Name is required', type: 'missing' },
        ])
      }
      if (seen.has(name.toLowerCase())) {
        failValidation([
          {
            loc: ['body', 'criteria', index, 'name'],
            msg: 'Names must be unique',
            type: 'value_error',
          },
        ])
      }
      seen.add(name.toLowerCase())
      const weight = item.weight ?? 1
      if (
        typeof weight !== 'number' ||
        weight < 0.01 ||
        weight > 10 ||
        Math.abs(Math.round(weight * 100) - weight * 100) > 1e-6
      ) {
        failValidation([
          {
            loc: ['body', 'criteria', index, 'weight'],
            msg: 'Weight is 0.01 to 10, two decimals at most',
            type: 'value_error',
          },
        ])
      }
      return {
        id: typeof item.id === 'string' ? item.id.toLowerCase() : null,
        name,
        description: typeof item.description === 'string' ? item.description : '',
        weight,
        inverted: item.inverted === true,
        guidance:
          typeof item.guidance === 'object' && item.guidance !== null
            ? (item.guidance as Record<string, string>)
            : {},
      }
    })
    const project = requireManage(ctx)
    const current = activeCriteria(ctx.db, project.id)
    for (const [index, item] of parsed.entries()) {
      if (item.id && !current.some((c) => c.id === item.id)) {
        failValidation(
          [
            {
              loc: ['body', 'criteria', index, 'id'],
              msg: 'Unknown criterion',
              type: 'unknown_criterion',
            },
          ],
          'unknown_criterion',
        )
      }
    }
    // Remove what was left out: archive scored criteria, delete the rest.
    for (const criterion of current) {
      if (parsed.some((item) => item.id === criterion.id)) continue
      const scored = ctx.db.evaluations.some((e) =>
        e.scores.some((s) => s.criterion_id === criterion.id && s.score !== null),
      )
      if (scored) criterion.archived = true
      else ctx.db.criteria.splice(ctx.db.criteria.indexOf(criterion), 1)
    }
    for (const [position, item] of parsed.entries()) {
      const existing = item.id ? ctx.db.criteria.find((c) => c.id === item.id) : undefined
      if (existing) Object.assign(existing, { ...item, id: existing.id, position })
      else {
        const criterion: MockCriterion = {
          ...item,
          id: newId(ctx.db, ID_KIND.criterion),
          project_id: project.id,
          position,
          archived: false,
        }
        ctx.db.criteria.push(criterion)
      }
    }
    return { criteria: activeCriteria(ctx.db, project.id).map(rubricCriterion) }
  }),

  route('get', '/projects/:slug/tags', (ctx) => {
    const project = viewProject(ctx)
    const counts = new Map<string, number>()
    for (const idea of ctx.db.ideas) {
      if (idea.project_id !== project.id || !canViewIdea(ctx.db, idea, ctx.user)) continue
      for (const id of idea.tag_ids) counts.set(id, (counts.get(id) ?? 0) + 1)
    }
    return ctx.db.tags
      .filter((tag) => tag.project_id === project.id && (counts.get(tag.id) ?? 0) > 0)
      .map((tag) => ({ id: tag.id, name: tag.name, idea_count: counts.get(tag.id) ?? 0 }))
      .sort((a, b) => a.name.localeCompare(b.name, 'en', { sensitivity: 'base' }))
  }),
]
