import {
  infiniteQueryOptions,
  queryOptions,
  useInfiniteQuery,
  useMutation,
  useQueries,
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
  IdeaDetail,
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

/** An idea approved or rejected a moment ago (its Undo toast is open), per project. */
const hiddenSubmission = (slug: string, ideaId: string) =>
  `moderation:${slug.toLowerCase()}:${ideaId}`

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
      const items = all.filter((item) => !hidden.has(hiddenSubmission(slug, item.id)))
      const total = (data.pages[0]?.total ?? 0) - (all.length - items.length)
      return { ...data, items, total: Math.max(0, total) }
    },
    [hidden, slug],
  )
  return useInfiniteQuery({
    ...moderationQueueOptions(slug),
    enabled: options.enabled ?? true,
    select,
  })
}

const moderationCountOptions = (slug: string) =>
  queryOptions({
    queryKey: [...queryKeys.submissions.moderation(slug), 'count'] as const,
    queryFn: ({ signal }) =>
      unwrap(
        api.GET('/api/v1/projects/{slug}/moderation', {
          params: { path: { slug }, query: { limit: 1 } },
          signal,
        }),
      ),
    staleTime: 30_000,
    refetchOnWindowFocus: true,
  })

/** The queue's total less the ideas approved or rejected a moment ago (Undo still open). */
function waiting(page: ModerationPage, slug: string, hidden: ReadonlySet<string>): number {
  const prefix = hiddenSubmission(slug, '')
  const pending = [...hidden].filter((key) => key.startsWith(prefix)).length
  return Math.max(0, page.total - pending)
}

/** "N ideas waiting for review" (project admins only: others get 403, so don't ask). */
export function useModerationCount(slug: string, options: { enabled?: boolean } = {}) {
  const hidden = useHiddenItems()
  return useQuery({
    ...moderationCountOptions(slug),
    enabled: options.enabled ?? true,
    select: (page) => waiting(page, slug, hidden),
  })
}

/** What a project list row needs for review counts (the sidebar's list or full projects). */
interface ReviewableProject {
  id: string
  slug: string
  name: string
  archived_at: string | null
  permissions: { can_manage: boolean }
}

export interface ReviewCount<P extends ReviewableProject = ReviewableProject> {
  project: P
  count: number
}

/**
 * Projects with ideas waiting for review that you can moderate (the sidebar's
 * "Review" and My work's "Waiting for review"): held ideas are on no board,
 * list or inbox, so this is how admins notice them. One small request per
 * project you administer (shared with the board's notice); archived projects
 * can't be moderated, so they're skipped.
 */
export function useReviewCounts<P extends ReviewableProject>(
  projects: readonly P[] | undefined,
): ReviewCount<P>[] {
  const hidden = useHiddenItems()
  const reviewable = (projects ?? []).filter(
    (project) => project.permissions.can_manage && !project.archived_at,
  )
  const pages = useQueries({ queries: reviewable.map((p) => moderationCountOptions(p.slug)) })
  return reviewable.flatMap((project, index) => {
    const page = pages[index]?.data
    const count = page ? waiting(page, project.slug, hidden) : 0
    return count > 0 ? [{ project, count }] : []
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

/**
 * Takes a moderated idea out of the cached queue and count (both shapes: the
 * infinite queue and the count's single page), so nothing flickers back in
 * between unhiding it and the refetch.
 */
function dropFromQueue(queryClient: QueryClient, slug: string, ideaId: string) {
  queryClient.setQueriesData<ModerationData | ModerationPage>(
    { queryKey: queryKeys.submissions.moderation(slug) },
    (data) => {
      if (!data) return data
      const drop = (page: ModerationPage): ModerationPage => {
        const items = page.items.filter((item) => item.id !== ideaId)
        return items.length === page.items.length ? page : { ...page, items }
      }
      if ('pages' in data) {
        const found = data.pages.some((page) => page.items.some((item) => item.id === ideaId))
        if (!found) return data
        return {
          ...data,
          pages: data.pages.map((page, index) => {
            const next = drop(page)
            return index === 0 ? { ...next, total: Math.max(0, page.total - 1) } : next
          }),
        }
      }
      // The count (limit 1): the idea may be on no page it holds, but it was counted.
      return { ...drop(data), total: Math.max(0, data.total - 1) }
    },
  )
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
      const key = hiddenSubmission(idea.project.slug, idea.id)
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
          dropFromQueue(queryClient, idea.project.slug, idea.id)
          if (action === 'approve') {
            // The idea page's banner goes at once; the refetch brings its permissions.
            queryClient.setQueryData<IdeaDetail>(queryKeys.ideas.detail(idea.key), (detail) =>
              detail ? { ...detail, held_for: null } : detail,
            )
          }
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
export function useModerationPending(idea: Pick<ModerationTarget, 'id' | 'project'>): boolean {
  const hidden = useHiddenItems()
  return hidden.has(hiddenSubmission(idea.project.slug, idea.id))
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
