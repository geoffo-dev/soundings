import { keepPreviousData, queryOptions, useQuery } from '@tanstack/react-query'

import { api, unwrap } from '@/api/client'
import { queryKeys } from '@/api/keys'

/**
 * The group picker (`search_groups`, contract-phase2 §3.7): any signed-in user,
 * groups whose name contains `q`, by name.
 */
export const groupSearchQueryOptions = (q = '', limit = 20) =>
  queryOptions({
    queryKey: queryKeys.groups.search(q),
    queryFn: ({ signal }) =>
      unwrap(
        api.GET('/api/v1/groups', {
          params: { query: { q: q.trim() || undefined, limit } },
          signal,
        }),
      ),
    staleTime: 60_000,
    placeholderData: keepPreviousData,
  })

export function useGroupSearch(q: string, options: { enabled?: boolean } = {}) {
  return useQuery({ ...groupSearchQueryOptions(q), enabled: options.enabled ?? true })
}
