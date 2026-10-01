import { QueryClientProvider, type QueryClient } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import { delay, http } from 'msw'
import type { ReactNode } from 'react'
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import { queryKeys } from '@/api/keys'
import {
  useMarkAllNotificationsRead,
  useMarkNotificationRead,
  useNotificationPreferences,
  useNotifications,
  useNotificationSummary,
  useUpdateNotificationPreferences,
} from '@/api/notifications'
import { createQueryClient } from '@/api/query'
import type { NotificationPreferences, NotificationSummary } from '@/api/types'
import { resetDb, USERS } from '@/mocks/db'
import { problemResponse } from '@/mocks/http'
import { server } from '@/mocks/server'
import { endSession } from '@/mocks/session'

const toasts = vi.hoisted(() => ({ errors: [] as string[] }))
vi.mock('@/components/ui/toaster', () => ({
  toast: {
    error: (title: string) => toasts.errors.push(title),
    success: () => undefined,
    info: () => undefined,
    message: () => undefined,
  },
  toastUndo: () => undefined,
}))

let queryClient: QueryClient

function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
}

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
beforeEach(async () => {
  resetDb()
  localStorage.setItem('soundings-mock-latency', 'none')
  toasts.errors.length = 0
  queryClient = createQueryClient()
  await api.POST('/api/v1/auth/dev/login', { body: { user_id: USERS.alice } })
})
afterEach(() => {
  server.resetHandlers()
  endSession()
})
afterAll(() => server.close())

const summary = () =>
  queryClient.getQueryData<NotificationSummary>(queryKeys.notifications.summary())

describe('the inbox hooks', () => {
  it('mark one read at once (count and dot), before the server answers', async () => {
    const { result } = renderHook(
      () => ({
        summary: useNotificationSummary(),
        list: useNotifications(),
        markRead: useMarkNotificationRead(),
      }),
      { wrapper },
    )
    await waitFor(() => expect(result.current.list.data).toBeDefined())
    await waitFor(() => expect(result.current.summary.data?.unread_count).toBe(5))
    const first = result.current.list.data?.items.find((item) => item.read_at === null)
    server.use(
      http.post('*/api/v1/me/notifications/:id/read', async () => {
        await delay(200)
        return new Response(null, { status: 204 })
      }),
    )
    act(() => result.current.markRead.mutate(first?.id ?? ''))
    await waitFor(() => expect(summary()?.unread_count).toBe(4))
    expect(
      result.current.list.data?.items.find((item) => item.id === first?.id)?.read_at,
    ).not.toBeNull()
  })

  it('mark all read, and roll back with a toast when it fails', async () => {
    const { result } = renderHook(
      () => ({
        summary: useNotificationSummary(),
        list: useNotifications(),
        markAll: useMarkAllNotificationsRead(),
      }),
      { wrapper },
    )
    await waitFor(() => expect(result.current.summary.data?.unread_count).toBe(5))
    await waitFor(() => expect(result.current.list.data).toBeDefined())
    server.use(
      http.post('*/api/v1/me/notifications/read-all', () => problemResponse(500, 'internal_error')),
    )
    act(() => result.current.markAll.mutate())
    await waitFor(() => expect(result.current.markAll.isError).toBe(true))
    expect(summary()?.unread_count).toBe(5)
    expect(toasts.errors).toEqual(['Couldn’t mark your notifications read'])

    server.resetHandlers()
    act(() => result.current.markAll.mutate())
    await waitFor(() => expect(result.current.markAll.isSuccess).toBe(true))
    expect(summary()?.unread_count).toBe(0)
    expect(result.current.list.data?.items.every((item) => item.read_at !== null)).toBe(true)
  })
})

describe('email preferences', () => {
  it('save optimistically and roll back on error', async () => {
    const { result } = renderHook(
      () => ({ prefs: useNotificationPreferences(), update: useUpdateNotificationPreferences() }),
      { wrapper },
    )
    await waitFor(() => expect(result.current.prefs.data).toBeDefined())
    const mode = () =>
      queryClient
        .getQueryData<NotificationPreferences>(queryKeys.notifications.preferences())
        ?.items.find((item) => item.type === 'mention')?.mode
    server.use(
      http.patch('*/api/v1/me/notification-preferences', async () => {
        await delay(100)
        return problemResponse(500, 'internal_error')
      }),
    )
    act(() => result.current.update.mutate({ mention: 'off' }))
    await waitFor(() => expect(mode()).toBe('off'))
    await waitFor(() => expect(result.current.update.isError).toBe(true))
    expect(mode()).toBe('immediate')
    expect(toasts.errors).toEqual(['Couldn’t save your email preferences'])
  })
})
