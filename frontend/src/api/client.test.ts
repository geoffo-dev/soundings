import { http, HttpResponse } from 'msw'
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest'

import { createApiClient, CSRF_HEADER, readCookie } from '@/api/client'
import { ApiError } from '@/api/errors'
import { shouldRetry } from '@/api/query'
import { server } from '@/mocks/server'

// A tiny stand-in for the generated `paths` so the test doesn't depend on the contract.
interface TestPaths {
  '/api/v1/things/{id}': {
    parameters: { path: { id: string } }
    get: {
      parameters: { path: { id: string } }
      responses: { 200: { content: { 'application/json': { id: string } } } }
    }
    post: {
      parameters: { path: { id: string } }
      responses: { 200: { content: { 'application/json': { ok: boolean } } } }
    }
  }
}

const BASE = 'http://api.test'
const client = createApiClient<TestPaths>(BASE)
const url = `${BASE}/api/v1/things/:id`

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => {
  server.resetHandlers()
  document.cookie = 'soundings_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT'
})
afterAll(() => server.close())

describe('api client', () => {
  it('sends the CSRF cookie back as a header on unsafe methods only', async () => {
    document.cookie = 'soundings_csrf=tok%3D123'
    const seen: Record<string, string | null> = {}
    server.use(
      http.get(url, ({ request }) => {
        seen.get = request.headers.get(CSRF_HEADER)
        return HttpResponse.json({ id: '1' })
      }),
      http.post(url, ({ request }) => {
        seen.post = request.headers.get(CSRF_HEADER)
        return HttpResponse.json({ ok: true })
      }),
    )
    await client.GET('/api/v1/things/{id}', { params: { path: { id: '1' } } })
    const { data } = await client.POST('/api/v1/things/{id}', { params: { path: { id: '1' } } })
    expect(data).toEqual({ ok: true })
    expect(seen.get).toBeNull()
    expect(seen.post).toBe('tok=123')
  })

  it('turns problem+json responses into a typed ApiError', async () => {
    server.use(
      http.get(url, () =>
        HttpResponse.json(
          {
            type: 'about:blank',
            title: 'Idea not found',
            status: 404,
            detail: 'No idea CI-9',
            code: 'idea_not_found',
          },
          { status: 404, headers: { 'Content-Type': 'application/problem+json' } },
        ),
      ),
    )
    const request = client.GET('/api/v1/things/{id}', { params: { path: { id: '9' } } })
    await expect(request).rejects.toBeInstanceOf(ApiError)
    await expect(
      client.GET('/api/v1/things/{id}', { params: { path: { id: '9' } } }),
    ).rejects.toMatchObject({
      status: 404,
      code: 'idea_not_found',
      title: 'Idea not found',
      detail: 'No idea CI-9',
      isClientError: true,
    })
  })

  it('falls back to sensible titles for non-JSON errors and network failures', async () => {
    server.use(http.get(url, () => new HttpResponse('upstream exploded', { status: 502 })))
    await expect(
      client.GET('/api/v1/things/{id}', { params: { path: { id: '1' } } }),
    ).rejects.toMatchObject({
      status: 502,
      code: 'http_502',
    })

    server.use(http.get(url, () => HttpResponse.error()))
    await expect(
      client.GET('/api/v1/things/{id}', { params: { path: { id: '1' } } }),
    ).rejects.toMatchObject({
      status: 0,
      code: 'network_error',
      isNetworkError: true,
    })
  })

  it('reads cookies safely', () => {
    expect(readCookie('a', 'x=1; a=b%20c; y=2')).toBe('b c')
    expect(readCookie('missing', 'x=1')).toBeUndefined()
  })
})

describe('query retry policy', () => {
  it('never retries 4xx and retries other failures twice', () => {
    const notFound = new ApiError({ status: 404, code: 'not_found', title: 'Not found' })
    const unavailable = new ApiError({ status: 503, code: 'http_503', title: 'Unavailable' })
    expect(shouldRetry(0, notFound)).toBe(false)
    expect(shouldRetry(0, unavailable)).toBe(true)
    expect(shouldRetry(1, unavailable)).toBe(true)
    expect(shouldRetry(2, unavailable)).toBe(false)
  })
})
