import { queryOptions, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, unwrap } from '@/api/client'
import { queryKeys } from '@/api/keys'
import type { MyEvaluationIn } from '@/api/types'

/**
 * Submitted evaluations of an idea. For a pending evaluator the API answers
 * `{ items: [], score_hidden: true }` — show "Hidden until you submit".
 */
export const evaluationsQueryOptions = (idea: string) =>
  queryOptions({
    queryKey: queryKeys.evaluations.list(idea),
    queryFn: ({ signal }) =>
      unwrap(api.GET('/api/v1/ideas/{idea}/evaluations', { params: { path: { idea } }, signal })),
  })

export function useEvaluations(idea: string, options: { enabled?: boolean } = {}) {
  return useQuery({ ...evaluationsQueryOptions(idea), enabled: options.enabled ?? true })
}

/** Your own evaluation (the evaluate sheet); `null` when you aren't an evaluator. */
export const myEvaluationQueryOptions = (idea: string) =>
  queryOptions({
    queryKey: queryKeys.evaluations.mine(idea),
    queryFn: ({ signal }) =>
      unwrap(
        api.GET('/api/v1/ideas/{idea}/evaluations/me', { params: { path: { idea } }, signal }),
      ),
  })

export function useMyEvaluation(idea: string, options: { enabled?: boolean } = {}) {
  return useQuery({ ...myEvaluationQueryOptions(idea), enabled: options.enabled ?? true })
}

/**
 * Save a draft (`submit: false`) or submit (`submit: true`). Not optimistic:
 * a submit can fail validation (422 `evaluation_incomplete` lists the gaps in
 * `error.problem.errors`), so the sheet shows errors inline (no toast).
 * Submitting reveals the scores: the idea, evaluations, lists and My work refetch.
 */
export function useSaveMyEvaluation(idea: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: MyEvaluationIn) =>
      unwrap(api.PUT('/api/v1/ideas/{idea}/evaluations/me', { params: { path: { idea } }, body })),
    onSuccess: (evaluation, body) => {
      queryClient.setQueryData(queryKeys.evaluations.mine(idea), evaluation)
      if (!body.submit) return
      void queryClient.invalidateQueries({ queryKey: queryKeys.evaluations.list(idea) })
      void queryClient.invalidateQueries({ queryKey: queryKeys.ideas.all })
      void queryClient.invalidateQueries({ queryKey: queryKeys.activity.idea(idea) })
      void queryClient.invalidateQueries({ queryKey: queryKeys.work.all })
    },
    meta: { silent: true },
  })
}
