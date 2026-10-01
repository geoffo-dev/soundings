import { expect, request, type APIRequestContext, type APIResponse } from '@playwright/test'

import type { components } from '../../../frontend/src/api/generated/schema'

/**
 * A signed-in API client for arranging and checking data in the e2e tests. It goes
 * through the real HTTP API (dev login, session cookie, CSRF header), never the
 * database, so every arrangement obeys the same rules the UI does.
 */

type Schemas = components['schemas']
export type CurrentUser = Schemas['CurrentUser']
export type IdeaDetail = Schemas['IdeaDetail']
export type IdeaPage = Schemas['IdeaPage']
export type IdeaSummary = Schemas['IdeaSummary']
export type Board = Schemas['Board']
export type Project = Schemas['Project']
export type Work = Schemas['Work']
export type MyEvaluation = Schemas['MyEvaluation']
export type EvaluationList = Schemas['EvaluationList']
export type SearchResults = Schemas['SearchResults']
export type ProjectRole = Schemas['ProjectRole']
export type IdeaStatus = Schemas['IdeaStatus']
export type Recommendation = Schemas['Recommendation']
export type AuthConfig = Schemas['AuthConfig']
export type AdminUser = Schemas['AdminUser']
export type AdminUserSummary = Schemas['AdminUserSummary']
export type Group = Schemas['Group']
export type GroupMember = Schemas['GroupMember']
export type GroupSyncMode = Schemas['GroupSyncMode']
export type MappingTestResult = Schemas['MappingTestResult']
export type AuditEntry = Schemas['AuditEntry']
export type ProjectAccessEntry = Schemas['ProjectAccessEntry']
export type ProjectGroupGrant = Schemas['ProjectGroupGrant']
export type SsoConfig = Schemas['SsoConfig']
// Phase 3: notifications and email (contract-phase3).
export type NotificationItem = Schemas['NotificationPage']['items'][number]
export type NotificationSummary = Schemas['NotificationSummary']
export type NotificationPreferences = Schemas['NotificationPreferences']
export type NotificationType = Schemas['NotificationType']
export type NotificationMode = Schemas['NotificationMode']
export type UnsubscribeInfo = Schemas['UnsubscribeInfo']
export type EmailConfig = Schemas['EmailConfig']
export type OutboxEmail = Schemas['OutboxEmail']
export type EmailStatus = Schemas['EmailStatus']
export type CommentActivity = Schemas['CommentActivity']

/** The seeded people (backend/app/seed/content.py), by username. */
export const PEOPLE = {
  alice: 'Alice Anders', // platform admin; admin of Customer Innovation
  amara: 'Amara Okafor',
  bob: 'Bob Brown',
  carol: 'Carol Chen',
  dave: 'Dave Davies',
  erin: 'Erin Evans', // viewer in Customer Innovation
  farah: 'Farah Haddad',
  kenji: 'Kenji Watanabe',
  mateo: 'Mateo Rodríguez',
  priya: 'Priya Raman',
  sven: 'Sven Lindqvist',
  zanele: 'Zanele Dlamini',
} as const
export type Person = keyof typeof PEOPLE

const API = '/api/v1'
const devUsers = new Map<string, Promise<Map<string, CurrentUser>>>()

/** The dev users by username (the part of the email before @), cached per base URL. */
export function usersByName(baseURL: string): Promise<Map<string, CurrentUser>> {
  let users = devUsers.get(baseURL)
  if (!users) {
    users = (async () => {
      const context = await request.newContext({ baseURL })
      try {
        const response = await context.get(`${API}/auth/dev/users`)
        expect(response.status(), 'dev login must be enabled on the app under test').toBe(200)
        const list = (await response.json()) as CurrentUser[]
        return new Map(list.map((user) => [user.email.split('@')[0] ?? user.email, user]))
      } finally {
        await context.dispose()
      }
    })()
    devUsers.set(baseURL, users)
  }
  return users
}

export async function userOf(baseURL: string, person: Person): Promise<CurrentUser> {
  const user = (await usersByName(baseURL)).get(person)
  if (!user) throw new Error(`No dev user "${person}": is the demo data seeded?`)
  return user
}

const authConfigs = new Map<string, Promise<AuthConfig>>()

/** The app's sign-in methods (`GET /auth/config`), cached per base URL. */
export function authConfig(baseURL: string): Promise<AuthConfig> {
  let config = authConfigs.get(baseURL)
  if (!config) {
    config = (async () => {
      const context = await request.newContext({ baseURL })
      try {
        return (await ok<AuthConfig>(await context.get(`${API}/auth/config`))) as AuthConfig
      } finally {
        await context.dispose()
      }
    })()
    authConfigs.set(baseURL, config)
  }
  return config
}

/** A short random suffix, so tests can run twice against the same database. */
export function uniqueSuffix(): string {
  return `${Date.now().toString(36).slice(-4)}${Math.random().toString(36).slice(2, 5)}`
}

/** Project keys are 2-6 upper-case letters/digits starting with a letter. */
export function uniqueKey(prefix = 'E'): string {
  return `${prefix}${uniqueSuffix().toUpperCase()}`.slice(0, 6)
}

/** `due` days from now at 17:00 UTC, as ISO 8601 (the API wants an offset). */
export function daysFromNow(days: number): string {
  const date = new Date()
  date.setUTCDate(date.getUTCDate() + days)
  date.setUTCHours(17, 0, 0, 0)
  return date.toISOString()
}

async function ok<T>(response: APIResponse, status = 200): Promise<T> {
  const body = await response.text()
  expect(response.status(), `${response.url()}: ${body}`).toBe(status)
  return (body ? JSON.parse(body) : null) as T
}

export class Api {
  /** Slugs of projects this client created (archived by the fixture afterwards). */
  readonly created: string[] = []
  /** Ids of groups this client created (deleted by the fixture afterwards). */
  readonly createdGroups: string[] = []

  private constructor(
    readonly baseURL: string,
    readonly context: APIRequestContext,
    readonly me: CurrentUser,
    private readonly csrf: string,
  ) {}

  /** Signs in as `person` with the dev login in a fresh cookie jar. */
  static async as(baseURL: string, person: Person): Promise<Api> {
    return Api.asUser(baseURL, await userOf(baseURL, person))
  }

  /** Signs in as any active user (e.g. one a test created) with the dev login. */
  static async asUser(baseURL: string, user: CurrentUser): Promise<Api> {
    const context = await request.newContext({ baseURL })
    await ok(await context.post(`${API}/auth/dev/login`, { data: { user_id: user.id } }))
    const { cookies } = await context.storageState()
    const csrf = cookies.find((cookie) => /^(__Host-)?soundings_csrf$/.test(cookie.name))?.value
    if (!csrf) throw new Error('dev login set no soundings_csrf cookie')
    return new Api(baseURL, context, user, csrf)
  }

  /**
   * Archives the projects this client created, so repeated runs against one database
   * don't pile them up in the sidebar and My work (archived projects are hidden).
   */
  async archiveCreated() {
    for (const slug of this.created.splice(0)) {
      await this.raw('PATCH', `/projects/${slug}`, { archived: true })
    }
    for (const id of this.createdGroups.splice(0)) {
      await this.raw('DELETE', `/admin/groups/${id}`)
    }
  }

  dispose() {
    return this.context.dispose()
  }

  raw(method: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE', path: string, data?: unknown) {
    return this.context.fetch(`${API}${path}`, {
      method,
      data,
      headers: method === 'GET' ? {} : { 'X-CSRF-Token': this.csrf },
    })
  }

  async get<T>(path: string): Promise<T> {
    return ok<T>(await this.raw('GET', path))
  }

  async send<T>(
    method: 'POST' | 'PUT' | 'PATCH' | 'DELETE',
    path: string,
    data?: unknown,
    status = 200,
  ): Promise<T> {
    return ok<T>(await this.raw(method, path, data), status)
  }

  // --- Projects ----------------------------------------------------------------------
  async createProject(body: {
    name: string
    slug: string
    key: string
    visibility?: 'private' | 'internal'
    admin?: CurrentUser
  }): Promise<Project> {
    const { admin, ...rest } = body
    const project = await this.send<Project>(
      'POST',
      '/projects',
      { ...rest, admin_user_id: admin?.id },
      201,
    )
    this.created.push(project.slug)
    return project
  }

  async addMember(slug: string, person: Person, role: ProjectRole = 'member') {
    const user = await userOf(this.baseURL, person)
    return this.send('POST', `/projects/${slug}/members`, { user_id: user.id, role }, 201)
  }

  project(slug: string): Promise<Project> {
    return this.get(`/projects/${slug}`)
  }

  // --- Ideas -------------------------------------------------------------------------
  createIdea(
    slug: string,
    body: { title: string; summary: string; tags?: string[] },
  ): Promise<IdeaDetail> {
    return this.send('POST', `/projects/${slug}/ideas`, body, 201)
  }

  idea(key: string): Promise<IdeaDetail> {
    return this.get(`/ideas/${key}`)
  }

  async setOwner(key: string, person: Person | null): Promise<IdeaDetail> {
    const user_id = person ? (await userOf(this.baseURL, person)).id : null
    return this.send('PUT', `/ideas/${key}/owner`, { user_id })
  }

  changeStatus(key: string, status: IdeaStatus): Promise<IdeaDetail> {
    return this.send('POST', `/ideas/${key}/status`, { status })
  }

  async invite(key: string, people: Person[], dueAt?: string): Promise<IdeaDetail> {
    const users = await Promise.all(people.map((person) => userOf(this.baseURL, person)))
    return this.send('POST', `/ideas/${key}/evaluators`, {
      user_ids: users.map((user) => user.id),
      due_at: dueAt,
    })
  }

  /** Saves this user's evaluation; `scores` maps criterion names to 1-5. */
  async evaluate(
    key: string,
    scores: Record<string, number>,
    options: { recommendation?: Recommendation; comment?: string; submit?: boolean } = {},
  ): Promise<MyEvaluation> {
    const idea = await this.idea(key)
    const project = await this.project(idea.project.slug)
    const byName = new Map(project.rubric.map((criterion) => [criterion.name, criterion.id]))
    return this.send('PUT', `/ideas/${key}/evaluations/me`, {
      scores: Object.entries(scores).map(([name, score]) => {
        const id = byName.get(name)
        if (!id) throw new Error(`No criterion "${name}" in ${project.slug}`)
        return { criterion_id: id, score }
      }),
      recommendation: options.recommendation ?? null,
      comment: options.comment ?? '',
      submit: options.submit ?? true,
    })
  }

  /** Adds anyone (by account) to a project. */
  addMemberUser(slug: string, user: { id: string }, role: ProjectRole = 'member') {
    return this.send('POST', `/projects/${slug}/members`, { user_id: user.id, role }, 201)
  }

  async setOwnerUser(key: string, user: { id: string }): Promise<IdeaDetail> {
    return this.send('PUT', `/ideas/${key}/owner`, { user_id: user.id })
  }

  inviteUsers(key: string, users: { id: string }[], dueAt?: string): Promise<IdeaDetail> {
    return this.send('POST', `/ideas/${key}/evaluators`, {
      user_ids: users.map((user) => user.id),
      due_at: dueAt,
    })
  }

  comment(key: string, bodyMd: string): Promise<CommentActivity> {
    return this.send('POST', `/ideas/${key}/comments`, { body_md: bodyMd }, 201)
  }

  unwatch(key: string) {
    return this.send('DELETE', `/ideas/${key}/watch`)
  }

  listIdeas(slug: string, query = ''): Promise<IdeaPage> {
    return this.get(`/projects/${slug}/ideas${query ? `?${query}` : ''}`)
  }
  // --- Admin: users, groups, audit (platform admins; contract-phase2) ----------------
  /** Users whose name or email contains `q` (the admin list's search). */
  async adminUsers(q: string): Promise<AdminUserSummary[]> {
    const page = await this.get<{ items: AdminUserSummary[] }>(
      `/admin/users?q=${encodeURIComponent(q)}&limit=100`,
    )
    return page.items
  }

  /** The account with exactly this email (case-insensitive), if there is one. */
  async adminUserByEmail(email: string): Promise<AdminUserSummary | undefined> {
    const wanted = email.toLowerCase()
    return (await this.adminUsers(email)).find((user) => user.email.toLowerCase() === wanted)
  }

  adminUser(id: string): Promise<AdminUser> {
    return this.get(`/admin/users/${id}`)
  }

  createUser(body: {
    email: string
    display_name: string
    is_platform_admin?: boolean
    external_ids?: { kind: string; value: string }[]
  }): Promise<AdminUser> {
    return this.send('POST', '/admin/users', body, 201)
  }

  updateUser(
    id: string,
    body: {
      display_name?: string
      email?: string
      is_active?: boolean
      is_platform_admin?: boolean
    },
  ): Promise<AdminUser> {
    return this.send('PATCH', `/admin/users/${id}`, body)
  }

  setExternalIds(id: string, externalIds: { kind: string; value: string }[]): Promise<AdminUser> {
    return this.send('PUT', `/admin/users/${id}/external-ids`, { external_ids: externalIds })
  }

  async createGroup(body: {
    name: string
    description?: string
    sync_mode?: GroupSyncMode
    idp_values?: string[]
  }): Promise<Group> {
    const group = await this.send<Group>('POST', '/admin/groups', body, 201)
    this.createdGroups.push(group.id)
    return group
  }

  group(id: string): Promise<Group> {
    return this.get(`/admin/groups/${id}`)
  }

  async groupByName(name: string): Promise<Group> {
    const page = await this.get<{ items: { id: string; name: string }[] }>(
      `/admin/groups?q=${encodeURIComponent(name)}&limit=100`,
    )
    const found = page.items.find((group) => group.name === name)
    if (!found) throw new Error(`No group named "${name}"`)
    return this.group(found.id)
  }

  replaceMapping(id: string, syncMode: GroupSyncMode, idpValues: string[]): Promise<Group> {
    return this.send('PUT', `/admin/groups/${id}/mapping`, {
      sync_mode: syncMode,
      idp_values: idpValues,
    })
  }

  async groupMembers(id: string): Promise<GroupMember[]> {
    const page = await this.get<{ items: GroupMember[] }>(`/admin/groups/${id}/members?limit=100`)
    return page.items
  }

  addGroupMember(groupId: string, userId: string): Promise<GroupMember> {
    return this.send('POST', `/admin/groups/${groupId}/members`, { user_id: userId }, 201)
  }

  /** The group's role in a project (`add_project_group_grant`). */
  grantGroup(slug: string, groupId: string, role: ProjectRole): Promise<ProjectGroupGrant> {
    return this.send('POST', `/projects/${slug}/groups`, { group_id: groupId, role }, 201)
  }

  /** Everyone with access to the project, with their effective role and its sources. */
  async projectAccess(slug: string): Promise<ProjectAccessEntry[]> {
    const page = await this.get<{ items: ProjectAccessEntry[] }>(
      `/projects/${slug}/access?limit=100`,
    )
    return page.items
  }

  testMapping(claims: Record<string, unknown>, userId?: string): Promise<MappingTestResult> {
    return this.send('POST', '/admin/groups/test-mapping', { claims, user_id: userId ?? null })
  }

  /** Audit entries, newest first, filtered like the viewer (`action` may repeat). */
  async audit(
    filters: {
      action?: string | string[]
      actor_id?: string
      target_type?: string
      target_id?: string
      project_id?: string
      since?: string
    } = {},
  ): Promise<AuditEntry[]> {
    const query = new URLSearchParams({ limit: '100' })
    for (const [key, value] of Object.entries(filters)) {
      for (const item of Array.isArray(value) ? value : [value]) {
        if (item !== undefined) query.append(key, item)
      }
    }
    const page = await this.get<{ items: AuditEntry[] }>(`/admin/audit?${query.toString()}`)
    return page.items
  }

  // --- Notifications and email (contract-phase3) -------------------------------------
  /** The caller's inbox, newest first (first page, up to 100). */
  async notifications(unread = false): Promise<NotificationItem[]> {
    const page = await this.get<{ items: NotificationItem[] }>(
      `/me/notifications?limit=100${unread ? '&unread=true' : ''}`,
    )
    return page.items
  }

  notificationSummary(): Promise<NotificationSummary> {
    return this.get('/me/notifications/summary')
  }

  preferences(): Promise<NotificationPreferences> {
    return this.get('/me/notification-preferences')
  }

  setPreferences(
    changes: Partial<Record<NotificationType, NotificationMode>>,
  ): Promise<NotificationPreferences> {
    return this.send('PATCH', '/me/notification-preferences', changes)
  }

  emailConfig(): Promise<EmailConfig> {
    return this.get('/admin/email')
  }

  async outbox(filters: { status?: EmailStatus; type?: string } = {}): Promise<OutboxEmail[]> {
    const query = new URLSearchParams({ limit: '100' })
    if (filters.status) query.append('status', filters.status)
    if (filters.type) query.append('type', filters.type)
    const page = await this.get<{ items: OutboxEmail[] }>(`/admin/email/outbox?${query}`)
    return page.items
  }

  outboxEmail(id: string): Promise<OutboxEmail> {
    return this.get(`/admin/email/outbox/${id}`)
  }

  sendTestEmail(to?: string): Promise<OutboxEmail> {
    return this.send('POST', '/admin/email/test', to ? { to } : {}, 202)
  }
}

/** Scores for the default rubric (Value, Feasibility, Effort↓, Strategic fit, Risk↓). */
export function defaultRubricScores(
  value: number,
  feasibility: number,
  effort: number,
  fit: number,
  risk: number,
): Record<string, number> {
  return {
    Value: value,
    Feasibility: feasibility,
    Effort: effort,
    'Strategic fit': fit,
    Risk: risk,
  }
}

/**
 * A fresh private project owned by Alice (platform admin) with the given members, so a
 * test can change data without disturbing the seeded story or other tests.
 */
export async function createTeamProject(
  admin: Api,
  name: string,
  members: Partial<Record<Person, ProjectRole>>,
): Promise<Project> {
  const key = uniqueKey()
  const project = await admin.createProject({
    name: `${name} ${key}`,
    slug: `e2e-${key.toLowerCase()}`,
    key,
  })
  for (const [person, role] of Object.entries(members) as [Person, ProjectRole][]) {
    if (person !== admin.me.email.split('@')[0]) await admin.addMember(project.slug, person, role)
  }
  return project
}
