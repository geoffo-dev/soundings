/**
 * AI assistance on an idea (contract-phase6 §2 "AI runs, the include toggle and
 * research notes"). Runs and their events hold no score data (blind-safe for
 * everyone who may view the idea); agent text never reaches them.
 *
 *   useIdeaAiRuns(key)              newest runs, the agents you may ask (c10), permissions
 *   useAiRun(key, runId, options)   one run with its events: the polling fallback of the stream
 *   useRequestAiRun(key)            ask an agent: `{ run, existing }` (201 new, 200 the active one)
 *   useCancelAiRun(key)             cancel (queued: at once; running: the worker stops it)
 *   useSetEvaluationInclusion(key)  count an AI evaluation in the score, or leave it out (optimistic)
 *   useDeleteResearchNote(key)      clears a research note (confirm first: no undo)
 *   runFinished(queryClient, key, run)  what to refetch when a run ends (by kind)
 *
 * The live progress stream itself is `api/ai-stream.ts`.
 */
import {
  queryOptions,
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from '@tanstack/react-query'

import { api, unwrap } from '@/api/client'
import { queryKeys } from '@/api/keys'
import type {
  AiRun,
  AiRunDetail,
  AiRunKind,
  AiRunList,
  Evaluation,
  EvaluationList,
  ProposalSectionKey,
} from '@/api/types'

export const ideaAiRunsQueryOptions = (idea: string) =>
  queryOptions({
    queryKey: queryKeys.ai.runs(idea),
    queryFn: ({ signal }) =>
      unwrap(
        api.GET('/api/v1/ideas/{idea}/ai-runs', {
          params: { path: { idea }, query: { limit: 20 } },
          signal,
        }),
      ),
    staleTime: 30_000,
  })

/** The idea's runs, newest first, with `agents` (who may be asked now) and `permissions`. */
export function useIdeaAiRuns(idea: string, options: { enabled?: boolean } = {}) {
  return useQuery({ ...ideaAiRunsQueryOptions(idea), enabled: options.enabled ?? true })
}

export const aiRunQueryOptions = (idea: string, runId: string) =>
  queryOptions({
    queryKey: queryKeys.ai.run(idea, runId),
    queryFn: ({ signal }) =>
      unwrap(
        api.GET('/api/v1/ideas/{idea}/ai-runs/{run_id}', {
          params: { path: { idea, run_id: runId } },
          signal,
        }),
      ),
  })

/**
 * One run with its events. `poll` refetches every 2.5 s while the run is
 * active (the stream's fallback); `enabled: false` while the stream feeds it.
 */
export function useAiRun(
  idea: string,
  runId: string,
  options: { enabled?: boolean; poll?: boolean } = {},
) {
  return useQuery({
    ...aiRunQueryOptions(idea, runId),
    enabled: options.enabled ?? true,
    refetchInterval: (query) =>
      options.poll && (!query.state.data || isActive(query.state.data)) ? 2500 : false,
  })
}

const isActive = (run: Pick<AiRun, 'status'>) => run.status === 'queued' || run.status === 'running'

/** Puts a run into the idea's list (newest first), replacing an older copy of it. */
export function storeRun(queryClient: QueryClient, idea: string, run: AiRun) {
  queryClient.setQueryData<AiRunList>(queryKeys.ai.runs(idea), (list) =>
    list ? { ...list, items: [run, ...list.items.filter((item) => item.id !== run.id)] } : list,
  )
  queryClient.setQueryData<AiRunDetail>(queryKeys.ai.run(idea, run.id), (detail) =>
    detail ? { ...detail, ...run } : { ...run, events: [] },
  )
}

/**
 * A run ended: refetch it, the list and what its result changed (the AI
 * evaluator's row and the evaluations; the feed's research note; the
 * proposal's suggestions). A run that assigned its agent and ended without an
 * evaluation took the assignment back, so the idea is refetched for every
 * evaluate run.
 */
export function runFinished(
  queryClient: QueryClient,
  idea: string,
  run: Pick<AiRun, 'id' | 'kind'>,
): void {
  void queryClient.invalidateQueries({ queryKey: queryKeys.ai.runs(idea) })
  void queryClient.invalidateQueries({ queryKey: queryKeys.ai.run(idea, run.id) })
  void queryClient.invalidateQueries({ queryKey: queryKeys.activity.idea(idea) })
  // Admin settings → AI agents: the agent's active runs and its key's "Used …".
  void queryClient.invalidateQueries({ queryKey: queryKeys.admin.aiAgents() })
  if (run.kind === 'evaluate') {
    void queryClient.invalidateQueries({ queryKey: queryKeys.ideas.detail(idea) })
    void queryClient.invalidateQueries({ queryKey: queryKeys.evaluations.list(idea) })
    void queryClient.invalidateQueries({ queryKey: queryKeys.work.all })
  }
  if (run.kind === 'draft_section') {
    void queryClient.invalidateQueries({ queryKey: queryKeys.proposals.suggestions(idea) })
  }
}

export interface AiRunAsk {
  kind: AiRunKind
  agentId: string
  /** draft_section only. */
  sectionKey?: ProposalSectionKey
}

/**
 * Asks an agent. Idempotent: while the same run (idea, agent, kind, section)
 * is active the API answers 200 with it (`existing: true`), else 201.
 * "Ask AI to evaluate" also makes the agent an evaluator: the idea refetches.
 */
export function useRequestAiRun(idea: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ kind, agentId, sectionKey }: AiRunAsk) => {
      const params = { path: { idea } }
      const result =
        kind === 'evaluate'
          ? await api.POST('/api/v1/ideas/{idea}/ai-runs/evaluation', {
              params,
              body: { agent_id: agentId },
            })
          : kind === 'research'
            ? await api.POST('/api/v1/ideas/{idea}/ai-runs/research', {
                params,
                body: { agent_id: agentId },
              })
            : await api.POST('/api/v1/ideas/{idea}/ai-runs/section-draft', {
                params,
                body: { agent_id: agentId, section_key: sectionKey ?? 'summary' },
              })
      return { run: result.data as AiRun, existing: result.response.status === 200 }
    },
    onSuccess: ({ run }) => {
      storeRun(queryClient, idea, run)
      void queryClient.invalidateQueries({ queryKey: queryKeys.ai.runs(idea) })
      void queryClient.invalidateQueries({ queryKey: queryKeys.admin.aiAgents() })
      if (run.kind === 'evaluate') {
        void queryClient.invalidateQueries({ queryKey: queryKeys.ideas.detail(idea) })
        void queryClient.invalidateQueries({ queryKey: queryKeys.activity.idea(idea) })
      }
    },
    meta: { errorTitle: 'Couldn’t ask the AI agent' },
  })
}

export function useCancelAiRun(idea: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (runId: string) =>
      unwrap(
        api.POST('/api/v1/ideas/{idea}/ai-runs/{run_id}/cancel', {
          params: { path: { idea, run_id: runId } },
        }),
      ),
    onSuccess: (run) => {
      storeRun(queryClient, idea, run)
      if (!isActive(run)) runFinished(queryClient, idea, run)
    },
    onError: (_error, runId) => {
      // Most likely it ended meanwhile (409 ai_run_finished): show what happened.
      void queryClient.invalidateQueries({ queryKey: queryKeys.ai.runs(idea) })
      void queryClient.invalidateQueries({ queryKey: queryKeys.ai.run(idea, runId) })
    },
    meta: { errorTitle: 'Couldn’t cancel the run' },
  })
}

/**
 * Counts an AI evaluation in the score (`include: true`) or leaves it out.
 * The evaluations list changes at once; the idea (aggregate, n, disagreement)
 * and lists (score) refetch after.
 */
export function useSetEvaluationInclusion(idea: string) {
  const queryClient = useQueryClient()
  const key = queryKeys.evaluations.list(idea)
  const patch = (evaluationId: string, change: (item: Evaluation) => Evaluation) =>
    queryClient.setQueryData<EvaluationList>(key, (list) =>
      list
        ? {
            ...list,
            items: list.items.map((item) => (item.id === evaluationId ? change(item) : item)),
          }
        : list,
    )
  return useMutation({
    mutationFn: ({ evaluationId, include }: { evaluationId: string; include: boolean }) =>
      unwrap(
        api.PUT('/api/v1/ideas/{idea}/evaluations/{evaluation_id}/include-in-aggregate', {
          params: { path: { idea, evaluation_id: evaluationId } },
          body: { include },
        }),
      ),
    onMutate: async ({ evaluationId, include }) => {
      await queryClient.cancelQueries({ queryKey: key })
      const before = queryClient.getQueryData<EvaluationList>(key)
      patch(evaluationId, (item) => ({ ...item, include_in_aggregate: include }))
      return { before }
    },
    onError: (_error, _variables, context) => {
      if (context?.before) queryClient.setQueryData(key, context.before)
    },
    onSuccess: (evaluation) => patch(evaluation.id, () => evaluation),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: key })
      void queryClient.invalidateQueries({ queryKey: queryKeys.ideas.all })
      void queryClient.invalidateQueries({ queryKey: queryKeys.work.all })
    },
    meta: { errorTitle: 'Couldn’t change what counts in the score' },
  })
}

/** Clears a research note's text and sources (the feed keeps "wrote a research note, since deleted"). */
export function useDeleteResearchNote(idea: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (noteId: string) =>
      api.DELETE('/api/v1/ideas/{idea}/research-notes/{note_id}', {
        params: { path: { idea, note_id: noteId } },
      }),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.activity.idea(idea) })
    },
    meta: { errorTitle: 'Couldn’t delete the research note' },
  })
}
