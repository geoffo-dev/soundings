import type { IdeaFilters, IdeaStatus } from '@/api/types'

/**
 * The one query-key factory. Every cached query uses a key from here, so
 * invalidation can target a whole area (`queryKeys.ideas.all`) or one entry.
 * Keys are hierarchical arrays: a prefix matches everything below it.
 *
 *   auth       ['auth', 'me'] · ['auth', 'dev-users']
 *   users      ['users', 'search', {q, project}]
 *   projects   ['projects', 'list', {includeArchived}] · ['projects', 'detail', slug, …]
 *   ideas      ['ideas', 'list', slug, filters] · ['ideas', 'board', slug, filters] ·
 *              ['ideas', 'detail', KEY]
 *   evaluations ['evaluations', KEY, 'all' | 'mine']
 *   activity   ['activity', KEY]
 *   work       ['work', 'summary'] · ['work', 'owned', status]
 *   search     ['search', q]
 *
 * Ideas are cached by their upper-case key ("CUST-12"): the SPA's URLs use keys
 * and every `/ideas/{idea}` route accepts one. Use `ideaCacheId()` to normalise.
 */

/** Normalises an idea reference for cache keys: keys upper-case, UUIDs lower-case. */
export function ideaCacheId(idea: string): string {
  return UUID_PATTERN.test(idea) ? idea.toLowerCase() : idea.toUpperCase()
}

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

/** Drops empty filter values so equivalent filters share one cache entry. */
export function normaliseFilters(filters: IdeaFilters = {}): IdeaFilters {
  const out: Record<string, unknown> = {}
  const entries: [string, unknown][] = Object.entries(filters)
  for (const [key, value] of entries) {
    if (value === undefined || value === null || value === false || value === '') continue
    if (Array.isArray(value)) {
      if (value.length === 0) continue
      out[key] = value.map(String).sort()
    } else out[key] = value
  }
  return out
}

export const queryKeys = {
  auth: {
    all: ['auth'] as const,
    me: () => ['auth', 'me'] as const,
    devUsers: () => ['auth', 'dev-users'] as const,
  },
  users: {
    all: ['users'] as const,
    search: (params: { q?: string; project?: string }) =>
      ['users', 'search', { q: params.q ?? '', project: params.project ?? null }] as const,
  },
  projects: {
    all: ['projects'] as const,
    lists: () => ['projects', 'list'] as const,
    list: (includeArchived = false) => ['projects', 'list', { includeArchived }] as const,
    detail: (slug: string) => ['projects', 'detail', slug] as const,
    members: (slug: string) => ['projects', 'detail', slug, 'members'] as const,
    tags: (slug: string) => ['projects', 'detail', slug, 'tags'] as const,
  },
  ideas: {
    all: ['ideas'] as const,
    lists: () => ['ideas', 'list'] as const,
    projectLists: (slug: string) => ['ideas', 'list', slug] as const,
    list: (slug: string, filters?: IdeaFilters) =>
      ['ideas', 'list', slug, normaliseFilters(filters)] as const,
    boards: () => ['ideas', 'board'] as const,
    projectBoards: (slug: string) => ['ideas', 'board', slug] as const,
    board: (slug: string, filters?: IdeaFilters) =>
      ['ideas', 'board', slug, normaliseFilters(filters)] as const,
    details: () => ['ideas', 'detail'] as const,
    detail: (idea: string) => ['ideas', 'detail', ideaCacheId(idea)] as const,
  },
  evaluations: {
    all: ['evaluations'] as const,
    idea: (idea: string) => ['evaluations', ideaCacheId(idea)] as const,
    list: (idea: string) => ['evaluations', ideaCacheId(idea), 'all'] as const,
    mine: (idea: string) => ['evaluations', ideaCacheId(idea), 'mine'] as const,
  },
  activity: {
    all: ['activity'] as const,
    idea: (idea: string) => ['activity', ideaCacheId(idea)] as const,
  },
  work: {
    all: ['work'] as const,
    summary: () => ['work', 'summary'] as const,
    owned: (status?: IdeaStatus) => ['work', 'owned', status ?? 'all'] as const,
  },
  search: {
    all: ['search'] as const,
    query: (q: string, limit?: number) => ['search', q.trim().toLowerCase(), limit ?? 8] as const,
  },
}
