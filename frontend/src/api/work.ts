import {
  infiniteQueryOptions,
  queryOptions,
  useInfiniteQuery,
  useQuery,
} from '@tanstack/react-query'

import { api, unwrap } from '@/api/client'
import { queryKeys } from '@/api/keys'
import type { IdeaStatus } from '@/api/types'

/** My work: evaluations due, owned ideas by status, recent activity, sidebar counts. */
export const myWorkQueryOptions = () =>
  queryOptions({
    queryKey: queryKeys.work.summary(),
    queryFn: ({ signal }) => unwrap(api.GET('/api/v1/me/work', { signal })),
    // The sidebar badge reads this too; keep it fresh without hammering.
    staleTime: 20_000,
    refetchInterval: 120_000,
  })

export function useMyWork() {
  return useQuery(myWorkQueryOptions())
}

/** Sidebar counts only (shares the My work request and cache). */
export function useWorkCounts() {
  return useQuery({ ...myWorkQueryOptions(), select: (work) => work.counts })
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
