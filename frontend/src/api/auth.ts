import { queryOptions, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, unwrap } from '@/api/client'
import { queryKeys } from '@/api/keys'
import type { CurrentUser } from '@/api/types'
import { flushPendingCommits } from '@/api/undo'
import { clearDrafts } from '@/lib/drafts'

/** The signed-in user. A 401 means "signed out" (the auth guard redirects). */
export const meQueryOptions = () =>
  queryOptions({
    queryKey: queryKeys.auth.me(),
    // No abort signal: the auth guard awaits this request, and an observer
    // unmounting meanwhile (StrictMode, navigation) must not cancel it.
    queryFn: () => unwrap(api.GET('/api/v1/auth/me')),
    staleTime: 5 * 60_000,
    meta: { allowUnauthorized: true },
  })

export function useMe() {
  return useQuery(meQueryOptions())
}

/** Users for the dev login picker (404 when dev login is disabled). */
export const devUsersQueryOptions = () =>
  queryOptions({
    queryKey: queryKeys.auth.devUsers(),
    queryFn: ({ signal }) => unwrap(api.GET('/api/v1/auth/dev/users', { signal })),
    staleTime: 60_000,
    retry: false,
  })

export function useDevUsers(options: { enabled?: boolean } = {}) {
  return useQuery({ ...devUsersQueryOptions(), enabled: options.enabled ?? true })
}

/**
 * Signs in as a user (dev login). Everything cached belongs to the previous
 * user, so the cache is cleared before the new user is stored.
 */
export function useDevLogin() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (userId: string) =>
      unwrap(api.POST('/api/v1/auth/dev/login', { body: { user_id: userId } })),
    onSuccess: (user: CurrentUser) => {
      queryClient.clear()
      clearDrafts()
      queryClient.setQueryData(queryKeys.auth.me(), user)
    },
    meta: { errorTitle: 'Couldn’t sign in' },
  })
}

/**
 * Signs out: sends pending deferred deletes first, then clears every cached query
 * and every unsent draft (lib/drafts).
 */
export function useLogout() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async () => {
      await flushPendingCommits({ keepalive: false })
      await api.POST('/api/v1/auth/logout')
    },
    onSettled: () => {
      queryClient.clear()
      clearDrafts()
    },
    meta: { silent: true },
  })
}
