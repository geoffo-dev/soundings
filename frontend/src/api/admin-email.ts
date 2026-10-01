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

import { snapshot } from '@/api/cache'
import { api, unwrap } from '@/api/client'
import { queryKeys } from '@/api/keys'
import type { EmailStatus, EmailType, OutboxEmail, OutboxEmailPage } from '@/api/types'
import { toast } from '@/components/ui/toaster'

/**
 * Admin settings → Email (contract-phase3 §3.10): the effective SMTP settings
 * (read-only), the test email and the outbox with retry. Platform admins only,
 * sessions only.
 */

const PAGE_SIZE = 25

export interface OutboxFilters {
  status?: EmailStatus[]
  type?: EmailType[]
}

function filterKey({ status, type }: OutboxFilters) {
  return { status: [...(status ?? [])].sort(), type: [...(type ?? [])].sort() }
}

type OutboxData = InfiniteData<OutboxEmailPage, string | null>

export const emailConfigQueryOptions = () =>
  queryOptions({
    queryKey: queryKeys.admin.emailConfig(),
    queryFn: ({ signal }) => unwrap(api.GET('/api/v1/admin/email', { signal })),
  })

/** The settings in effect, credentials as "set" flags, and the outbox counters. */
export function useEmailConfig() {
  return useQuery(emailConfigQueryOptions())
}

export const outboxInfiniteOptions = (filters: OutboxFilters = {}, limit = PAGE_SIZE) =>
  infiniteQueryOptions({
    queryKey: [...queryKeys.admin.outbox(filterKey(filters)), { limit }] as const,
    queryFn: ({ pageParam, signal }) =>
      unwrap(
        api.GET('/api/v1/admin/email/outbox', {
          params: {
            query: {
              status: filters.status?.length ? filters.status : undefined,
              type: filters.type?.length ? filters.type : undefined,
              cursor: pageParam ?? undefined,
              limit,
            },
          },
          signal,
        }),
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor,
    placeholderData: keepPreviousData,
  })

/** The outbox, newest first; `status` and `type` are OR-ed within themselves. */
export function useOutboxEmails(filters: OutboxFilters = {}, options: { enabled?: boolean } = {}) {
  return useInfiniteQuery({
    ...outboxInfiniteOptions(filters),
    enabled: options.enabled ?? true,
    select: (data) => ({ ...data, items: data.pages.flatMap((page) => page.items) }),
  })
}

/** How often the test email's row is checked, and for how long (contract §3.10). */
export const TEST_POLL_MS = 2_000
export const TEST_POLL_LIMIT_MS = 30_000

/** One outbox email; `poll` re-reads it every 2 s while it is queued or sending. */
export function useOutboxEmail(emailId: string | undefined, options: { poll?: boolean } = {}) {
  return useQuery({
    queryKey: queryKeys.admin.outboxEmail(emailId ?? ''),
    queryFn: ({ signal }) =>
      unwrap(
        api.GET('/api/v1/admin/email/outbox/{email_id}', {
          params: { path: { email_id: emailId ?? '' } },
          signal,
        }),
      ),
    enabled: Boolean(emailId),
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return options.poll && (status === undefined || status === 'queued' || status === 'sending')
        ? TEST_POLL_MS
        : false
    },
  })
}

function refreshEmail(queryClient: QueryClient) {
  void queryClient.invalidateQueries({ queryKey: queryKeys.admin.email() })
  // The admin's "email failing" banner may clear.
  void queryClient.invalidateQueries({ queryKey: queryKeys.notifications.summary() })
}

/**
 * Queue a test email (to `to`, or yourself). Errors are shown inline: 409
 * smtp_not_configured, 422 on `to`, 429 too_many_attempts with Retry-After.
 */
export function useSendTestEmail() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (to: string | null) =>
      unwrap(api.POST('/api/v1/admin/email/test', { body: { to } })),
    onSuccess: (email) => {
      queryClient.setQueryData(queryKeys.admin.outboxEmail(email.id), email)
      refreshEmail(queryClient)
    },
    meta: { silent: true },
  })
}

function patchOutboxEmail(
  queryClient: QueryClient,
  emailId: string,
  patch: (email: OutboxEmail) => OutboxEmail,
) {
  queryClient.setQueriesData<OutboxData>({ queryKey: queryKeys.admin.outboxes() }, (data) => {
    if (!data?.pages) return data
    return {
      ...data,
      pages: data.pages.map((page) => ({
        ...page,
        items: page.items.map((item) => (item.id === emailId ? patch(item) : item)),
      })),
    }
  })
}

/** Retry one failed email: the row shows "Queued" at once (rolled back on error). */
export function useRetryOutboxEmail() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (emailId: string) =>
      unwrap(
        api.POST('/api/v1/admin/email/outbox/{email_id}/retry', {
          params: { path: { email_id: emailId } },
        }),
      ),
    onMutate: async (emailId) => {
      const rollback = await snapshot(queryClient, [queryKeys.admin.outboxes()])
      patchOutboxEmail(queryClient, emailId, (email) => ({
        ...email,
        status: 'queued',
        attempts: 0,
        last_error: null,
        retryable: false,
        next_attempt_at: new Date().toISOString(),
      }))
      return { rollback }
    },
    onError: (_error, _id, context) => context?.rollback(),
    onSuccess: (saved) => patchOutboxEmail(queryClient, saved.id, () => saved),
    // The counters and the banner change; the list keeps the row (now "Queued") in place
    // rather than dropping it from the "Failed" view under the admin's cursor.
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.admin.emailConfig() })
      void queryClient.invalidateQueries({ queryKey: queryKeys.notifications.summary() })
    },
    meta: { errorTitle: 'Couldn’t retry the email' },
  })
}

/** "Retry all failed": every failed email still recent enough to send. */
export function useRetryFailedOutboxEmails() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => unwrap(api.POST('/api/v1/admin/email/outbox/retry-failed', {})),
    onSuccess: ({ retried }) => {
      toast.success(
        retried === 0
          ? 'Nothing to retry'
          : `${retried.toLocaleString()} ${retried === 1 ? 'email' : 'emails'} queued again`,
        retried === 0 ? { description: 'The failed emails are too old to send.' } : undefined,
      )
    },
    onSettled: () => refreshEmail(queryClient),
    meta: { errorTitle: 'Couldn’t retry the failed emails' },
  })
}
