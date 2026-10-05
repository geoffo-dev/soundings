import { QueryClientProvider, type QueryClient } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  containsWholeKey,
  keySearchTerm,
  useAdminApiKeys,
  useCreateApiKey,
  useMyApiKeys,
  useRevokeAdminApiKey,
  useRevokeApiKey,
} from '@/api/api-keys'
import { api } from '@/api/client'
import { createQueryClient } from '@/api/query'
import { resetDb, USERS } from '@/mocks/db'
import { API_KEYS } from '@/mocks/phase5-fixtures'
import { server } from '@/mocks/server'

vi.mock('@/components/ui/toaster', () => ({
  toast: { error: () => undefined, success: () => undefined, info: () => undefined },
  toastUndo: () => undefined,
}))

let queryClient: QueryClient

function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
}

const signIn = (userId: string) => api.POST('/api/v1/auth/dev/login', { body: { user_id: userId } })

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
beforeEach(() => {
  resetDb()
  localStorage.setItem('soundings-mock-latency', 'none')
  queryClient = createQueryClient()
})
afterEach(() => {
  server.resetHandlers()
  queryClient.clear()
})
afterAll(() => server.close())

const WHOLE_KEY = `sdg_Ab12Cd34Ef56_${'Z9'.repeat(20)}`

describe('keySearchTerm', () => {
  it('cuts a pasted whole key to its prefix, wherever it is in the text', () => {
    expect(keySearchTerm(WHOLE_KEY)).toBe('sdg_Ab12Cd34Ef56')
    expect(keySearchTerm(`Authorization: Bearer ${WHOLE_KEY}`)).toBe('sdg_Ab12Cd34Ef56')
    expect(containsWholeKey(`Bearer ${WHOLE_KEY}`)).toBe(true)
    expect(keySearchTerm('sdg_Ab12Cd34Ef56')).toBe('sdg_Ab12Cd34Ef56')
    expect(keySearchTerm('claude')).toBe('claude')
  })
})

describe('your keys', () => {
  it('creates a key: the secret only in the mutation, gone after reset()', async () => {
    await signIn(USERS.alice)
    const { result } = renderHook(() => ({ list: useMyApiKeys(), create: useCreateApiKey() }), {
      wrapper,
    })
    await waitFor(() => expect(result.current.list.data?.items).toHaveLength(3))
    act(() => result.current.create.mutate({ name: 'Claude Code', scopes: ['evaluate', 'mcp'] }))
    await waitFor(() => expect(result.current.create.isSuccess).toBe(true))
    const secret = result.current.create.data?.secret ?? ''
    expect(secret).toMatch(/^sdg_[A-Za-z0-9]{12}_[A-Za-z0-9]{40}$/)
    expect(result.current.list.data?.items[0]).toMatchObject({
      name: 'Claude Code',
      scopes: ['read', 'evaluate', 'mcp'],
    })

    act(() => result.current.create.reset())
    await waitFor(() => expect(result.current.create.data).toBeUndefined())
    // No query or mutation the client holds still carries the secret.
    const cached = JSON.stringify([
      queryClient
        .getQueryCache()
        .getAll()
        .map((query) => query.state.data),
      queryClient
        .getMutationCache()
        .getAll()
        .map((mutation) => mutation.state.data),
    ])
    expect(cached).not.toContain(secret)
  })

  it('reports name clashes for the form (silent: no toast)', async () => {
    await signIn(USERS.alice)
    const { result } = renderHook(() => useCreateApiKey(), { wrapper })
    act(() => result.current.mutate({ name: 'claude desktop', scopes: ['read'] }))
    await waitFor(() => expect(result.current.isError).toBe(true))
    expect(result.current.error).toMatchObject({ status: 409, code: 'api_key_name_taken' })
  })

  it('revokes: the key leaves the list at once', async () => {
    await signIn(USERS.alice)
    const { result } = renderHook(() => ({ list: useMyApiKeys(), revoke: useRevokeApiKey() }), {
      wrapper,
    })
    await waitFor(() => expect(result.current.list.data?.items).toHaveLength(3))
    act(() => result.current.revoke.mutate(API_KEYS.claudeDesktop))
    await waitFor(() => expect(result.current.list.data?.items).toHaveLength(2))
    expect(result.current.list.data?.items.map((key) => key.name)).not.toContain('Claude Desktop')
  })
})

describe('admin keys', () => {
  it('never sends a whole key: the search goes out as the prefix', async () => {
    await signIn(USERS.priya)
    const urls: string[] = []
    server.events.on('request:start', ({ request }) => {
      urls.push(request.url)
    })
    const { result } = renderHook(
      () => useAdminApiKeys({ q: `sdg_J1r4SyncB0b2_${'a'.repeat(40)}` }),
      { wrapper },
    )
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data?.pages[0]?.items.map((key) => key.name)).toEqual(['Jira sync'])
    expect(urls.some((url) => url.includes('a'.repeat(40)))).toBe(false)
    server.events.removeAllListeners()
  })

  it('revokes anyone’s key and drops it from every loaded page', async () => {
    await signIn(USERS.priya)
    const { result } = renderHook(
      () => ({ list: useAdminApiKeys(), revoke: useRevokeAdminApiKey() }),
      { wrapper },
    )
    await waitFor(() => expect(result.current.list.data?.pages[0]?.total).toBe(7))
    act(() => result.current.revoke.mutate(API_KEYS.agent))
    await waitFor(() => expect(result.current.list.data?.pages[0]?.total).toBe(6))
    expect(
      result.current.list.data?.pages.flatMap((page) => page.items).map((key) => key.id),
    ).not.toContain(API_KEYS.agent)
  })
})
