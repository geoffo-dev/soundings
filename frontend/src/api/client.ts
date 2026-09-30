import createClient, { type Middleware } from 'openapi-fetch'

import { networkError, toApiError } from '@/api/errors'
import type { paths } from '@/api/generated/schema'

export const CSRF_COOKIE = 'soundings_csrf'
export const CSRF_HEADER = 'X-CSRF-Token'
const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS'])

export function readCookie(name: string, cookies: string = document.cookie): string | undefined {
  for (const part of cookies.split(';')) {
    const [key, ...rest] = part.trim().split('=')
    if (key === name) return decodeURIComponent(rest.join('='))
  }
  return undefined
}

/** Double-submit CSRF: echo the (non-HttpOnly) CSRF cookie in a header on unsafe methods. */
export const csrfMiddleware: Middleware = {
  onRequest({ request }) {
    if (SAFE_METHODS.has(request.method.toUpperCase())) return request
    const token = readCookie(CSRF_COOKIE)
    if (token) request.headers.set(CSRF_HEADER, token)
    return request
  },
}

/** Every non-2xx becomes a thrown ApiError, so TanStack Query sees real errors. */
export const errorMiddleware: Middleware = {
  async onResponse({ response }) {
    if (!response.ok) throw await toApiError(response)
    return response
  },
  // Only called when fetch itself fails. Cancellations (TanStack Query aborts) pass through.
  onError({ error }) {
    if (error instanceof Error && error.name === 'AbortError') return error
    return networkError(error)
  },
}

/** Builds a client with the Soundings defaults and middleware (exported for tests). */
// eslint-disable-next-line @typescript-eslint/no-empty-object-type -- mirrors openapi-fetch's own constraint
export function createApiClient<Paths extends {}>(baseUrl?: string) {
  const client = createClient<Paths>({
    baseUrl:
      baseUrl ?? (typeof window === 'undefined' ? 'http://localhost' : window.location.origin),
    credentials: 'same-origin',
    headers: { Accept: 'application/json' },
    // Resolve fetch per call (not at creation) so test interceptors are picked up.
    fetch: (request: Request) => globalThis.fetch(request),
  })
  client.use(csrfMiddleware, errorMiddleware)
  return client
}

/**
 * Typed client for the Soundings REST API. Paths come from the generated
 * OpenAPI types, e.g.:
 *   const { data } = await api.GET('/api/v1/projects')
 * Requests are same-origin with the session cookie; errors throw ApiError.
 */
export const api = createApiClient<paths>()

/**
 * Returns `data` from an openapi-fetch result. Errors already throw via the
 * middleware; this only narrows the type (and guards 204s used as data).
 */
export async function unwrap<T>(request: Promise<{ data?: T; response: Response }>): Promise<T> {
  const { data } = await request
  return data as T
}
