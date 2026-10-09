import {
  canViewProject,
  effectiveRole,
  findProjectBySlug,
  isPickable,
  paginate,
  userSearchResult,
} from '@/mocks/domain'
import { failValidation, notFound, queryBool, queryLimit, route } from '@/mocks/http'

export const userHandlers = [
  route('get', '/users', ({ url, db, user }) => {
    const q = (url.searchParams.get('q') ?? '').trim().toLowerCase()
    if (q.length > 100) {
      failValidation([
        {
          loc: ['query', 'q'],
          msg: 'String should have at most 100 characters',
          type: 'string_too_long',
        },
      ])
    }
    const slug = url.searchParams.get('project')
    // Phase 8b: the researcher picker lists everyone, members with their role.
    const everyone = queryBool(url, 'include_non_members')
    const limit = queryLimit(url)
    let projectId: string | null = null
    if (slug) {
      const project = findProjectBySlug(db, slug)
      if (!project || !canViewProject(db, project, user)) notFound('Project not found.')
      projectId = project.id
    }
    const matches = db.users
      .filter(isPickable)
      .filter(
        (candidate) =>
          !q ||
          candidate.display_name.toLowerCase().includes(q) ||
          candidate.email.toLowerCase().includes(q),
      )
      .map((candidate) => ({
        candidate,
        role: projectId ? effectiveRole(db, projectId, candidate.id) : null,
      }))
      .filter(({ role }) => !projectId || everyone || role !== null)
      .sort((a, b) => a.candidate.display_name.localeCompare(b.candidate.display_name))
    const { page, next_cursor } = paginate(
      matches,
      url.searchParams.get('cursor'),
      limit,
      `users:${q}:${slug ?? ''}:${everyone ? 'all' : ''}`,
    )
    return {
      items: page.map(({ candidate, role }) => userSearchResult(candidate, role)),
      next_cursor,
    }
  }),
]
