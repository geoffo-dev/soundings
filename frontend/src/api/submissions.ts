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
import { useCallback } from 'react'

import { api, unwrap } from '@/api/client'
import { describeError } from '@/api/errors'
import { queryKeys } from '@/api/keys'
import { deferUntilToastCloses, hideItem, unhideItem, useHiddenItems } from '@/api/undo'
import type {
  IdeaSubmission,
  ModerationPage,
  PublicFormSettings,
  PublicFormSettingsUpdate,
} from '@/api/types'

/**
 * Public form settings, the moderation queue and public submitters
 * (contract-phase4 §2 "Public form settings, moderation and submitters",
 * §3.6, §3.9). Approve and reject wait for their Undo toast (a deferred commit,
 * api/undo): reject deletes the idea, and neither has an inverse request.
 */

const PAGE_SIZE = 25

export const publicFormSettingsQueryOptions = (slug: string) =>
  queryOptions({
    queryKey: queryKeys.submissions.form(slug),
    queryFn: ({ signal }) =>
      unwrap(
        api.GET('/api/v1/projects/{slug}/public-form', { params: { path: { slug } }, signal }),
      ),
  })

export function usePublicFormSettings(slug: string, options: { enabled?: boolean } = {}) {
  return useQuery({ ...publicFormSettingsQueryOptions(slug), enabled: options.enabled ?? true })
}

/** Partial update; errors (409 `public_submission_unavailable`, `smtp_not_configured`) inline. */
export function useUpdatePublicFormSettings(slug: string) {
  const queryClient = useQueryClient()
  return useMutation<PublicFormSettings, Error, PublicFormSettingsUpdate>({
    mutationFn: (body) =>
      unwrap(
        api.PATCH('/api/v1/projects/{slug}/public-form', { params: { path: { slug } }, body }),
      ),
    onSuccess: (settings) => {
      queryClient.setQueryData(queryKeys.submissions.form(slug), settings)
      void queryClient.invalidateQueries({ queryKey: queryKeys.public.project(slug) })
    },
    meta: { silent: true },
  })
}

export const moderationQueueOptions = (slug: string, limit = PAGE_SIZE) =>
  infiniteQueryOptions({
    queryKey: [...queryKeys.submissions.moderation(slug), limit] as const,
    queryFn: ({ pageParam, signal }) =>
      unwrap(
        api.GET('/api/v1/projects/{slug}/moderation', {
          params: { path: { slug }, query: { cursor: pageParam ?? undefined, limit } },
          signal,
        }),
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor,
    staleTime: 15_000,
  })

type ModerationData = InfiniteData<ModerationPage, string | null>

const hiddenSubmission = (ideaId: string) => `moderation:${ideaId}`

/**
 * The queue, oldest first. Ideas approved or rejected while their Undo toast is
 * open are left out (and `total` counts them out) so a refetch can't bring them
 * back and Undo is exact.
 */
export function useModerationQueue(slug: string, options: { enabled?: boolean } = {}) {
  const hidden = useHiddenItems()
  const select = useCallback(
    (data: ModerationData) => {
      const all = data.pages.flatMap((page) => page.items)
      const items = all.filter((item) => !hidden.has(hiddenSubmission(item.id)))
      const total = (data.pages[0]?.total ?? 0) - (all.length - items.length)
      return { ...data, items, total: Math.max(0, total) }
    },
    [hidden],
  )
  return useInfiniteQuery({
    ...moderationQueueOptions(slug),
    enabled: options.enabled ?? true,
    select,
  })
}

/** "N ideas waiting for review" (project admins only: others get 403, so don't ask). */
export function useModerationCount(slug: string, options: { enabled?: boolean } = {}) {
  const hidden = useHiddenItems()
  return useQuery({
    queryKey: [...queryKeys.submissions.moderation(slug), 'count'] as const,
    queryFn: ({ signal }) =>
      unwrap(
        api.GET('/api/v1/projects/{slug}/moderation', {
          params: { path: { slug }, query: { limit: 1 } },
          signal,
        }),
      ),
    enabled: options.enabled ?? true,
    staleTime: 30_000,
    refetchOnWindowFocus: true,
    select: (page) => {
      const pending = [...hidden].filter((key) => key.startsWith('moderation:')).length
      return Math.max(0, page.total - pending)
    },
  })
}

export const ideaSubmissionQueryOptions = (idea: string) =>
  queryOptions({
    queryKey: queryKeys.submissions.idea(idea),
    queryFn: ({ signal }) =>
      unwrap(api.GET('/api/v1/ideas/{idea}/submission', { params: { path: { idea } }, signal })),
  })

/** How a public idea came in (name, and contact details for admins). Only for public ideas. */
export function useIdeaSubmission(idea: string, options: { enabled?: boolean } = {}) {
  return useQuery({ ...ideaSubmissionQueryOptions(idea), enabled: options.enabled ?? true })
}

function afterModeration(queryClient: QueryClient, slug: string, ideaKey: string) {
  void queryClient.invalidateQueries({ queryKey: queryKeys.submissions.moderation(slug) })
  void queryClient.invalidateQueries({ queryKey: queryKeys.submissions.form(slug) })
  void queryClient.invalidateQueries({ queryKey: queryKeys.submissions.idea(ideaKey) })
  void queryClient.invalidateQueries({ queryKey: queryKeys.ideas.all })
  void queryClient.invalidateQueries({ queryKey: queryKeys.projects.all })
  void queryClient.invalidateQueries({ queryKey: queryKeys.work.all })
  void queryClient.invalidateQueries({ queryKey: queryKeys.search.all })
}

export interface ModerationTarget {
  id: string
  key: string
  title: string
  project: { slug: string }
}

/**
 * Approve or reject, each with an Undo toast: the idea leaves the queue at
 * once and the request is sent when the toast closes (or the page is hidden).
 * `onDone` runs after a successful commit (e.g. leave a rejected idea's page).
 */
export function useModerate() {
  const queryClient = useQueryClient()
  const run = useCallback(
    (
      action: 'approve' | 'reject',
      idea: ModerationTarget,
      callbacks: { onHide?: () => void; onRestore?: () => void; onDone?: () => void } = {},
    ) => {
      const key = hiddenSubmission(idea.id)
      deferUntilToastCloses({
        title:
          action === 'approve'
            ? `${idea.key} approved: it’s in New now`
            : `${idea.key} rejected and deleted`,
        description: idea.title,
        hide: () => {
          hideItem(key)
          callbacks.onHide?.()
        },
        restore: () => {
          unhideItem(key)
          callbacks.onRestore?.()
        },
        commit: async ({ keepalive }) => {
          try {
            if (action === 'approve') {
              await api.POST('/api/v1/ideas/{idea}/submission/approve', {
                params: { path: { idea: idea.key } },
                keepalive,
              })
            } else {
              await api.POST('/api/v1/ideas/{idea}/submission/reject', {
                params: { path: { idea: idea.key } },
                keepalive,
              })
            }
          } catch (error) {
            const { title, description } = describeError(error)
            throw new Error(description ? `${title}. ${description}` : title)
          }
        },
        onCommitted: () => {
          unhideItem(key)
          afterModeration(queryClient, idea.project.slug, idea.key)
          if (action === 'reject') {
            queryClient.removeQueries({ queryKey: queryKeys.ideas.detail(idea.key) })
          }
          callbacks.onDone?.()
        },
        errorTitle:
          action === 'approve' ? `Couldn’t approve ${idea.key}` : `Couldn’t reject ${idea.key}`,
      })
    },
    [queryClient],
  )
  return {
    approve: (idea: ModerationTarget, callbacks?: Parameters<typeof run>[2]) =>
      run('approve', idea, callbacks),
    reject: (idea: ModerationTarget, callbacks?: Parameters<typeof run>[2]) =>
      run('reject', idea, callbacks),
  }
}

/** Is this idea waiting for its Undo toast (approved or rejected a moment ago)? */
export function useModerationPending(ideaId: string | undefined): boolean {
  const hidden = useHiddenItems()
  return ideaId ? hidden.has(hiddenSubmission(ideaId)) : false
}

/** Erase the submitter's details (cannot be undone: the caller confirms first). */
export function useEraseSubmitter(ideaKey: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (): Promise<IdeaSubmission> =>
      unwrap(
        api.POST('/api/v1/ideas/{idea}/submission/erase', { params: { path: { idea: ideaKey } } }),
      ),
    onSuccess: (submission) => {
      queryClient.setQueryData(queryKeys.submissions.idea(ideaKey), submission)
      void queryClient.invalidateQueries({ queryKey: queryKeys.submissions.moderationAll() })
    },
    meta: { silent: true },
  })
}
