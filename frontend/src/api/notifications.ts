import {
  infiniteQueryOptions,
  queryOptions,
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
  type InfiniteData,
  type QueryClient,
} from '@tanstack/react-query'
import { useCallback, useEffect, useRef } from 'react'

import { snapshot } from '@/api/cache'
import { api, unwrap } from '@/api/client'
import { queryKeys } from '@/api/keys'
import { deferUntilToastCloses, hideItem, unhideItem, useHiddenItems } from '@/api/undo'
import type {
  NotificationItem,
  NotificationMode,
  NotificationPage,
  NotificationPreferences,
  NotificationPreferencesUpdate,
  NotificationSummary,
} from '@/api/types'

/**
 * The in-app inbox, the bell's summary and email preferences
 * (contract-phase3 §2 "Inbox", "Email preferences", "Unsubscribe links").
 *
 * The summary is polled about once a minute while the tab is visible (and on
 * focus); the poll never keeps the session alive (§3.2), and a 401 from it is
 * handled like any other 401 (back to sign-in). Marking one read is optimistic;
 * "Mark all read" waits for its Undo toast (a deferred commit, api/undo).
 */

/** How often the bell asks for the unread count (ms). */
export const SUMMARY_POLL_MS = 60_000
const PAGE_SIZE = 30

type NotificationData = InfiniteData<NotificationPage, string | null>

/**
 * While "Mark all read" waits for its Undo toast, the inbox reads as all read
 * (through `select`, so a poll in the meantime can't bring the dots back and
 * Undo is exact: the cache itself is unchanged until the request is sent).
 */
const READ_ALL_PENDING = 'notifications:read-all'

export const notificationSummaryQueryOptions = () =>
  queryOptions({
    queryKey: queryKeys.notifications.summary(),
    queryFn: ({ signal }) => unwrap(api.GET('/api/v1/me/notifications/summary', { signal })),
    staleTime: 20_000,
    refetchInterval: SUMMARY_POLL_MS,
    // Only while the tab is visible: a hidden tab neither polls nor counts as activity.
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: true,
  })

/**
 * The bell's badge and the email banners. When the unread count goes up (new
 * notifications), the cached inbox pages are refreshed (the open one at once,
 * others on next view). Not when it goes down: that is usually this tab marking
 * something read, and a refetch could race the optimistic update.
 */
export function useNotificationSummary(options: { enabled?: boolean } = {}) {
  const queryClient = useQueryClient()
  const readAllPending = useHiddenItems().has(READ_ALL_PENDING)
  const select = useCallback(
    (summary: NotificationSummary) => (readAllPending ? { ...summary, unread_count: 0 } : summary),
    [readAllPending],
  )
  const query = useQuery({
    ...notificationSummaryQueryOptions(),
    enabled: options.enabled ?? true,
    select,
  })
  const count = query.data?.unread_count
  const previous = useRef(count)
  useEffect(() => {
    if (count === undefined) return
    if (previous.current !== undefined && count > previous.current) {
      void queryClient.invalidateQueries({ queryKey: queryKeys.notifications.lists() })
    }
    previous.current = count
  }, [count, queryClient])
  return query
}

export const notificationsInfiniteOptions = (
  params: { unread?: boolean } = {},
  limit = PAGE_SIZE,
) =>
  infiniteQueryOptions({
    queryKey: queryKeys.notifications.list(params),
    queryFn: ({ pageParam, signal }) =>
      unwrap(
        api.GET('/api/v1/me/notifications', {
          params: {
            query: {
              unread: params.unread ? true : undefined,
              cursor: pageParam ?? undefined,
              limit,
            },
          },
          signal,
        }),
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor,
    staleTime: 15_000,
  })

/**
 * The inbox, newest first (`unread: true` for unread only: what has been read
 * since it loaded drops out at once, so "Mark all read" leaves it empty).
 */
export function useNotifications(
  params: { unread?: boolean } = {},
  options: { enabled?: boolean } = {},
) {
  const readAllPending = useHiddenItems().has(READ_ALL_PENDING)
  const unreadOnly = Boolean(params.unread)
  const select = useCallback(
    (data: NotificationData) => {
      const items = data.pages
        .flatMap((page) => page.items)
        .map((item) =>
          readAllPending && item.read_at === null ? { ...item, read_at: item.created_at } : item,
        )
      return {
        ...data,
        items: unreadOnly ? items.filter((item) => item.read_at === null) : items,
      }
    },
    [readAllPending, unreadOnly],
  )
  return useInfiniteQuery({
    ...notificationsInfiniteOptions(params),
    enabled: options.enabled ?? true,
    select,
  })
}

/** Sets `read_at` on the cached inbox items that `match`. */
function markCachedRead(
  queryClient: QueryClient,
  match: (item: NotificationItem) => boolean,
  readAt = new Date().toISOString(),
): number {
  let changed = 0
  const seen = new Set<string>()
  queryClient.setQueriesData<NotificationData>(
    { queryKey: queryKeys.notifications.lists() },
    (data) =>
      data && {
        ...data,
        pages: data.pages.map((page) => ({
          ...page,
          items: page.items.map((item) => {
            if (item.read_at !== null || !match(item)) return item
            if (!seen.has(item.id)) {
              seen.add(item.id)
              changed += 1
            }
            return { ...item, read_at: readAt }
          }),
        })),
      },
  )
  return changed
}

function patchSummary(
  queryClient: QueryClient,
  patch: (summary: NotificationSummary) => NotificationSummary,
) {
  queryClient.setQueryData<NotificationSummary>(
    queryKeys.notifications.summary(),
    (summary) => summary && patch(summary),
  )
}

/** Mark one notification read (optimistic; idempotent on the server). */
export function useMarkNotificationRead() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (notificationId: string) =>
      api.POST('/api/v1/me/notifications/{notification_id}/read', {
        params: { path: { notification_id: notificationId } },
      }),
    onMutate: async (notificationId) => {
      const rollback = await snapshot(queryClient, [queryKeys.notifications.all])
      const changed = markCachedRead(queryClient, (item) => item.id === notificationId)
      if (changed > 0) {
        patchSummary(queryClient, (summary) => ({
          ...summary,
          unread_count: Math.max(0, summary.unread_count - 1),
        }))
      }
      return { rollback }
    },
    onError: (_error, _id, context) => context?.rollback(),
    onSettled: () =>
      void queryClient.invalidateQueries({ queryKey: queryKeys.notifications.summary() }),
    // Opening the item matters more than the dot: never interrupt with a toast.
    meta: { silent: true },
  })
}

/**
 * "Mark all read" with Undo (SPEC §5): the inbox reads as all read at once,
 * and the request is sent when the Undo toast closes (or the page is hidden);
 * Undo puts every dot back. There's no "mark unread", so this is a deferred
 * commit (api/undo), not an inverse call. Call it with the unread count (for
 * the toast).
 */
export function useMarkAllNotificationsRead() {
  const queryClient = useQueryClient()
  return useCallback(
    (unreadCount: number) =>
      deferUntilToastCloses({
        title:
          unreadCount === 1
            ? '1 notification marked read'
            : `${unreadCount > 99 ? 'All' : unreadCount.toLocaleString()} notifications marked read`,
        hide: () => hideItem(READ_ALL_PENDING),
        restore: () => unhideItem(READ_ALL_PENDING),
        commit: async ({ keepalive }) => {
          const summary = await unwrap(api.POST('/api/v1/me/notifications/read-all', { keepalive }))
          markCachedRead(queryClient, () => true)
          queryClient.setQueryData(queryKeys.notifications.summary(), summary)
          unhideItem(READ_ALL_PENDING)
          void queryClient.invalidateQueries({ queryKey: queryKeys.notifications.lists() })
        },
        errorTitle: 'Couldn’t mark your notifications read',
      }),
    [queryClient],
  )
}

/**
 * Visiting an idea reads its news (contract-phase3 §3.2): when the idea page
 * opens and something is unread, mark that idea's notifications read. Quiet:
 * no toast, no retry.
 */
export function useMarkIdeaNotificationsRead(ideaKey: string, ideaId: string | undefined) {
  const queryClient = useQueryClient()
  const summary = useQuery({ ...notificationSummaryQueryOptions(), enabled: false })
  const unread = summary.data?.unread_count ?? 0
  const done = useRef<string | null>(null)
  const mutation = useMutation({
    mutationFn: (idea: string) =>
      unwrap(api.POST('/api/v1/me/notifications/read-all', { params: { query: { idea } } })),
    onSuccess: (next, idea) => {
      markCachedRead(
        queryClient,
        (item) => item.idea.key.toUpperCase() === idea.toUpperCase() || item.idea.id === ideaId,
      )
      queryClient.setQueryData(queryKeys.notifications.summary(), next)
    },
    meta: { silent: true },
  })
  const { mutate } = mutation
  useEffect(() => {
    if (!ideaId || unread === 0 || done.current === ideaKey) return
    done.current = ideaKey
    mutate(ideaKey)
  }, [ideaId, ideaKey, unread, mutate])
}

/* ------------------------------------------------------------------ */
/* Email preferences                                                   */
/* ------------------------------------------------------------------ */

export const notificationPreferencesQueryOptions = () =>
  queryOptions({
    queryKey: queryKeys.notifications.preferences(),
    queryFn: ({ signal }) => unwrap(api.GET('/api/v1/me/notification-preferences', { signal })),
  })

export function useNotificationPreferences() {
  return useQuery(notificationPreferencesQueryOptions())
}

/** Applies `update` to cached preferences (optimistic saves and their undo). */
export function applyPreferenceUpdate(
  preferences: NotificationPreferences,
  update: NotificationPreferencesUpdate,
): NotificationPreferences {
  return {
    ...preferences,
    items: preferences.items.map((item) => {
      const mode = update[item.type]
      return mode ? { ...item, mode } : item
    }),
  }
}

/** Save some types' email modes (optimistic; rolled back with a toast on error). */
export function useUpdateNotificationPreferences() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (update: NotificationPreferencesUpdate) =>
      unwrap(api.PATCH('/api/v1/me/notification-preferences', { body: update })),
    onMutate: async (update) => {
      const rollback = await snapshot(queryClient, [queryKeys.notifications.preferences()])
      queryClient.setQueryData<NotificationPreferences>(
        queryKeys.notifications.preferences(),
        (current) => current && applyPreferenceUpdate(current, update),
      )
      return { rollback }
    },
    onError: (_error, _update, context) => context?.rollback(),
    onSuccess: (saved) => queryClient.setQueryData(queryKeys.notifications.preferences(), saved),
    meta: { errorTitle: 'Couldn’t save your email preferences' },
  })
}

/** Every type set to `mode` (e.g. "Turn off all email"). */
export function allTypes(
  preferences: NotificationPreferences,
  mode: NotificationMode,
): NotificationPreferencesUpdate {
  const out: NotificationPreferencesUpdate = {}
  for (const item of preferences.items) out[item.type] = mode
  return out
}

/* ------------------------------------------------------------------ */
/* Unsubscribe links (public: no session, no CSRF)                     */
/* ------------------------------------------------------------------ */

export const unsubscribeQueryOptions = (token: string) =>
  queryOptions({
    queryKey: queryKeys.notifications.unsubscribe(token),
    // The client sends `Accept: application/json`, so the API answers JSON
    // (a browser navigation to the API URL gets a 303 to this page instead).
    queryFn: ({ signal }) =>
      unwrap(api.GET('/api/v1/unsubscribe', { params: { query: { token } }, signal })),
    staleTime: Infinity,
    meta: { allowUnauthorized: true },
  })

/** What an unsubscribe link turns off (changes nothing: link scanners prefetch). */
export function useUnsubscribeInfo(token: string | undefined) {
  return useQuery({ ...unsubscribeQueryOptions(token ?? ''), enabled: Boolean(token) })
}

/**
 * Confirm: turns the link's types off. Only a link scoped to `all` (the
 * email footer's "Unsubscribe from all email") turns off every type; the API
 * refuses `all=true` for the others (403), so the page never sends it.
 * Errors are shown inline.
 */
export function useConfirmUnsubscribe(token: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => unwrap(api.POST('/api/v1/unsubscribe', { params: { query: { token } } })),
    onSuccess: (info) => {
      queryClient.setQueryData(queryKeys.notifications.unsubscribe(token), info)
      // A signed-in tab's preferences are out of date now.
      void queryClient.invalidateQueries({ queryKey: queryKeys.notifications.preferences() })
    },
    meta: { silent: true },
  })
}
