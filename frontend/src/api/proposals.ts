/**
 * Proposals (contract-phase4 §3.1–3.4): the Proposal tab's view, section saves
 * (optimistic concurrency per section), margin threads and the exports.
 *
 *   useProposal(key)                 the tab: proposal (or null) + permissions
 *   useCreateProposal(key)           "Start proposal" (moves a Shortlisted idea to Proposal)
 *   saveProposalSection(…)           one section's PUT (the editor's save controller calls it)
 *   useProposalThreads(key)          margin threads; deleted-but-undoable comments filtered out
 *   useCreateProposalThread(key) · useReplyToProposalThread(key) ·
 *   useSetProposalThreadResolved(key) · useDeleteProposalComment(key) (deferred, Undo)
 *   useExportProposal(key)           Markdown / PDF download through fetch + blob
 */
import {
  MutationObserver,
  queryOptions,
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from '@tanstack/react-query'
import { useCallback } from 'react'

import { api, unwrap } from '@/api/client'
import { networkError, toApiError } from '@/api/errors'
import { queryKeys } from '@/api/keys'
import type {
  CurrentUser,
  ProposalComment,
  ProposalSection,
  ProposalSectionKey,
  ProposalThread,
  ProposalThreadList,
  ProposalView,
} from '@/api/types'
import { deferUntilToastCloses, hideItem, unhideItem, useHiddenItems } from '@/api/undo'

export const proposalQueryOptions = (idea: string) =>
  queryOptions({
    queryKey: queryKeys.proposals.view(idea),
    queryFn: ({ signal }) =>
      unwrap(api.GET('/api/v1/ideas/{idea}/proposal', { params: { path: { idea } }, signal })),
  })

/** The Proposal tab: `proposal` is null until someone starts one. */
export function useProposal(idea: string) {
  return useQuery(proposalQueryOptions(idea))
}

/** Puts one saved section into the cached view (the rest of the proposal untouched). */
export function storeProposalSection(
  queryClient: QueryClient,
  idea: string,
  section: ProposalSection,
): void {
  queryClient.setQueryData<ProposalView>(queryKeys.proposals.view(idea), (view) => {
    if (!view?.proposal) return view
    return {
      ...view,
      proposal: {
        ...view.proposal,
        updated_at:
          section.updated_at > view.proposal.updated_at
            ? section.updated_at
            : view.proposal.updated_at,
        sections: view.proposal.sections.map((current) =>
          current.key === section.key ? section : current,
        ),
      },
    }
  })
}

/**
 * Saves one section from `baseVersion`. Throws the ApiError (409
 * `proposal_conflict` carries `problem.current`). Not a hook: the editor's save
 * store keeps saving after the tab unmounts (switching tabs flushes pending
 * saves), so it runs through a MutationObserver of the app's QueryClient — a
 * 401 still ends the session as everywhere else; other errors are shown inline
 * by the editor (silent).
 */
export function saveProposalSection(
  queryClient: QueryClient,
  idea: string,
  key: ProposalSectionKey,
  bodyMd: string,
  baseVersion: number,
  options: { keepalive?: boolean } = {},
): Promise<ProposalSection> {
  const observer = new MutationObserver(queryClient, {
    mutationFn: () =>
      unwrap(
        api.PUT('/api/v1/ideas/{idea}/proposal/sections/{section_key}', {
          params: { path: { idea, section_key: key } },
          body: { body_md: bodyMd, base_version: baseVersion },
          keepalive: options.keepalive,
        }),
      ),
    meta: { silent: true },
  })
  return observer.mutate()
}

/** "Start proposal": creates the eight sections; a Shortlisted idea moves to Proposal. */
export function useCreateProposal(idea: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () =>
      unwrap(api.POST('/api/v1/ideas/{idea}/proposal', { params: { path: { idea } } })),
    onSuccess: (view) => {
      queryClient.setQueryData(queryKeys.proposals.view(idea), view)
      queryClient.setQueryData<ProposalThreadList>(queryKeys.proposals.threads(idea), {
        items: [],
      })
    },
    onSettled: () => {
      // The idea's status may have moved (Shortlisted → Proposal): everything that shows it.
      void queryClient.invalidateQueries({ queryKey: queryKeys.proposals.view(idea) })
      void queryClient.invalidateQueries({ queryKey: queryKeys.ideas.all })
      void queryClient.invalidateQueries({ queryKey: queryKeys.activity.idea(idea) })
      void queryClient.invalidateQueries({ queryKey: queryKeys.work.all })
    },
    meta: { errorTitle: 'Couldn’t start the proposal' },
  })
}

/* ------------------------------------------------------------------ */
/* Margin threads                                                      */
/* ------------------------------------------------------------------ */

const hiddenComment = (commentId: string) => `proposal-comment:${commentId}`

export const proposalThreadsQueryOptions = (idea: string) =>
  queryOptions({
    queryKey: queryKeys.proposals.threads(idea),
    queryFn: ({ signal }) =>
      unwrap(
        api.GET('/api/v1/ideas/{idea}/proposal/threads', { params: { path: { idea } }, signal }),
      ),
  })

/**
 * Every thread (template order, then oldest first). Comments waiting for a
 * deferred delete are left out, and a thread left with no comment to show
 * disappears until the delete is undone.
 */
export function useProposalThreads(idea: string, { enabled = true }: { enabled?: boolean } = {}) {
  const hidden = useHiddenItems()
  const select = useCallback(
    (data: ProposalThreadList) => ({
      items: data.items.flatMap((thread) => {
        const comments = thread.comments.filter((comment) => !hidden.has(hiddenComment(comment.id)))
        return comments.some((comment) => !comment.deleted) ? [{ ...thread, comments }] : []
      }),
    }),
    [hidden],
  )
  return useQuery({ ...proposalThreadsQueryOptions(idea), enabled, select })
}

function storeThread(queryClient: QueryClient, idea: string, thread: ProposalThread): void {
  queryClient.setQueryData<ProposalThreadList>(queryKeys.proposals.threads(idea), (list) => {
    if (!list) return { items: [thread] }
    const exists = list.items.some((item) => item.id === thread.id)
    return {
      items: exists
        ? list.items.map((item) => (item.id === thread.id ? thread : item))
        : [...list.items, thread],
    }
  })
}

/** A pending comment by you, shown until the server's copy arrives. */
function pendingComment(queryClient: QueryClient, bodyMd: string): ProposalComment {
  const user = queryClient.getQueryData<CurrentUser>(queryKeys.auth.me())
  return {
    id: `pending-${String(Date.now())}`,
    author: user
      ? {
          id: user.id,
          display_name: user.display_name,
          avatar_url: user.avatar_url,
          initials: user.initials,
        }
      : null,
    body_md: bodyMd,
    created_at: new Date().toISOString(),
    deleted: false,
    can_delete: false,
  }
}

/** Opens a thread on a section with its first comment. */
export function useCreateProposalThread(idea: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ sectionKey, bodyMd }: { sectionKey: ProposalSectionKey; bodyMd: string }) =>
      unwrap(
        api.POST('/api/v1/ideas/{idea}/proposal/threads', {
          params: { path: { idea } },
          body: { section_key: sectionKey, body_md: bodyMd },
        }),
      ),
    onSuccess: (thread) => storeThread(queryClient, idea, thread),
    onSettled: () =>
      void queryClient.invalidateQueries({ queryKey: queryKeys.proposals.threads(idea) }),
    meta: { errorTitle: 'Couldn’t post your comment' },
  })
}

/** Replies in a thread (shown at once; a reply reopens a resolved thread). */
export function useReplyToProposalThread(idea: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ threadId, bodyMd }: { threadId: string; bodyMd: string }) =>
      unwrap(
        api.POST('/api/v1/ideas/{idea}/proposal/threads/{thread_id}/comments', {
          params: { path: { idea, thread_id: threadId } },
          body: { body_md: bodyMd },
        }),
      ),
    onMutate: async ({ threadId, bodyMd }) => {
      const key = queryKeys.proposals.threads(idea)
      await queryClient.cancelQueries({ queryKey: key })
      const previous = queryClient.getQueryData<ProposalThreadList>(key)
      const pending = pendingComment(queryClient, bodyMd)
      queryClient.setQueryData<ProposalThreadList>(key, (list) =>
        list
          ? {
              items: list.items.map((thread) =>
                thread.id === threadId
                  ? {
                      ...thread,
                      resolved_at: null,
                      resolved_by: null,
                      comments: [...thread.comments, pending],
                    }
                  : thread,
              ),
            }
          : list,
      )
      return { previous }
    },
    onError: (_error, _vars, context) => {
      if (context?.previous)
        queryClient.setQueryData(queryKeys.proposals.threads(idea), context.previous)
    },
    onSuccess: (thread) => storeThread(queryClient, idea, thread),
    onSettled: () =>
      void queryClient.invalidateQueries({ queryKey: queryKeys.proposals.threads(idea) }),
    meta: { errorTitle: 'Couldn’t post your reply' },
  })
}

/** Resolve (true) or reopen (false) a thread; the change shows at once. */
export function useSetProposalThreadResolved(idea: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ threadId, resolved }: { threadId: string; resolved: boolean }) => {
      const params = { params: { path: { idea, thread_id: threadId } } }
      const path = '/api/v1/ideas/{idea}/proposal/threads/{thread_id}/resolved' as const
      return unwrap(resolved ? api.PUT(path, params) : api.DELETE(path, params))
    },
    onMutate: async ({ threadId, resolved }) => {
      const key = queryKeys.proposals.threads(idea)
      await queryClient.cancelQueries({ queryKey: key })
      const previous = queryClient.getQueryData<ProposalThreadList>(key)
      const me = queryClient.getQueryData<CurrentUser>(queryKeys.auth.me())
      queryClient.setQueryData<ProposalThreadList>(key, (list) =>
        list
          ? {
              items: list.items.map((thread) =>
                thread.id === threadId
                  ? {
                      ...thread,
                      resolved_at: resolved ? new Date().toISOString() : null,
                      resolved_by:
                        resolved && me
                          ? {
                              id: me.id,
                              display_name: me.display_name,
                              avatar_url: me.avatar_url,
                              initials: me.initials,
                            }
                          : null,
                    }
                  : thread,
              ),
            }
          : list,
      )
      return { previous }
    },
    onError: (_error, _vars, context) => {
      if (context?.previous)
        queryClient.setQueryData(queryKeys.proposals.threads(idea), context.previous)
    },
    onSuccess: (thread) => storeThread(queryClient, idea, thread),
    meta: { errorTitle: 'Couldn’t update the thread' },
  })
}

/**
 * Delete a margin comment — deferred like idea comments (contract §3.14): it
 * disappears at once and the DELETE goes out when the Undo toast closes.
 */
export function useDeleteProposalComment(idea: string) {
  const queryClient = useQueryClient()
  return useCallback(
    (threadId: string, commentId: string) => {
      const key = hiddenComment(commentId)
      deferUntilToastCloses({
        title: 'Comment deleted',
        hide: () => hideItem(key),
        restore: () => unhideItem(key),
        commit: async ({ keepalive }) => {
          await api.DELETE(
            '/api/v1/ideas/{idea}/proposal/threads/{thread_id}/comments/{comment_id}',
            {
              params: { path: { idea, thread_id: threadId, comment_id: commentId } },
              keepalive,
            },
          )
          await queryClient.invalidateQueries({ queryKey: queryKeys.proposals.threads(idea) })
          unhideItem(key)
        },
        errorTitle: 'Couldn’t delete the comment',
      })
    },
    [queryClient, idea],
  )
}

/* ------------------------------------------------------------------ */
/* Exports                                                             */
/* ------------------------------------------------------------------ */

export type ProposalExportFormat = 'markdown' | 'pdf'

/** The filename from `Content-Disposition` (ASCII, from the idea key), or a fallback. */
export function exportFilename(response: Response, fallback: string): string {
  const header = response.headers.get('content-disposition') ?? ''
  const match = /filename="([^"]+)"/i.exec(header)
  const name = match?.[1]
  return name && /^[\w.-]+$/.test(name) ? name : fallback
}

/** Fetches an export and hands it to the browser as a download. */
export async function downloadProposal(idea: string, format: ProposalExportFormat): Promise<void> {
  const url = `/api/v1/ideas/${encodeURIComponent(idea)}/proposal/${format}`
  let response: Response
  try {
    response = await fetch(url, { credentials: 'same-origin' })
  } catch (error) {
    throw networkError(error)
  }
  if (!response.ok) throw await toApiError(response)
  const blob = await response.blob()
  const fallback = `${idea.toUpperCase()}-proposal.${format === 'pdf' ? 'pdf' : 'md'}`
  const href = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = href
  link.download = exportFilename(response, fallback)
  link.rel = 'noopener'
  document.body.append(link)
  link.click()
  link.remove()
  // Give the browser a moment to start the download before the URL goes.
  window.setTimeout(() => URL.revokeObjectURL(href), 10_000)
}

/** Export as Markdown or PDF; errors are shown by the caller (toast with Retry). */
export function useExportProposal(idea: string) {
  return useMutation({
    mutationFn: (format: ProposalExportFormat) => downloadProposal(idea, format),
    meta: { silent: true },
  })
}
