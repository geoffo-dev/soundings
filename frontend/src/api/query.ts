import { CancelledError, MutationCache, QueryCache, QueryClient } from '@tanstack/react-query'

import { describeError, isApiError, type ApiError } from '@/api/errors'
import { toast } from '@/components/ui/toaster'

const MAX_RETRIES = 2

/** Don't retry what can't succeed: 4xx are the client's problem (auth, validation, not found). */
export function shouldRetry(failureCount: number, error: unknown): boolean {
  if (isApiError(error) && error.isClientError) return false
  return failureCount < MAX_RETRIES
}

declare module '@tanstack/react-query' {
  interface Register {
    mutationMeta: {
      /** Toast title when the mutation fails (default: from the error code). */
      errorTitle?: string
      /** The caller shows its own error UI (inline form errors): no toast. */
      silent?: boolean
    }
    queryMeta: {
      /** A 401 from this query is expected (the auth guard handles it). */
      allowUnauthorized?: boolean
    }
  }
}

type UnauthorizedHandler = (error: ApiError) => void
let unauthorizedHandler: UnauthorizedHandler | null = null

/**
 * The session ended (401 from any request): the auth feature registers a
 * handler that clears the cache and sends the user to /login?next=….
 */
export function setUnauthorizedHandler(handler: UnauthorizedHandler | null): void {
  unauthorizedHandler = handler
}

function isUnauthorized(error: unknown): error is ApiError {
  return isApiError(error) && error.status === 401
}

/**
 * For route loaders: a fetch awaited by a loader can be cancelled when the
 * last component observing that query unmounts (StrictMode, fast navigation).
 * Try once more instead of showing an error.
 */
export async function retryIfCancelled<T>(load: () => Promise<T>): Promise<T> {
  try {
    return await load()
  } catch (error) {
    if (error instanceof CancelledError) return load()
    throw error
  }
}

export function createQueryClient(): QueryClient {
  return new QueryClient({
    queryCache: new QueryCache({
      onError: (error, query) => {
        if (isUnauthorized(error) && !query.meta?.allowUnauthorized) unauthorizedHandler?.(error)
      },
    }),
    mutationCache: new MutationCache({
      onError: (error, _variables, _context, mutation) => {
        if (isUnauthorized(error)) {
          unauthorizedHandler?.(error)
          return
        }
        if (mutation.meta?.silent) return
        // Phase 8: the guarded request's own hook opens the research gate's dialog instead.
        if (isApiError(error) && error.code === 'research_incomplete') return
        const { title, description } = describeError(error)
        const errorTitle = mutation.meta?.errorTitle
        // "Couldn't change the status" · "This project is archived. Archived projects are read-only."
        toast.error(errorTitle ?? title, {
          description: errorTitle ? [title, description].filter(Boolean).join('. ') : description,
        })
      },
    }),
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
