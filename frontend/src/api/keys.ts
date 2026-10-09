import type { IdeaFilters, IdeaStatus } from '@/api/types'

/**
 * The one query-key factory. Every cached query uses a key from here, so
 * invalidation can target a whole area (`queryKeys.ideas.all`) or one entry.
 * Keys are hierarchical arrays: a prefix matches everything below it.
 *
 *   auth       ['auth', 'me'] · ['auth', 'dev-users'] · ['auth', 'config']
 *   groups     ['groups', 'search', q]
 *   users      ['users', 'search', {q, project}]
 *   projects   ['projects', 'list', {includeArchived}] · ['projects', 'detail', slug, …]
 *              (… 'members' · 'groups' · 'access', {q, role})
 *   ideas      ['ideas', 'list', slug, filters] · ['ideas', 'board', slug, filters] ·
 *              ['ideas', 'detail', KEY]
 *   evaluations ['evaluations', KEY, 'all' | 'mine']
 *   activity   ['activity', KEY]
 *   work       ['work', 'summary'] · ['work', 'counts'] · ['work', 'due'] · ['work', 'owned', status]
 *   search     ['search', q]
 *   admin      ['admin', 'users' | 'groups', 'list' | 'detail', …] · ['admin', 'audit', filters] ·
 *              ['admin', 'sso'] · ['admin', 'email'] · ['admin', 'email', 'outbox', …]
 *   notifications ['notifications', 'summary'] · ['notifications', 'list', {unread}] ·
 *              ['notifications', 'preferences'] · ['notifications', 'unsubscribe', token]
 *   proposals  ['proposals', KEY, 'view' | 'threads' | 'suggestions']
 *   research   ['research', KEY, 'checklist' | 'similar'] (project settings: ['projects', 'detail',
 *              slug, 'proposal-template' | 'research'])
 *   apiKeys    ['api-keys', 'mine'] (admin: ['admin', 'api-keys', 'list', filters])
 *   ai         ['ai', KEY, 'runs'] · ['ai', KEY, 'run', runId] (admin: ['admin', 'ai-agents'])
 *   public     ['public', 'project', slug] · ['public', 'track', token] (public pages, no session)
 *   branding   ['branding', 'effective'] · ['branding', 'global'] · ['branding', 'project', slug]
 *   submissions ['submissions', 'form', slug] · ['submissions', 'moderation', slug] ·
 *              ['submissions', 'idea', KEY]
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
    config: () => ['auth', 'config'] as const,
  },
  groups: {
    all: ['groups'] as const,
    search: (q: string) => ['groups', 'search', q.trim().toLowerCase()] as const,
  },
  users: {
    all: ['users'] as const,
    search: (params: { q?: string; project?: string; includeNonMembers?: boolean }) =>
      [
        'users',
        'search',
        {
          q: params.q ?? '',
          project: params.project ?? null,
          everyone: params.includeNonMembers ?? false,
        },
      ] as const,
  },
  projects: {
    all: ['projects'] as const,
    lists: () => ['projects', 'list'] as const,
    list: (includeArchived = false) => ['projects', 'list', { includeArchived }] as const,
    detail: (slug: string) => ['projects', 'detail', slug] as const,
    members: (slug: string) => ['projects', 'detail', slug, 'members'] as const,
    groupGrants: (slug: string) => ['projects', 'detail', slug, 'groups'] as const,
    access: (slug: string, params: { q?: string; role?: string } = {}) =>
      [
        'projects',
        'detail',
        slug,
        'access',
        { q: params.q?.trim().toLowerCase() ?? '', role: params.role ?? null },
      ] as const,
    accessAll: (slug: string) => ['projects', 'detail', slug, 'access'] as const,
    tags: (slug: string) => ['projects', 'detail', slug, 'tags'] as const,
    /** Phase 8: the project's proposal template and research settings (`api/research.ts`). */
    proposalTemplate: (slug: string) => ['projects', 'detail', slug, 'proposal-template'] as const,
    research: (slug: string) => ['projects', 'detail', slug, 'research'] as const,
  },
  /** Phase 8: an idea's research checklist and "Similar ideas" (`api/research.ts`). */
  research: {
    all: ['research'] as const,
    idea: (idea: string) => ['research', ideaCacheId(idea)] as const,
    checklist: (idea: string) => ['research', ideaCacheId(idea), 'checklist'] as const,
    similar: (idea: string) => ['research', ideaCacheId(idea), 'similar'] as const,
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
    counts: () => ['work', 'counts'] as const,
    due: () => ['work', 'due'] as const,
    /** Phase 8b: "Research to do" pages after the first 50 (`GET /me/research-to-do`). */
    research: () => ['work', 'research'] as const,
    owned: (status?: IdeaStatus) => ['work', 'owned', status ?? 'all'] as const,
  },
  search: {
    all: ['search'] as const,
    query: (q: string, limit?: number) => ['search', q.trim().toLowerCase(), limit ?? 8] as const,
  },
  /** Admin settings (`api/admin.ts`): users, groups, the audit log and the SSO view. */
  admin: {
    all: ['admin'] as const,
    users: () => ['admin', 'users'] as const,
    userList: (filters: Record<string, unknown>) => ['admin', 'users', 'list', filters] as const,
    user: (id: string) => ['admin', 'users', 'detail', id.toLowerCase()] as const,
    groups: () => ['admin', 'groups'] as const,
    groupList: (q: string) => ['admin', 'groups', 'list', q.trim().toLowerCase()] as const,
    group: (id: string) => ['admin', 'groups', 'detail', id.toLowerCase()] as const,
    groupMembers: (id: string, q: string) =>
      ['admin', 'groups', 'detail', id.toLowerCase(), 'members', q.trim().toLowerCase()] as const,
    audit: (filters: Record<string, unknown>) => ['admin', 'audit', filters] as const,
    sso: () => ['admin', 'sso'] as const,
    /** Admin settings → Email (contract-phase3 §3.10): the config and the outbox. */
    email: () => ['admin', 'email'] as const,
    emailConfig: () => ['admin', 'email', 'config'] as const,
    outboxes: () => ['admin', 'email', 'outbox'] as const,
    outbox: (filters: Record<string, unknown>) =>
      ['admin', 'email', 'outbox', 'list', filters] as const,
    outboxEmail: (id: string) => ['admin', 'email', 'outbox', 'detail', id.toLowerCase()] as const,
    /** Phase 5: Admin settings → API keys (`api/api-keys.ts`). */
    apiKeys: () => ['admin', 'api-keys'] as const,
    apiKeyList: (filters: Record<string, unknown>) =>
      ['admin', 'api-keys', 'list', filters] as const,
    /** Phase 6: Admin settings → AI agents (`api/ai-agents.ts`). */
    aiAgents: () => ['admin', 'ai-agents'] as const,
  },
  /** Phase 6: an idea's AI runs (`api/ai.ts`): the list (with permissions) and one run's events. */
  ai: {
    all: ['ai'] as const,
    idea: (idea: string) => ['ai', ideaCacheId(idea)] as const,
    runs: (idea: string) => ['ai', ideaCacheId(idea), 'runs'] as const,
    run: (idea: string, runId: string) =>
      ['ai', ideaCacheId(idea), 'run', runId.toLowerCase()] as const,
  },
  /** Phase 5: your API keys (`api/api-keys.ts`). */
  apiKeys: {
    all: ['api-keys'] as const,
    mine: () => ['api-keys', 'mine'] as const,
  },
  /** Phase 4: an idea's proposal (`api/proposals.ts`): the tab's view and its margin threads. */
  proposals: {
    all: ['proposals'] as const,
    idea: (idea: string) => ['proposals', ideaCacheId(idea)] as const,
    view: (idea: string) => ['proposals', ideaCacheId(idea), 'view'] as const,
    threads: (idea: string) => ['proposals', ideaCacheId(idea), 'threads'] as const,
    /** Phase 5: pending suggestions (from people, MCP clients and AI agents). */
    suggestions: (idea: string) => ['proposals', ideaCacheId(idea), 'suggestions'] as const,
  },
  /** Phase 4: the public form and tracking pages (`api/public.ts`); no session. */
  public: {
    all: ['public'] as const,
    project: (slug: string) => ['public', 'project', slug.toLowerCase()] as const,
    /** In memory only (the token never reaches a URL the server sees). */
    tracking: (token: string) => ['public', 'track', token] as const,
  },
  /** Phase 4: branding (`api/branding.ts`): what the app shows, and the settings forms. */
  branding: {
    all: ['branding'] as const,
    effective: () => ['branding', 'effective'] as const,
    global: () => ['branding', 'global'] as const,
    project: (slug: string) => ['branding', 'project', slug] as const,
  },
  /** Phase 4: public form settings, moderation and submitters (`api/submissions.ts`). */
  submissions: {
    all: ['submissions'] as const,
    form: (slug: string) => ['submissions', 'form', slug] as const,
    moderation: (slug: string) => ['submissions', 'moderation', slug] as const,
    moderationAll: () => ['submissions', 'moderation'] as const,
    idea: (idea: string) => ['submissions', 'idea', ideaCacheId(idea)] as const,
  },
  /** The inbox, the bell's summary and email preferences (`api/notifications.ts`). */
  notifications: {
    all: ['notifications'] as const,
    summary: () => ['notifications', 'summary'] as const,
    lists: () => ['notifications', 'list'] as const,
    list: (params: { unread?: boolean } = {}) =>
      ['notifications', 'list', { unread: params.unread ?? false }] as const,
    preferences: () => ['notifications', 'preferences'] as const,
    /** Public (no session): what an unsubscribe link turns off. */
    unsubscribe: (token: string) => ['notifications', 'unsubscribe', token] as const,
  },
}
