import {
  infiniteQueryOptions,
  queryOptions,
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from '@tanstack/react-query'
import { useCallback } from 'react'

import {
  findCachedIdea,
  moveOnBoards,
  patchIdea,
  patchIdeaDetail,
  snapshot,
  statusLabelFor,
} from '@/api/cache'
import { api, unwrap } from '@/api/client'
import { normaliseFilters, queryKeys } from '@/api/keys'
import { openResearchGate, overrideBody } from '@/api/research'
import type {
  CurrentUser,
  IdeaCreate,
  IdeaDetail,
  IdeaFilters,
  IdeaStatus,
  ResearchOverride,
  IdeaSummary,
  IdeaUpdate,
  Resolution,
  UserRef,
} from '@/api/types'
import {
  deferUntilToastCloses,
  hiddenKey,
  hideItem,
  offerUndo,
  unhideItem,
  useHiddenItems,
} from '@/api/undo'

/* ------------------------------------------------------------------ */
/* Queries                                                             */
/* ------------------------------------------------------------------ */

export interface IdeaListOptions {
  /** Page size (default 50, max 200). */
  pageSize?: number
  /** Start from this cursor, e.g. a board column's `next_cursor` ("load more"). */
  initialCursor?: string | null
}

/**
 * The project List view (and "load more" for a board column: pass
 * `status: [column]` plus the column's `next_cursor` as `initialCursor`).
 * Pages come from `data.pages`; `total` is on every page.
 */
export const ideaListInfiniteOptions = (
  slug: string,
  filters: IdeaFilters = {},
  { pageSize = 50, initialCursor = null }: IdeaListOptions = {},
) =>
  infiniteQueryOptions({
    queryKey: [...queryKeys.ideas.list(slug, filters), { pageSize, from: initialCursor }] as const,
    queryFn: ({ pageParam, signal }) =>
      unwrap(
        api.GET('/api/v1/projects/{slug}/ideas', {
          params: {
            path: { slug },
            query: {
              ...normaliseFilters(filters),
              cursor: pageParam ?? undefined,
              limit: pageSize,
            },
          },
          signal,
        }),
      ),
    initialPageParam: initialCursor,
    getNextPageParam: (page) => page.next_cursor,
  })

export function useIdeaList(
  slug: string,
  filters: IdeaFilters = {},
  options: IdeaListOptions & { enabled?: boolean } = {},
) {
  return useInfiniteQuery({
    ...ideaListInfiniteOptions(slug, filters, options),
    enabled: options.enabled ?? true,
  })
}

/** The Board: five columns with counts and the first `limit` ideas each. */
export const boardQueryOptions = (slug: string, filters: IdeaFilters = {}, limit = 50) => {
  const { status: _status, resolution: _resolution, ...boardFilters } = normaliseFilters(filters)
  return queryOptions({
    queryKey: [...queryKeys.ideas.board(slug, boardFilters), { limit }] as const,
    queryFn: ({ signal }) =>
      unwrap(
        api.GET('/api/v1/projects/{slug}/board', {
          params: { path: { slug }, query: { ...boardFilters, limit } },
          signal,
        }),
      ),
  })
}

export function useBoard(slug: string, filters: IdeaFilters = {}, limit = 50) {
  return useQuery(boardQueryOptions(slug, filters, limit))
}

/** One idea by key ("CUST-12", any case) or id. */
export const ideaQueryOptions = (idea: string) =>
  queryOptions({
    queryKey: queryKeys.ideas.detail(idea),
    queryFn: ({ signal }) =>
      unwrap(api.GET('/api/v1/ideas/{idea}', { params: { path: { idea } }, signal })),
  })

/**
 * The idea page. Evaluators whose removal is waiting for its Undo toast are
 * filtered out (and the progress adjusted), so a refetch can't show them.
 */
export function useIdea(idea: string) {
  const hidden = useHiddenItems()
  const select = useCallback((data: IdeaDetail) => withoutHiddenEvaluators(data, hidden), [hidden])
  return useQuery({ ...ideaQueryOptions(idea), select })
}

/**
 * The idea as any list, board or My work cache already knows it, so the idea
 * page can show the title and status instantly while the detail loads.
 */
export function useCachedIdeaSummary(idea: string): IdeaSummary | undefined {
  const queryClient = useQueryClient()
  return findCachedIdea(queryClient, idea)
}

function withoutHiddenEvaluators(idea: IdeaDetail, hidden: ReadonlySet<string>): IdeaDetail {
  if (hidden.size === 0) return idea
  const evaluators = idea.evaluators.filter(
    (evaluator) => !hidden.has(hiddenKey.evaluator(idea.id, evaluator.user.id)),
  )
  if (evaluators.length === idea.evaluators.length) return idea
  return {
    ...idea,
    evaluators,
    evaluator_progress: {
      total: evaluators.length,
      submitted: evaluators.filter((e) => e.state === 'submitted').length,
    },
  }
}

/* ------------------------------------------------------------------ */
/* Shared plumbing                                                     */
/* ------------------------------------------------------------------ */

type Undoable<T> = T & {
  /** Internal: this call is itself an Undo, so don't offer another one. */
  isUndo?: boolean
}

interface UndoOption {
  /** Show an Undo toast after success (default true where the contract has an inverse). */
  undo?: boolean
}

const IDEA_CACHES = [queryKeys.ideas.all, queryKeys.work.all]

/** After a change to one idea: store the response and refresh what depends on it. */
function settleIdea(queryClient: QueryClient, key: string, idea?: IdeaDetail) {
  if (idea) {
    // Summaries first: patchIdea also touches the detail, and summary fields
    // (e.g. `permissions: {can_change_status}`) must not replace detail-only ones.
    patchIdea(queryClient, key, () => summaryFields(idea))
    queryClient.setQueryData(queryKeys.ideas.detail(key), idea)
  }
  void queryClient.invalidateQueries({ queryKey: queryKeys.activity.idea(key) })
  void queryClient.invalidateQueries({ queryKey: queryKeys.ideas.lists() })
  void queryClient.invalidateQueries({ queryKey: queryKeys.ideas.boards() })
  void queryClient.invalidateQueries({ queryKey: queryKeys.work.all })
}

/** The IdeaSummary fields of an IdeaDetail (lists must not receive detail-only fields). */
export function summaryFields(idea: IdeaDetail): Partial<IdeaSummary> {
  return {
    title: idea.title,
    summary: idea.summary,
    tags: idea.tags,
    status: idea.status,
    resolution: idea.resolution,
    status_label: idea.status_label,
    owner: idea.owner,
    evaluator_progress: idea.evaluator_progress,
    score: idea.score,
    score_hidden: idea.score_hidden,
    high_disagreement: idea.high_disagreement,
    comment_count: idea.comment_count,
    vote_count: idea.vote_count,
    has_voted: idea.has_voted,
    last_activity_at: idea.last_activity_at,
    permissions: { can_change_status: idea.permissions.can_change_status },
    research: idea.research,
  }
}

function me(queryClient: QueryClient): UserRef | undefined {
  const user = queryClient.getQueryData<CurrentUser>(queryKeys.auth.me())
  return user
    ? {
        id: user.id,
        display_name: user.display_name,
        avatar_url: user.avatar_url,
        initials: user.initials,
      }
    : undefined
}

const path = (idea: string) => ({ params: { path: { idea } } })

/* ------------------------------------------------------------------ */
/* Create, edit, delete                                                */
/* ------------------------------------------------------------------ */

/** Submit an idea. Field errors (422) are left to the form: no toast. */
export function useCreateIdea() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ slug, ...body }: IdeaCreate & { slug: string }) =>
      unwrap(api.POST('/api/v1/projects/{slug}/ideas', { params: { path: { slug } }, body })),
    onSuccess: (idea, { slug }) => {
      queryClient.setQueryData(queryKeys.ideas.detail(idea.key), idea)
      void queryClient.invalidateQueries({ queryKey: queryKeys.ideas.projectLists(slug) })
      void queryClient.invalidateQueries({ queryKey: queryKeys.ideas.projectBoards(slug) })
      void queryClient.invalidateQueries({ queryKey: queryKeys.projects.tags(slug) })
      void queryClient.invalidateQueries({ queryKey: queryKeys.projects.lists() })
      void queryClient.invalidateQueries({ queryKey: queryKeys.work.all })
    },
    meta: { silent: true },
  })
}

/**
 * Inline edits (title, summary, description, tags): applied optimistically
 * everywhere the idea is shown, rolled back if the save fails. The caller keeps
 * the editor open on error (`mutation.error` has the field errors).
 */
export function useUpdateIdea(idea: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: IdeaUpdate) =>
      unwrap(api.PATCH('/api/v1/ideas/{idea}', { ...path(idea), body })),
    onMutate: async (body) => {
      const rollback = await snapshot(queryClient, IDEA_CACHES)
      patchIdea(queryClient, idea, () => ({
        ...(body.title != null && { title: body.title.trim() }),
        ...(body.summary != null && { summary: body.summary.trim() }),
        ...(body.tags != null && {
          tags: [...body.tags].sort((a, b) => a.localeCompare(b, 'en', { sensitivity: 'base' })),
        }),
      }))
      if (body.description_md != null) {
        const description = body.description_md
        patchIdeaDetail(queryClient, idea, () => ({ description_md: description }))
      }
      return { rollback }
    },
    onError: (_error, _body, context) => context?.rollback(),
    onSuccess: (data) => settleIdea(queryClient, idea, data),
    onSettled: (_data, _error, body) => {
      if (body.tags) void queryClient.invalidateQueries({ queryKey: queryKeys.projects.all })
    },
    meta: { silent: true },
  })
}

/** Admins: delete an idea (the UI confirms first; there is no undo). */
export function useDeleteIdea(idea: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => api.DELETE('/api/v1/ideas/{idea}', path(idea)),
    onSuccess: () => {
      queryClient.removeQueries({ queryKey: queryKeys.ideas.detail(idea) })
      queryClient.removeQueries({ queryKey: queryKeys.activity.idea(idea) })
      queryClient.removeQueries({ queryKey: queryKeys.evaluations.idea(idea) })
      void queryClient.invalidateQueries({ queryKey: queryKeys.ideas.all })
      void queryClient.invalidateQueries({ queryKey: queryKeys.projects.all })
      void queryClient.invalidateQueries({ queryKey: queryKeys.work.all })
      void queryClient.invalidateQueries({ queryKey: queryKeys.search.all })
    },
    meta: { errorTitle: 'Couldn’t delete the idea' },
  })
}

/* ------------------------------------------------------------------ */
/* Status (board drag, status menu)                                    */
/* ------------------------------------------------------------------ */

export interface StatusTarget extends ResearchOverride {
  status: IdeaStatus
  /** Required for `closed`, ignored otherwise. */
  resolution?: Resolution | null
  /** If the research gate refuses the move: where focus goes after its dialog (the card). */
  gateFocus?: () => HTMLElement | null
}

/**
 * Change status: the card moves at once (board columns and counts, lists,
 * My work, the idea page), snaps back if the request fails, and an Undo toast
 * sends the previous status and resolution (contract §3.3: no side effects).
 *
 * The board uses one hook for every card: call it without an idea and pass
 * `{ idea: key, status, resolution }` to `mutate`.
 */
export function useChangeIdeaStatus(idea?: string, { undo = true }: UndoOption = {}) {
  const queryClient = useQueryClient()
  const target = (vars: { idea?: string }): string => {
    const ref = vars.idea ?? idea
    if (!ref) throw new Error('useChangeIdeaStatus: pass the idea to the hook or to mutate()')
    return ref
  }
  const mutation = useMutation({
    mutationFn: (vars: Undoable<StatusTarget & { idea?: string }>) =>
      unwrap(
        api.POST('/api/v1/ideas/{idea}/status', {
          ...path(target(vars)),
          body: {
            ...(vars.status === 'closed'
              ? { status: vars.status, resolution: vars.resolution ?? null }
              : { status: vars.status }),
            ...overrideBody(vars),
          },
        }),
      ),
    onMutate: async (vars) => {
      const ref = target(vars)
      const { status, resolution = null } = vars
      const previous = findCachedIdea(queryClient, ref)
      const rollback = await snapshot(queryClient, IDEA_CACHES)
      const to = {
        status,
        resolution: status === 'closed' ? resolution : null,
        status_label: statusLabelFor(queryClient, previous?.project.slug, status, resolution),
      }
      moveOnBoards(queryClient, ref, to)
      patchIdea(queryClient, ref, () => ({ ...to, last_activity_at: new Date().toISOString() }))
      return { rollback, previous }
    },
    onError: (error, vars, context) => {
      context?.rollback()
      // Phase 8: required research items are open: the dialog lists them (and, for
      // admins, "Move anyway" sends the same move with the override).
      openResearchGate(error, {
        ideaKey: target(vars),
        action: 'move',
        targetLabel: statusLabelFor(
          queryClient,
          context?.previous?.project.slug,
          vars.status,
          vars.resolution ?? null,
        ),
        retry: (override) => mutation.mutate({ ...vars, ...override }),
        returnFocus: vars.gateFocus,
      })
    },
    onSuccess: (data, vars, context) => {
      const ref = target(vars)
      settleIdea(queryClient, ref, data)
      const previous = context.previous
      if (undo && !vars.isUndo && previous) {
        offerUndo(`${data.key} moved to ${data.status_label}`, () =>
          mutation.mutate({
            idea: vars.idea,
            status: previous.status,
            resolution: previous.resolution,
            isUndo: true,
          }),
        )
      }
    },
    meta: { errorTitle: 'Couldn’t change the status' },
  })
  return mutation
}

/* ------------------------------------------------------------------ */
/* Owner                                                               */
/* ------------------------------------------------------------------ */

/**
 * Admins assign, change or clear the owner; the owner may only clear it
 * ("Step down"). Undo restores the previous owner — for a step-down that is
 * `volunteer_as_owner`, offered only if the response says `can_volunteer`.
 */
export function useSetIdeaOwner(idea: string, { undo = true }: UndoOption = {}) {
  const queryClient = useQueryClient()
  const volunteer = useVolunteerAsOwner(idea, { undo: false })
  const mutation = useMutation({
    mutationFn: ({ owner }: Undoable<{ owner: UserRef | null }>) =>
      unwrap(
        api.PUT('/api/v1/ideas/{idea}/owner', {
          ...path(idea),
          body: { user_id: owner?.id ?? null },
        }),
      ),
    onMutate: async ({ owner }) => {
      const previous = findCachedIdea(queryClient, idea)?.owner ?? null
      const rollback = await snapshot(queryClient, IDEA_CACHES)
      patchIdea(queryClient, idea, () => ({ owner }))
      return { rollback, previous }
    },
    onError: (_error, _vars, context) => context?.rollback(),
    onSuccess: (data, vars, context) => {
      settleIdea(queryClient, idea, data)
      if (!undo || vars.isUndo) return
      const previous = context.previous
      const self = me(queryClient)
      const steppedDown = vars.owner === null && previous?.id === self?.id
      if (steppedDown) {
        if (data.permissions.can_volunteer) {
          offerUndo(`You stepped down as owner of ${data.key}`, () =>
            volunteer.mutate({ isUndo: true }),
          )
        }
        return
      }
      offerUndo(
        vars.owner ? `${vars.owner.display_name} now owns ${data.key}` : `${data.key} has no owner`,
        () => mutation.mutate({ owner: previous, isUndo: true }),
      )
    },
    meta: { errorTitle: 'Couldn’t change the owner' },
  })
  return mutation
}

/** "I'll own this". Undo steps down again (`set_idea_owner {user_id: null}`). */
export function useVolunteerAsOwner(idea: string, { undo = true }: UndoOption = {}) {
  const queryClient = useQueryClient()
  const stepDown = useMutation({
    mutationFn: () =>
      unwrap(api.PUT('/api/v1/ideas/{idea}/owner', { ...path(idea), body: { user_id: null } })),
    onSuccess: (data) => settleIdea(queryClient, idea, data),
    meta: { errorTitle: 'Couldn’t undo that' },
  })
  return useMutation({
    mutationFn: (_vars: Undoable<object>) =>
      unwrap(api.POST('/api/v1/ideas/{idea}/volunteer', path(idea))),
    onMutate: async () => {
      const rollback = await snapshot(queryClient, IDEA_CACHES)
      const self = me(queryClient)
      if (self) patchIdea(queryClient, idea, () => ({ owner: self }))
      return { rollback }
    },
    onError: (_error, _vars, context) => context?.rollback(),
    onSuccess: (data, vars) => {
      settleIdea(queryClient, idea, data)
      if (undo && !vars.isUndo) {
        offerUndo(`You now own ${data.key}`, () => stepDown.mutate())
      }
    },
    meta: { errorTitle: 'Couldn’t take ownership' },
  })
}

/* ------------------------------------------------------------------ */
/* Evaluators and the evaluation window                                */
/* ------------------------------------------------------------------ */

/** Invite evaluators (optimistic rows in the sidebar). The first invite sets the default due date. */
export function useAddEvaluators(idea: string) {
  const queryClient = useQueryClient()
  const mutation = useMutation({
    mutationFn: ({
      users,
      dueAt,
      ...override
    }: { users: UserRef[]; dueAt?: string | null } & ResearchOverride) =>
      unwrap(
        api.POST('/api/v1/ideas/{idea}/evaluators', {
          ...path(idea),
          body: {
            user_ids: users.map((user) => user.id),
            ...(dueAt !== undefined && { due_at: dueAt }),
            ...overrideBody(override),
          },
        }),
      ),
    onMutate: async ({ users }) => {
      const rollback = await snapshot(queryClient, IDEA_CACHES)
      const now = new Date().toISOString()
      patchIdeaDetail(queryClient, idea, (detail) => {
        const added = users
          .filter((user) => !detail.evaluators.some((e) => e.user.id === user.id))
          .map((user) => ({
            user,
            invited_at: now,
            is_ai: false,
            state: 'invited' as const,
            submitted_at: null,
          }))
        return {
          evaluators: [...detail.evaluators, ...added],
          evaluator_progress: {
            ...detail.evaluator_progress,
            total: detail.evaluator_progress.total + added.length,
          },
        }
      })
      return { rollback }
    },
    onError: (error, vars, context) => {
      context?.rollback()
      // Phase 8: the first evaluator starts evaluation, which the research step guards.
      openResearchGate(error, {
        ideaKey: idea,
        action: 'invite',
        retry: (override) => mutation.mutate({ ...vars, ...override }),
      })
    },
    onSuccess: (data) => settleIdea(queryClient, idea, data),
    meta: { errorTitle: 'Couldn’t invite evaluators' },
  })
  return mutation
}

/**
 * Remove an evaluator — deferred (contract §3.14): the row disappears at once,
 * the DELETE is sent when the Undo toast closes, Undo brings the row back.
 * Offer it only on rows of *other* evaluators who haven't submitted.
 */
export function useRemoveEvaluator(idea: string) {
  const queryClient = useQueryClient()
  return useCallback(
    (evaluator: UserRef) => {
      const detail = queryClient.getQueryData<IdeaDetail>(queryKeys.ideas.detail(idea))
      if (!detail) return
      const key = hiddenKey.evaluator(detail.id, evaluator.id)
      deferUntilToastCloses({
        title: `${evaluator.display_name} removed as evaluator`,
        hide: () => hideItem(key),
        restore: () => unhideItem(key),
        commit: async ({ keepalive }) => {
          const data = await unwrap(
            api.DELETE('/api/v1/ideas/{idea}/evaluators/{user_id}', {
              params: { path: { idea, user_id: evaluator.id } },
              keepalive,
            }),
          )
          settleIdea(queryClient, idea, data)
          unhideItem(key)
        },
        errorTitle: `Couldn’t remove ${evaluator.display_name}`,
      })
    },
    [queryClient, idea],
  )
}

/** Set or clear (`null`) the evaluation due date. */
export function useSetEvaluationDueDate(idea: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (dueAt: string | null) =>
      unwrap(
        api.PUT('/api/v1/ideas/{idea}/evaluation/due-date', {
          ...path(idea),
          body: { due_at: dueAt },
        }),
      ),
    onMutate: async (dueAt) => {
      const rollback = await snapshot(queryClient, IDEA_CACHES)
      patchIdeaDetail(queryClient, idea, () => ({ evaluation_due_at: dueAt }))
      return { rollback }
    },
    onError: (_error, _vars, context) => context?.rollback(),
    onSuccess: (data) => settleIdea(queryClient, idea, data),
    meta: { errorTitle: 'Couldn’t change the due date' },
  })
}

/** Close (`closed: true`) or reopen evaluation; Undo makes the other call. */
export function useSetEvaluationClosed(idea: string, { undo = true }: UndoOption = {}) {
  const queryClient = useQueryClient()
  const mutation = useMutation({
    mutationFn: ({ closed }: Undoable<{ closed: boolean }>) =>
      unwrap(
        closed
          ? api.POST('/api/v1/ideas/{idea}/evaluation/close', path(idea))
          : api.POST('/api/v1/ideas/{idea}/evaluation/reopen', path(idea)),
      ),
    onMutate: async ({ closed }) => {
      const rollback = await snapshot(queryClient, IDEA_CACHES)
      patchIdeaDetail(queryClient, idea, (detail) => ({
        evaluation_closed_at: closed ? new Date().toISOString() : null,
        evaluation_open: !closed && detail.status !== 'closed',
      }))
      return { rollback }
    },
    onError: (_error, _vars, context) => context?.rollback(),
    onSuccess: (data, vars) => {
      settleIdea(queryClient, idea, data)
      void queryClient.invalidateQueries({ queryKey: queryKeys.evaluations.idea(idea) })
      if (undo && !vars.isUndo) {
        offerUndo(vars.closed ? 'Evaluation closed' : 'Evaluation reopened', () =>
          mutation.mutate({ closed: !vars.closed, isUndo: true }),
        )
      }
    },
    meta: { errorTitle: 'Couldn’t change the evaluation' },
  })
  return mutation
}

/* ------------------------------------------------------------------ */
/* Votes and watching (toggles: the next click is the undo)            */
/* ------------------------------------------------------------------ */

export function useVoteIdea(idea: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ vote }: { vote: boolean }) =>
      unwrap(
        vote
          ? api.PUT('/api/v1/ideas/{idea}/vote', path(idea))
          : api.DELETE('/api/v1/ideas/{idea}/vote', path(idea)),
      ),
    onMutate: async ({ vote }) => {
      const rollback = await snapshot(queryClient, IDEA_CACHES)
      patchIdea(queryClient, idea, (current) =>
        current.has_voted === vote
          ? {}
          : { has_voted: vote, vote_count: Math.max(0, current.vote_count + (vote ? 1 : -1)) },
      )
      return { rollback }
    },
    onError: (_error, _vars, context) => context?.rollback(),
    onSuccess: (state) => patchIdea(queryClient, idea, () => state),
    onSettled: () => {
      // Lists sorted by votes may reorder; refetch when next shown.
      void queryClient.invalidateQueries({ queryKey: queryKeys.ideas.lists(), refetchType: 'none' })
    },
    meta: { errorTitle: 'Couldn’t save your vote' },
  })
}

export function useWatchIdea(idea: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ watch }: { watch: boolean }) =>
      unwrap(
        watch
          ? api.PUT('/api/v1/ideas/{idea}/watch', path(idea))
          : api.DELETE('/api/v1/ideas/{idea}/watch', path(idea)),
      ),
    onMutate: async ({ watch }) => {
      const rollback = await snapshot(queryClient, [queryKeys.ideas.detail(idea)])
      patchIdeaDetail(queryClient, idea, () => ({ watching: watch }))
      return { rollback }
    },
    onError: (_error, _vars, context) => context?.rollback(),
    onSuccess: (state) => patchIdeaDetail(queryClient, idea, () => state),
    meta: { errorTitle: 'Couldn’t change watching' },
  })
}
