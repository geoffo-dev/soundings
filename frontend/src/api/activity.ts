import {
  infiniteQueryOptions,
  useInfiniteQuery,
  useMutation,
  useQueryClient,
  type InfiniteData,
} from '@tanstack/react-query'
import { useCallback } from 'react'

import { patchIdea, snapshot } from '@/api/cache'
import { api, unwrap } from '@/api/client'
import { queryKeys } from '@/api/keys'
import type { ActivityItem, ActivityPage, CommentActivity, CurrentUser } from '@/api/types'
import { deferUntilToastCloses, hiddenKey, hideItem, unhideItem, useHiddenItems } from '@/api/undo'

type ActivityData = InfiniteData<ActivityPage, string | null>

/** An idea's activity feed, newest first (pages of `limit`). */
export const ideaActivityInfiniteOptions = (idea: string, limit = 50) =>
  infiniteQueryOptions({
    queryKey: queryKeys.activity.idea(idea),
    queryFn: ({ pageParam, signal }) =>
      unwrap(
        api.GET('/api/v1/ideas/{idea}/activity', {
          params: { path: { idea }, query: { cursor: pageParam ?? undefined, limit } },
          signal,
        }),
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor,
  })

/**
 * The feed. `items` is flattened and ordered **oldest → newest** (the way the
 * idea page shows it); older pages load with `fetchNextPage`. Comments waiting
 * for a deferred delete are left out.
 */
export function useIdeaActivity(idea: string, limit = 50) {
  const hidden = useHiddenItems()
  const select = useCallback(
    (data: ActivityData) => ({
      ...data,
      items: data.pages
        .flatMap((page) => page.items)
        .filter(
          (item) => item.type !== 'comment' || !hidden.has(hiddenKey.comment(item.comment.id)),
        )
        .reverse(),
    }),
    [hidden],
  )
  return useInfiniteQuery({ ...ideaActivityInfiniteOptions(idea, limit), select })
}

function updateComments(
  data: ActivityData | undefined,
  update: (items: ActivityItem[], pageIndex: number) => ActivityItem[],
): ActivityData | undefined {
  if (!data) return data
  return {
    ...data,
    pages: data.pages.map((page, i) => ({ ...page, items: update(page.items, i) })),
  }
}

/** Post a comment: it appears at once (pending) and is replaced by the saved one. */
export function useCreateComment(idea: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (bodyMd: string) =>
      unwrap(
        api.POST('/api/v1/ideas/{idea}/comments', {
          params: { path: { idea } },
          body: { body_md: bodyMd },
        }),
      ),
    onMutate: async (bodyMd) => {
      const rollback = await snapshot(queryClient, [
        queryKeys.activity.idea(idea),
        queryKeys.ideas.all,
      ])
      const user = queryClient.getQueryData<CurrentUser>(queryKeys.auth.me())
      const tempId = `pending-${Date.now()}`
      const optimistic: CommentActivity = {
        type: 'comment',
        id: tempId,
        idea_id: '',
        created_at: new Date().toISOString(),
        actor: user
          ? {
              id: user.id,
              display_name: user.display_name,
              avatar_url: user.avatar_url,
              initials: user.initials,
            }
          : null,
        comment: {
          id: tempId,
          body_md: bodyMd,
          deleted: false,
          edited_at: null,
          can_edit: false,
          can_delete: false,
        },
      }
      queryClient.setQueryData<ActivityData>(queryKeys.activity.idea(idea), (data) =>
        updateComments(data, (items, pageIndex) =>
          pageIndex === 0 ? [optimistic, ...items] : items,
        ),
      )
      patchIdea(queryClient, idea, (current) => ({ comment_count: current.comment_count + 1 }))
      return { rollback, tempId }
    },
    onError: (_error, _body, context) => context?.rollback(),
    onSuccess: (saved, _body, context) => {
      queryClient.setQueryData<ActivityData>(queryKeys.activity.idea(idea), (data) =>
        updateComments(data, (items) =>
          items.map((item) => (item.id === context.tempId ? saved : item)),
        ),
      )
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.activity.idea(idea) })
      void queryClient.invalidateQueries({ queryKey: queryKeys.ideas.detail(idea) })
    },
    meta: { errorTitle: 'Couldn’t post your comment' },
  })
}

/** Edit your comment (optimistic; rolled back on error). */
export function useUpdateComment(idea: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ commentId, bodyMd }: { commentId: string; bodyMd: string }) =>
      unwrap(
        api.PATCH('/api/v1/comments/{comment_id}', {
          params: { path: { comment_id: commentId } },
          body: { body_md: bodyMd },
        }),
      ),
    onMutate: async ({ commentId, bodyMd }) => {
      const rollback = await snapshot(queryClient, [queryKeys.activity.idea(idea)])
      queryClient.setQueryData<ActivityData>(queryKeys.activity.idea(idea), (data) =>
        updateComments(data, (items) =>
          items.map((item) =>
            item.type === 'comment' && item.comment.id === commentId
              ? {
                  ...item,
                  comment: {
                    ...item.comment,
                    body_md: bodyMd,
                    edited_at: new Date().toISOString(),
                  },
                }
              : item,
          ),
        ),
      )
      return { rollback }
    },
    onError: (_error, _vars, context) => context?.rollback(),
    onSuccess: (saved) => {
      queryClient.setQueryData<ActivityData>(queryKeys.activity.idea(idea), (data) =>
        updateComments(data, (items) => items.map((item) => (item.id === saved.id ? saved : item))),
      )
    },
    meta: { errorTitle: 'Couldn’t save your comment' },
  })
}

/**
 * Delete a comment — deferred (contract §3.14): it disappears at once, the
 * DELETE is sent when the Undo toast closes (or the page is hidden), and Undo
 * brings it back untouched.
 */
export function useDeleteComment(idea: string) {
  const queryClient = useQueryClient()
  return useCallback(
    (commentId: string) => {
      const key = hiddenKey.comment(commentId)
      deferUntilToastCloses({
        title: 'Comment deleted',
        hide: () => {
          hideItem(key)
          patchIdea(queryClient, idea, (current) => ({
            comment_count: Math.max(0, current.comment_count - 1),
          }))
        },
        restore: () => {
          unhideItem(key)
          patchIdea(queryClient, idea, (current) => ({ comment_count: current.comment_count + 1 }))
        },
        commit: async ({ keepalive }) => {
          await api.DELETE('/api/v1/comments/{comment_id}', {
            params: { path: { comment_id: commentId } },
            keepalive,
          })
          await queryClient.invalidateQueries({ queryKey: queryKeys.activity.idea(idea) })
          unhideItem(key)
        },
        errorTitle: 'Couldn’t delete the comment',
      })
    },
    [queryClient, idea],
  )
}
