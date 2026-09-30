import { QueryClient } from '@tanstack/react-query'

import { isApiError } from '@/api/errors'

const MAX_RETRIES = 2

/** Don't retry what can't succeed: 4xx are the client's problem (auth, validation, not found). */
export function shouldRetry(failureCount: number, error: unknown): boolean {
  if (isApiError(error) && error.isClientError) return false
  return failureCount < MAX_RETRIES
}

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        gcTime: 5 * 60_000,
        retry: shouldRetry,
        // Refetch stale data when the tab regains focus — keeps lists fresh
        // without polling; staleTime stops it hammering the API.
        refetchOnWindowFocus: true,
        refetchOnReconnect: true,
      },
      mutations: {
        retry: false,
      },
    },
  })
}
