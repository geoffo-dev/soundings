import {
  infiniteQueryOptions,
  queryOptions,
  useInfiniteQuery,
  useQuery,
} from '@tanstack/react-query'

import { api, unwrap } from '@/api/client'
import { queryKeys } from '@/api/keys'
import type { IdeaStatus } from '@/api/types'

/**
 * My work: the first 50 evaluations due (`evaluations_due_next_cursor` pages on),
 * owned ideas by status, recent activity and the counts.
 */
export const myWorkQueryOptions = () =>
  queryOptions({
    queryKey: queryKeys.work.summary(),
    queryFn: ({ signal }) => unwrap(api.GET('/api/v1/me/work', { signal })),
    staleTime: 20_000,
    refetchInterval: 120_000,
  })

export function useMyWork() {
  return useQuery(myWorkQueryOptions())
}

/**
 * The sidebar's badges: `GET /me/work/counts` runs only the counts, so every page
 * load doesn't fetch the whole of My work (contract-phase7 C1).
 */
export const workCountsQueryOptions = () =>
  queryOptions({
    queryKey: queryKeys.work.counts(),
    queryFn: ({ signal }) => unwrap(api.GET('/api/v1/me/work/counts', { signal })),
    staleTime: 20_000,
    refetchInterval: 120_000,
  })

export function useWorkCounts() {
  return useQuery(workCountsQueryOptions())
}

/** My work's "Show more" for evaluations due, from `evaluations_due_next_cursor`. */
export const evaluationsDueInfiniteOptions = (initialCursor: string | null, pageSize = 100) =>
  infiniteQueryOptions({
    queryKey: [...queryKeys.work.due(), { from: initialCursor, pageSize }] as const,
    queryFn: ({ pageParam, signal }) =>
      unwrap(
        api.GET('/api/v1/me/evaluations-due', {
          params: { query: { cursor: pageParam ?? undefined, limit: pageSize } },
          signal,
        }),
      ),
    initialPageParam: initialCursor,
    getNextPageParam: (page) => page.next_cursor,
  })

export function useMoreEvaluationsDue(initialCursor: string | null, enabled: boolean) {
  return useInfiniteQuery({ ...evaluationsDueInfiniteOptions(initialCursor), enabled })
}

/**
 * "Load more" for one My work group: ideas you own in `status`, starting from
 * the group's `next_cursor`.
 */
export const ownedIdeasInfiniteOptions = (
  status: IdeaStatus,
  initialCursor: string | null,
  pageSize = 50,
) =>
  infiniteQueryOptions({
    queryKey: [...queryKeys.work.owned(status), { from: initialCursor, pageSize }] as const,
    queryFn: ({ pageParam, signal }) =>
      unwrap(
        api.GET('/api/v1/me/owned-ideas', {
          params: { query: { status: [status], cursor: pageParam ?? undefined, limit: pageSize } },
          signal,
        }),
      ),
    initialPageParam: initialCursor,
    getNextPageParam: (page) => page.next_cursor,
  })

export function useOwnedIdeas(
  status: IdeaStatus,
  initialCursor: string | null,
  options: { enabled?: boolean; pageSize?: number } = {},
) {
  return useInfiniteQuery({
    ...ownedIdeasInfiniteOptions(status, initialCursor, options.pageSize),
    enabled: options.enabled ?? true,
  })
}
