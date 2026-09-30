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

  private constructor(
    readonly baseURL: string,
    readonly context: APIRequestContext,
    readonly me: CurrentUser,
    private readonly csrf: string,
  ) {}

  /** Signs in as `person` with the dev login in a fresh cookie jar. */
  static async as(baseURL: string, person: Person): Promise<Api> {
    const user = await userOf(baseURL, person)
    const context = await request.newContext({ baseURL })
    await ok(await context.post(`${API}/auth/dev/login`, { data: { user_id: user.id } }))
    const { cookies } = await context.storageState()
    const csrf = cookies.find((cookie) => cookie.name === 'soundings_csrf')?.value
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

  listIdeas(slug: string, query = ''): Promise<IdeaPage> {
    return this.get(`/projects/${slug}/ideas${query ? `?${query}` : ''}`)
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
