import {
  ID_KIND,
  newId,
  type MockDb,
  type MockEventType,
  type MockIdea,
  type MockProject,
  type MockUser,
} from '@/mocks/db'
import {
  canViewIdea,
  canViewProject,
  effectiveRole,
  findIdea,
  findProjectBySlug,
  isValidIdeaRef,
  projectOf,
} from '@/mocks/domain'
import { conflict, failValidation, notFound, type RouteContext } from '@/mocks/http'

const SLUG = /^[a-z0-9]+(-[a-z0-9]+)*$/
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

export function param(ctx: RouteContext, name: string): string {
  const value = ctx.params[name]
  return typeof value === 'string' ? decodeURIComponent(value) : ''
}

/** The `{slug}` path parameter: 422 when malformed, 404 when unknown or not viewable. */
export function viewProject(ctx: RouteContext): MockProject {
  const slug = param(ctx, 'slug')
  if (!SLUG.test(slug) || slug.length > 48) {
    failValidation([
      { loc: ['path', 'slug'], msg: 'Invalid slug', type: 'string_pattern_mismatch' },
    ])
  }
  const project = findProjectBySlug(ctx.db, slug)
  if (!project || !canViewProject(ctx.db, project, ctx.user)) notFound('Project not found.')
  return project
}

/** The `{idea}` path parameter (UUID or key): 422 malformed, 404 unknown or not viewable. */
export function viewIdea(ctx: RouteContext): MockIdea {
  const ref = param(ctx, 'idea')
  if (!isValidIdeaRef(ref)) {
    failValidation([
      { loc: ['path', 'idea'], msg: 'Invalid idea id or key', type: 'string_pattern_mismatch' },
    ])
  }
  const idea = findIdea(ctx.db, ref)
  if (!idea || !canViewIdea(ctx.db, idea, ctx.user)) notFound('Idea not found.')
  return idea
}

export function uuidParam(ctx: RouteContext, name: string): string {
  const value = param(ctx, name)
  if (!UUID.test(value)) {
    failValidation([
      { loc: ['path', name], msg: 'Input should be a valid UUID', type: 'uuid_parsing' },
    ])
  }
  return value.toLowerCase()
}

export function isUuid(value: unknown): value is string {
  return typeof value === 'string' && UUID.test(value)
}

/** The principal's standing on a project (and optionally an idea). */
export function standing(db: MockDb, project: MockProject, user: MockUser, idea?: MockIdea) {
  const role = effectiveRole(db, project.id, user.id)
  const memberish = role === 'member' || role === 'admin'
  const admin = user.is_platform_admin || role === 'admin'
  const owner = idea?.owner_id === user.id && memberish
  return { role, memberish, admin, owner, manager: admin || owner }
}

export function ensureNotArchived(project: MockProject): void {
  if (project.archived_at !== null) conflict('project_archived', 'This project is archived.')
}

export function ensureIdeaWritable(db: MockDb, idea: MockIdea): void {
  ensureNotArchived(projectOf(db, idea))
}

/** c4: owners and evaluators need an effective member/admin role in the project. */
export function isEligibleAssignee(db: MockDb, projectId: string, userId: string): boolean {
  const role = effectiveRole(db, projectId, userId)
  return role === 'member' || role === 'admin'
}

/**
 * Inserts an activity event and bumps last_activity_at (contract §3 "emit"); the
 * notification fan-out runs after the handler returns (contract-phase3 §3.3).
 */
export function emit(
  db: MockDb,
  idea: MockIdea,
  type: MockEventType,
  actorId: string,
  payload: Record<string, unknown> = {},
  commentId: string | null = null,
): void {
  const at = new Date().toISOString()
  const event = {
    id: newId(db, ID_KIND.event),
    idea_id: idea.id,
    actor_id: actorId,
    type,
    payload,
    comment_id: commentId,
    created_at: at,
  }
  db.events.push(event)
  // Notified once the request's last write is done (contract-phase3 §3.3; http.ts).
  db.pendingEvents.push(event)
  idea.last_activity_at = at
}

export function addWatcher(db: MockDb, ideaId: string, userId: string): void {
  db.watchers.add(`${ideaId}:${userId}`)
}

/** Resolves tag names to the project's tags (case-insensitive), creating unknown ones. */
export function resolveTags(db: MockDb, projectId: string, names: string[]): string[] {
  const ids: string[] = []
  for (const raw of names) {
    const name = raw.trim()
    let tag = db.tags.find(
      (t) => t.project_id === projectId && t.name.toLowerCase() === name.toLowerCase(),
    )
    if (!tag) {
      tag = { id: newId(db, ID_KIND.tag), project_id: projectId, name }
      db.tags.push(tag)
    }
    if (!ids.includes(tag.id)) ids.push(tag.id)
  }
  return ids
}

/** Validates a `tags` array: ≤ 10 names of 1–32 chars without commas or line breaks. */
export function parseTags(value: unknown): string[] | undefined {
  if (value === undefined || value === null) return undefined
  if (!Array.isArray(value)) {
    failValidation([
      { loc: ['body', 'tags'], msg: 'Input should be a valid list', type: 'list_type' },
    ])
  }
  if (value.length > 10) {
    failValidation([
      { loc: ['body', 'tags'], msg: 'List should have at most 10 items', type: 'too_long' },
    ])
  }
  return value.map((tag, index) => {
    const name = typeof tag === 'string' ? tag.trim() : ''
    if (!name || name.length > 32 || /[,\r\n\t]/.test(name)) {
      failValidation([
        { loc: ['body', 'tags', index], msg: 'Invalid tag name', type: 'string_pattern_mismatch' },
      ])
    }
    return name
  })
}
