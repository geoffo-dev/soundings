/**
 * Personal API keys and Admin settings → API keys (contract-phase5 §2, §3.1).
 *
 *   useMyApiKeys()               Settings → API keys: your keys + whether you may create one
 *   useCreateApiKey()            silent (the dialog shows errors inline); its `data.secret`
 *                                is the only copy of the key: call `reset()` when the
 *                                secret dialog closes, so it leaves the cache
 *   useRevokeApiKey()            your key (confirm first: no undo)
 *   useAdminApiKeys(filters)     every key that isn't revoked (infinite, newest first)
 *   useRevokeAdminApiKey()       any key (platform admins; confirm first)
 *   keySearchTerm(text)          a pasted whole key cut to its prefix (never sent whole)
 */
import {
  infiniteQueryOptions,
  keepPreviousData,
  queryOptions,
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
  type InfiniteData,
  type QueryClient,
} from '@tanstack/react-query'

import { api, unwrap } from '@/api/client'
import { queryKeys } from '@/api/keys'
import type { AdminApiKeyPage, ApiKeyCreate, ApiKeyList, ApiKeyState } from '@/api/types'

/** A whole Soundings key (`API_KEY_PATTERN`). */
export const API_KEY_PATTERN = /^sdg_[A-Za-z0-9]{12}_[A-Za-z0-9]{40}$/
const KEY_IN_TEXT = /sdg_([A-Za-z0-9]{12})_[A-Za-z0-9]{40}/

/**
 * What an admin search may send: a pasted whole key (alone, or inside other
 * text such as "Bearer sdg_…") becomes its prefix (`sdg_` + lookup id), so a
 * secret never goes into a URL, a log or the history (contract-phase5 §3.10).
 */
export function keySearchTerm(text: string): string {
  const match = KEY_IN_TEXT.exec(text)
  return match ? `sdg_${match[1] ?? ''}` : text
}

/** True when the text holds a whole key (the search says it used only the prefix). */
export function containsWholeKey(text: string): boolean {
  return KEY_IN_TEXT.test(text)
}

/* ------------------------------------------------------------------ */
/* Your keys                                                           */
/* ------------------------------------------------------------------ */

export const myApiKeysQueryOptions = () =>
  queryOptions({
    queryKey: queryKeys.apiKeys.mine(),
    queryFn: ({ signal }) => unwrap(api.GET('/api/v1/me/api-keys', { signal })),
  })

export function useMyApiKeys() {
  return useQuery(myApiKeysQueryOptions())
}

function invalidateKeys(queryClient: QueryClient) {
  void queryClient.invalidateQueries({ queryKey: queryKeys.apiKeys.all })
  void queryClient.invalidateQueries({ queryKey: queryKeys.admin.apiKeys() })
}

/**
 * Creates a key. The response's `secret` is shown once: the screen keeps it
 * only while the secret dialog is open and calls `reset()` afterwards. The key
 * (without the secret) goes into the list at once.
 */
export function useCreateApiKey() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: ApiKeyCreate) => unwrap(api.POST('/api/v1/me/api-keys', { body })),
    onSuccess: ({ key }) => {
      queryClient.setQueryData<ApiKeyList>(queryKeys.apiKeys.mine(), (list) =>
        list
          ? {
              ...list,
              items: [key, ...list.items.filter((item) => item.id !== key.id)],
              can_create: list.can_create && list.items.length + 1 < list.max_keys,
            }
          : list,
      )
      invalidateKeys(queryClient)
    },
    // Nothing keeps a finished create (and its secret) around once the dialog lets go.
    gcTime: 0,
    meta: { silent: true },
  })
}

/** Revokes one of your keys: it stops working at once (no undo). */
export function useRevokeApiKey() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (keyId: string) =>
      unwrap(api.DELETE('/api/v1/me/api-keys/{key_id}', { params: { path: { key_id: keyId } } })),
    onSuccess: (_data, keyId) => {
      queryClient.setQueryData<ApiKeyList>(queryKeys.apiKeys.mine(), (list) =>
        list
          ? {
              ...list,
              items: list.items.filter((item) => item.id !== keyId),
              can_create: list.can_create || list.items.length - 1 < list.max_keys,
            }
          : list,
      )
      invalidateKeys(queryClient)
    },
    meta: { errorTitle: 'Couldn’t revoke the key' },
  })
}

/* ------------------------------------------------------------------ */
/* Admin settings → API keys                                           */
/* ------------------------------------------------------------------ */

const PAGE_SIZE = 50

export interface AdminApiKeyFilters {
  /** Part of a key name, an owner's name or email, or a key's prefix or lookup id (exact). */
  q?: string
  user_id?: string
  state?: ApiKeyState
}

function adminKeyFilterKey({ q, user_id, state }: AdminApiKeyFilters) {
  return {
    q: keySearchTerm(q?.trim() ?? ''),
    user_id: user_id?.toLowerCase() ?? null,
    state: state ?? null,
  }
}

export const adminApiKeysInfiniteOptions = (filters: AdminApiKeyFilters = {}) => {
  const key = adminKeyFilterKey(filters)
  return infiniteQueryOptions({
    queryKey: queryKeys.admin.apiKeyList(key),
    queryFn: ({ pageParam, signal }) =>
      unwrap(
        api.GET('/api/v1/admin/api-keys', {
          params: {
            query: {
              q: key.q || undefined,
              user_id: key.user_id ?? undefined,
              state: key.state ?? undefined,
              cursor: pageParam ?? undefined,
              limit: PAGE_SIZE,
            },
          },
          signal,
        }),
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor,
    placeholderData: keepPreviousData,
  })
}

export function useAdminApiKeys(filters: AdminApiKeyFilters = {}) {
  return useInfiniteQuery(adminApiKeysInfiniteOptions(filters))
}

/** Revokes anyone's key (platform admins): it stops working at once (no undo). */
export function useRevokeAdminApiKey() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (keyId: string) =>
      unwrap(
        api.DELETE('/api/v1/admin/api-keys/{key_id}', { params: { path: { key_id: keyId } } }),
      ),
    onSuccess: (_data, keyId) => {
      // Gone from every loaded page at once; the refetch brings the totals.
      queryClient.setQueriesData<InfiniteData<AdminApiKeyPage>>(
        { queryKey: queryKeys.admin.apiKeys() },
        (data) =>
          data && {
            ...data,
            pages: data.pages.map((page) => {
              const items = page.items.filter((item) => item.id !== keyId)
              return { ...page, items, total: page.total - (page.items.length - items.length) }
            }),
          },
      )
      invalidateKeys(queryClient)
    },
    meta: { errorTitle: 'Couldn’t revoke the key' },
  })
}
