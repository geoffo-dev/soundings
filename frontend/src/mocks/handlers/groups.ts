import type { ProjectRole } from '@/api/types'

import {
  accessEntry,
  findGroup,
  groupSearchResult,
  projectGroupGrant,
  projectGroupGrants,
  recordAudit,
} from '@/mocks/access'
import { paginate, usersWithAccess } from '@/mocks/domain'
import {
  allowOnly,
  conflict,
  created,
  failValidation,
  noContent,
  notFound,
  queryEnum,
  queryLimit,
  queryText,
  readJson,
  route,
} from '@/mocks/http'

import { isUuid, uuidParam, viewProject } from '@/mocks/handlers/common'
import { keepAnAdmin, parseRole, requireManage } from '@/mocks/handlers/projects'

const ROLES: ProjectRole[] = ['admin', 'member', 'viewer']

/**
 * Contract-phase2: the group picker (`search_groups`), project group grants
 * and "everyone with access" (§3.7).
 */
export const groupHandlers = [
  route('get', '/groups', ({ url, db }) => {
    const q = (queryText(url, 'q', 80) ?? '').toLowerCase()
    const limit = queryLimit(url, 20, 50)
    return db.groups
      .filter((group) => !q || group.name.toLowerCase().includes(q))
      .sort((a, b) => a.name.localeCompare(b.name, 'en', { sensitivity: 'base' }))
      .slice(0, limit)
      .map((group) => groupSearchResult(db, group))
  }),

  route('get', '/projects/:slug/groups', (ctx) => {
    const project = viewProject(ctx)
    return projectGroupGrants(ctx.db, project.id)
  }),

  route('post', '/projects/:slug/groups', async (ctx) => {
    const body = await readJson(ctx.request)
    allowOnly(body, ['group_id', 'role'])
    if (!isUuid(body.group_id)) {
      failValidation([
        { loc: ['body', 'group_id'], msg: 'Input should be a valid UUID', type: 'uuid_parsing' },
      ])
    }
    const role = parseRole(body.role ?? 'member')
    const project = requireManage(ctx)
    const group = findGroup(ctx.db, body.group_id.toLowerCase())
    if (!group) {
      failValidation(
        [{ loc: ['body', 'group_id'], msg: 'Unknown group', type: 'group_not_found' }],
        'group_not_found',
      )
    }
    if (ctx.db.groupGrants.some((g) => g.project_id === project.id && g.group_id === group.id)) {
      conflict('already_granted', 'This group already has a role in the project.')
    }
    const grant = {
      project_id: project.id,
      group_id: group.id,
      role,
      granted_at: new Date().toISOString(),
    }
    ctx.db.groupGrants.push(grant)
    recordAudit(
      ctx.db,
      ctx.user,
      'project.group_grant_add',
      { type: 'group', id: group.id },
      { rule: 'project.manage_members', role },
      project.id,
    )
    return created(projectGroupGrant(ctx.db, grant))
  }),

  route('patch', '/projects/:slug/groups/:groupId', async (ctx) => {
    const groupId = uuidParam(ctx, 'groupId')
    const body = await readJson(ctx.request)
    allowOnly(body, ['role'])
    const role = parseRole(body.role)
    const project = requireManage(ctx)
    const grant = ctx.db.groupGrants.find(
      (g) => g.project_id === project.id && g.group_id === groupId,
    )
    if (!grant) notFound('This group has no role in the project.')
    const from = grant.role
    keepAnAdmin(
      ctx,
      project.id,
      () => (grant.role = role),
      () => (grant.role = from),
    )
    if (from !== role) {
      recordAudit(
        ctx.db,
        ctx.user,
        'project.group_grant_update',
        { type: 'group', id: groupId },
        { rule: 'project.manage_members', from_role: from, role },
        project.id,
      )
    }
    return projectGroupGrant(ctx.db, grant)
  }),

  route('delete', '/projects/:slug/groups/:groupId', (ctx) => {
    const groupId = uuidParam(ctx, 'groupId')
    const project = requireManage(ctx)
    const grant = ctx.db.groupGrants.find(
      (g) => g.project_id === project.id && g.group_id === groupId,
    )
    if (!grant) notFound('This group has no role in the project.')
    keepAnAdmin(
      ctx,
      project.id,
      () => ctx.db.groupGrants.splice(ctx.db.groupGrants.indexOf(grant), 1),
      () => ctx.db.groupGrants.push(grant),
    )
    recordAudit(
      ctx.db,
      ctx.user,
      'project.group_grant_remove',
      { type: 'group', id: groupId },
      { rule: 'project.manage_members', from_role: grant.role },
      project.id,
    )
    return noContent()
  }),

  route('get', '/projects/:slug/access', (ctx) => {
    const project = viewProject(ctx)
    const q = (queryText(ctx.url, 'q', 100) ?? '').toLowerCase()
    const [role] = queryEnum(ctx.url, 'role', ROLES)
    const limit = queryLimit(ctx.url)
    const people = usersWithAccess(ctx.db, project.id)
      .filter(({ role: effective }) => !role || effective === role)
      .filter(
        ({ user }) =>
          !q || user.display_name.toLowerCase().includes(q) || user.email.toLowerCase().includes(q),
      )
      .sort(
        (a, b) =>
          a.user.display_name.toLowerCase().localeCompare(b.user.display_name.toLowerCase()) ||
          a.user.id.localeCompare(b.user.id),
      )
    const { page, next_cursor } = paginate(
      people,
      ctx.url.searchParams.get('cursor'),
      limit,
      `access:${project.id}:${q}:${role ?? ''}`,
    )
    return {
      items: page.map(({ user }) => accessEntry(ctx.db, project.id, user)),
      next_cursor,
    }
  }),
]
