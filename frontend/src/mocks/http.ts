/**
 * Plumbing shared by the mock handlers: problem+json responses, the session
 * and CSRF checks, JSON body parsing, latency and failure injection.
 *
 * Handlers are written with `route(method, path, resolver, options)`. A
 * resolver gets `{ request, params, url, db, user }` and returns data (sent as
 * JSON), a Response, or throws `fail(...)` to answer with a problem. The check
 * order follows the contract: 401 → 403 csrf → 422 shape → 404 → 403 → 422 → 409.
 */
import { delay, http, HttpResponse, type PathParams } from 'msw'

import { methodAvailable } from './auth-config'
import { getDb, type MockDb, type MockUser } from './db'
import { findUser, InvalidCursorError, invalidateIndexes } from './domain'
import { flushFanOut } from './notifications'
import { clearLostResearchers, researcherRoles } from './researchers'
import { csrfToken, sessionUserId, storedAuthMethod } from './session'

/** Matches the API on any origin (the dev server, jsdom, Playwright). */
export const API = '*/api/v1'

const TITLES: Record<number, string> = {
  400: 'Bad Request',
  401: 'Unauthorized',
  403: 'Forbidden',
  404: 'Not Found',
  409: 'Conflict',
  422: 'Unprocessable Content',
  413: 'Content Too Large',
  415: 'Unsupported Media Type',
  429: 'Too Many Requests',
  500: 'Internal Server Error',
  503: 'Service Unavailable',
}

export function problemResponse(
  status: number,
  code: string,
  detail?: string,
  extra?: Record<string, unknown>,
): Response {
  return HttpResponse.json(
    {
      type: `urn:soundings:problem:${code}`,
      title: TITLES[status] ?? 'Error',
      status,
      detail: detail ?? null,
      instance: null,
      code,
      request_id: null,
      ...extra,
    },
    { status, headers: { 'Content-Type': 'application/problem+json' } },
  )
}

/** Throw inside a resolver to answer with a problem. */
export function fail(status: number, code: string, detail?: string): never {
  throw problemResponse(status, code, detail)
}

export interface FieldIssue {
  loc: (string | number)[]
  msg: string
  type: string
}

export function failValidation(errors: FieldIssue[], code = 'validation_error'): never {
  throw problemResponse(422, code, 'The request is invalid.', { errors })
}

export function notFound(what = 'Not found.'): never {
  fail(404, 'not_found', what)
}

export function forbidden(code = 'forbidden', detail?: string): never {
  fail(403, code, detail)
}

export function conflict(code: string, detail?: string): never {
  fail(409, code, detail)
}

/** 429 `too_many_attempts` (or another code) with `Retry-After` in seconds. */
export function tooManyAttempts(
  retryAfterSeconds: number,
  detail = 'Too many attempts. Try again shortly.',
  code = 'too_many_attempts',
  status = 429,
): never {
  const response = problemResponse(status, code, detail)
  response.headers.set('Retry-After', String(Math.max(1, Math.ceil(retryAfterSeconds))))
  throw response
}

/* ------------------------------------------------------------------ */
/* Request helpers                                                     */
/* ------------------------------------------------------------------ */

export async function readJson(request: Request): Promise<Record<string, unknown>> {
  let body: unknown
  try {
    body = await request.json()
  } catch {
    failValidation([{ loc: ['body'], msg: 'Body must be JSON.', type: 'json_invalid' }])
  }
  if (typeof body !== 'object' || body === null || Array.isArray(body)) {
    failValidation([{ loc: ['body'], msg: 'Body must be an object.', type: 'model_type' }])
  }
  return body as Record<string, unknown>
}

/** Rejects unknown fields (the API's request models forbid extras). */
export function allowOnly(body: Record<string, unknown>, fields: string[]): void {
  const extra = Object.keys(body).filter((key) => !fields.includes(key))
  if (extra.length > 0) {
    failValidation(
      extra.map((key) => ({
        loc: ['body', key],
        msg: 'Extra inputs are not permitted',
        type: 'extra_forbidden',
      })),
    )
  }
}

/** A trimmed string field; `required` fails when missing or empty. */
export function stringField(
  body: Record<string, unknown>,
  field: string,
  options: { required?: boolean; max?: number; min?: number } = {},
): string | undefined {
  const { required = false, max = Infinity } = options
  const min = options.min ?? (required ? 1 : 0)
  const value = body[field]
  if (value === undefined || value === null) {
    if (required) failValidation([{ loc: ['body', field], msg: 'Field required', type: 'missing' }])
    return undefined
  }
  if (typeof value !== 'string') {
    failValidation([
      { loc: ['body', field], msg: 'Input should be a valid string', type: 'string_type' },
    ])
  }
  const trimmed = value.trim()
  if (trimmed.length < min) {
    failValidation([
      {
        loc: ['body', field],
        msg: `String should have at least ${min} character${min === 1 ? '' : 's'}`,
        type: 'string_too_short',
      },
    ])
  }
  if (trimmed.length > max) {
    failValidation([
      {
        loc: ['body', field],
        msg: `String should have at most ${max} characters`,
        type: 'string_too_long',
      },
    ])
  }
  return trimmed
}

export function queryList(url: URL, name: string): string[] {
  return url.searchParams
    .getAll(name)
    .flatMap((value) => value.split(','))
    .filter(Boolean)
}

export function queryBool(url: URL, name: string): boolean {
  const value = url.searchParams.get(name)
  if (value === null) return false
  if (['true', '1', 'yes', 'on'].includes(value.toLowerCase())) return true
  if (['false', '0', 'no', 'off'].includes(value.toLowerCase())) return false
  failValidation([
    { loc: ['query', name], msg: 'Input should be a valid boolean', type: 'bool_parsing' },
  ])
}

/** A boolean filter that is off when absent (`active=`, `platform_admin=`…): null, true or false. */
export function queryOptionalBool(url: URL, name: string): boolean | null {
  return url.searchParams.has(name) ? queryBool(url, name) : null
}

/** A UUID query parameter (null when absent; 422 when malformed). */
export function queryUuid(url: URL, name: string): string | null {
  const value = url.searchParams.get(name)
  if (value === null || value === '') return null
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value)) {
    failValidation([
      { loc: ['query', name], msg: 'Input should be a valid UUID', type: 'uuid_parsing' },
    ])
  }
  return value.toLowerCase()
}

/** A text query parameter, trimmed (null when absent or empty; 422 over `max`). */
export function queryText(url: URL, name: string, max: number): string | null {
  const value = url.searchParams.get(name)
  if (value === null) return null
  if (value.length > max) {
    failValidation([
      {
        loc: ['query', name],
        msg: `String should have at most ${max} characters`,
        type: 'string_too_long',
      },
    ])
  }
  return value.trim() || null
}

export function queryLimit(url: URL, fallback = 50, max = 200): number {
  const raw = url.searchParams.get('limit')
  if (raw === null) return fallback
  const value = Number(raw)
  if (!Number.isInteger(value) || value < 1 || value > max) {
    failValidation([
      {
        loc: ['query', 'limit'],
        msg: `Input should be between 1 and ${max}`,
        type: 'less_than_equal',
      },
    ])
  }
  return value
}

export function queryEnum<T extends string>(url: URL, name: string, allowed: readonly T[]): T[] {
  const values = queryList(url, name)
  const bad = values.find((value) => !allowed.includes(value as T))
  if (bad !== undefined) {
    failValidation([
      { loc: ['query', name], msg: `Input should be ${allowed.join(', ')}`, type: 'enum' },
    ])
  }
  return values as T[]
}

/* ------------------------------------------------------------------ */
/* Mock settings (localStorage, dev only)                              */
/* ------------------------------------------------------------------ */

export const MOCK_LATENCY_STORAGE_KEY = 'soundings-mock-latency'
export const MOCK_FAIL_STORAGE_KEY = 'soundings-mock-fail'

function setting(key: string): string | null {
  try {
    return typeof localStorage === 'undefined' ? null : localStorage.getItem(key)
  } catch {
    return null
  }
}

/**
 * `soundings-mock-latency`: "none", a number of ms, or unset for realistic
 * 100–400 ms (5 ms under Node). `soundings-mock-fail`: requests whose path
 * contains this text answer 500, to check error states.
 */
async function simulateNetwork(url: URL): Promise<void> {
  const latency = setting(MOCK_LATENCY_STORAGE_KEY)
  if (latency !== 'none')
    await delay(latency && /^\d+$/.test(latency) ? Number(latency) : undefined)
  const failing = setting(MOCK_FAIL_STORAGE_KEY)
  if (failing && url.pathname.includes(failing)) {
    fail(500, 'internal_error', `Simulated failure (localStorage "${MOCK_FAIL_STORAGE_KEY}").`)
  }
}

/* ------------------------------------------------------------------ */
/* Routes                                                              */
/* ------------------------------------------------------------------ */

type Method = 'get' | 'post' | 'put' | 'patch' | 'delete'

export interface RouteContext {
  request: Request
  params: PathParams
  url: URL
  db: MockDb
  user: MockUser
}

export type PublicRouteContext = Omit<RouteContext, 'user'> & { user: MockUser | null }

export interface Reply {
  status?: number
  body?: unknown
}

type Resolver<C> = (context: C) => unknown

/**
 * The signed-in user, or null: the session must name an active user, and its
 * sign-in method must still be available (contract-phase2 §3.9).
 */
function sessionUser(db: MockDb): MockUser | null {
  const user = findUser(db, sessionUserId())
  if (!user?.is_active) return null
  const method = storedAuthMethod()
  if (method && !methodAvailable(method)) return null
  return user
}

/** A signed-in route (401 without a session; CSRF on unsafe methods). */
export function route(method: Method, path: string, resolver: Resolver<RouteContext>) {
  return http[method](`${API}${path}`, async ({ request, params }) => {
    const url = new URL(request.url)
    return run(method, url, () => {
      const db = getDb()
      const user = sessionUser(db)
      if (!user) fail(401, 'unauthorized', 'Sign in to continue.')
      checkCsrf(method, request)
      if (method === 'get') return resolver({ request, params, url, db, user })
      // Phase 8b (S1 b): whatever takes someone's role in a private project away ends
      // their research assignments there; compare before and after every write.
      const before = researcherRoles(db)
      const result = resolver({ request, params, url, db, user })
      const settle = () => clearLostResearchers(db, user, before)
      if (result instanceof Promise) return result.then((value: unknown) => (settle(), value))
      settle()
      return result
    })
  })
}

/** A route that works without a session (sign-in, logout, list dev users). */
export function publicRoute(method: Method, path: string, resolver: Resolver<PublicRouteContext>) {
  return http[method](`${API}${path}`, async ({ request, params }) => {
    const url = new URL(request.url)
    return run(method, url, () => {
      const db = getDb()
      return resolver({ request, params, url, db, user: sessionUser(db) })
    })
  })
}

function checkCsrf(method: Method, request: Request): void {
  if (method === 'get') return
  const token = csrfToken()
  if (!token || request.headers.get('X-CSRF-Token') !== token) {
    fail(403, 'csrf_failed', 'Missing or invalid CSRF token.')
  }
}

async function run(method: Method, url: URL, body: () => unknown): Promise<Response> {
  try {
    await simulateNetwork(url)
    const result = await body()
    // One fan-out per request, after its last write (contract-phase3 §3.3).
    if (method !== 'get') flushFanOut(getDb())
    if (method !== 'get') invalidateIndexes()
    if (result instanceof Response) return result
    if (result === undefined) return new HttpResponse(null, { status: 204 })
    const reply = result as Reply
    if (isReply(reply)) {
      return reply.body === undefined
        ? new HttpResponse(null, { status: reply.status ?? 204 })
        : HttpResponse.json(reply.body as never, { status: reply.status ?? 200 })
    }
    return HttpResponse.json(result as never)
  } catch (error) {
    // A failed request notifies nobody (its transaction would roll back).
    getDb().pendingEvents.length = 0
    if (method !== 'get') invalidateIndexes()
    if (error instanceof Response) return error
    if (error instanceof InvalidCursorError) {
      return problemResponse(400, 'invalid_cursor', 'The pagination cursor is invalid.')
    }
    throw error
  }
}

const REPLY = Symbol('reply')

/** Return `created(body)` for 201s, `accepted(body)` for 202s and `noContent()` for 204s. */
export function created(body: unknown): Reply {
  return { status: 201, body, [REPLY]: true } as Reply
}

/** 202: queued for the worker (the test email). */
export function accepted(body: unknown): Reply {
  return { status: 202, body, [REPLY]: true } as Reply
}

export function noContent(): Reply {
  return { status: 204, [REPLY]: true } as Reply
}

/** Wraps a plain JSON value that could be mistaken for a Reply (e.g. `null`). */
export function json(body: unknown): Response {
  return HttpResponse.json(body as never)
}

function isReply(value: unknown): value is Reply {
  return typeof value === 'object' && value !== null && REPLY in value
}
