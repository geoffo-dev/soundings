import { act, renderHook, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

import type { AltchaChallenge } from '@/api/types'
import { resetDb } from '@/mocks/db'
import { server } from '@/mocks/server'

import { useAltcha } from './use-altcha'

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
beforeEach(() => {
  resetDb()
  localStorage.setItem('soundings-mock-latency', 'none')
})
afterEach(() => server.resetHandlers())
afterAll(() => server.close())

let count = 0
const solver = vi.fn((challenge: AltchaChallenge) => {
  count += 1
  return Promise.resolve(`payload-${count}-${challenge.parameters.nonce}`)
})

beforeEach(() => {
  count = 0
  solver.mockClear()
})

describe('useAltcha', () => {
  it('solves once on the first input, and hands that payload to the submit', async () => {
    const { result } = renderHook(() => useAltcha('customer-innovation', solver))
    expect(result.current.state).toBe('idle')
    act(() => {
      result.current.start()
      result.current.start()
    })
    await waitFor(() => expect(result.current.state).toBe('verified'))
    expect(solver).toHaveBeenCalledTimes(1)
    const payload = await result.current.getPayload()
    expect(payload).toMatch(/^payload-1-/)
    expect(solver).toHaveBeenCalledTimes(1)
  })

  it('never reuses a payload once sent', async () => {
    const { result } = renderHook(() => useAltcha('customer-innovation', solver))
    const first = await act(() => result.current.getPayload())
    act(() => result.current.discard())
    const second = await act(() => result.current.getPayload())
    expect(second).not.toBe(first)
    expect(solver).toHaveBeenCalledTimes(2)
  })

  it('solves again when the challenge is about to expire', async () => {
    server.use(
      http.get('*/api/v1/public/projects/:slug/altcha', () =>
        HttpResponse.json({
          parameters: {
            algorithm: 'PBKDF2/SHA-256',
            cost: 1000,
            keyLength: 32,
            keyPrefix: '00',
            nonce: `n${Math.random()}`,
            salt: 's',
            // 30 seconds left: inside the refresh margin.
            expiresAt: Math.floor(Date.now() / 1000) + 30,
            data: { project: 'customer-innovation' },
          },
          signature: 'sig',
        }),
      ),
    )
    const { result } = renderHook(() => useAltcha('customer-innovation', solver))
    await act(() => result.current.getPayload())
    await act(() => result.current.getPayload())
    expect(solver).toHaveBeenCalledTimes(2)
  })

  it('reports a failure (a form that is gone, or no solution) and can retry', async () => {
    const failing = vi.fn(() => Promise.resolve(null))
    const { result } = renderHook(() => useAltcha('customer-innovation', failing))
    expect(await act(() => result.current.getPayload())).toBeNull()
    expect(result.current.state).toBe('error')
    const { result: missing } = renderHook(() => useAltcha('no-such-project', solver))
    expect(await act(() => missing.current.getPayload())).toBeNull()
    expect(missing.current.state).toBe('error')
    expect(solver).not.toHaveBeenCalled()
  })
})
