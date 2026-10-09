import { keepPreviousData, queryOptions, useQuery } from '@tanstack/react-query'

import { api, unwrap } from '@/api/client'
import { queryKeys } from '@/api/keys'

export interface UserSearchParams {
  /** Part of a name or email. */
  q?: string
  /** A project slug: only its members, with `project_role` filled in. */
  project?: string
  /**
   * Phase 8b (the researcher picker): with `project`, everyone active, members with
   * their `project_role` and everyone else with `null` ("Not in this project").
   */
  includeNonMembers?: boolean
  limit?: number
}

export const userSearchQueryOptions = ({
  q = '',
  project,
  includeNonMembers,
  limit = 20,
}: UserSearchParams) =>
  queryOptions({
    queryKey: queryKeys.users.search({ q: q.trim(), project, includeNonMembers }),
    queryFn: ({ signal }) =>
      unwrap(
        api.GET('/api/v1/users', {
          params: {
            query: {
              q: q.trim() || undefined,
              project,
              ...(includeNonMembers && project ? { include_non_members: true } : {}),
              limit,
            },
          },
          signal,
        }),
      ),
    staleTime: 60_000,
    placeholderData: keepPreviousData,
  })

/**
 * People pickers (owner, evaluators, members). Pass `project` to limit to its
 * members; only `project_role` member/admin can be owners or evaluators.
 */
export function useUserSearch(params: UserSearchParams, options: { enabled?: boolean } = {}) {
  return useQuery({ ...userSearchQueryOptions(params), enabled: options.enabled ?? true })
}
