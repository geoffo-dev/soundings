/**
 * Phase 8 (contract-phase8): the project's proposal template and research
 * settings, each idea's research checklist and "Similar ideas", and the research
 * gate's dialog store.
 *
 *   useProposalTemplate(slug) · useReplaceProposalTemplate(slug)    Project settings → Proposal
 *   useResearchSettings(slug) · useReplaceResearchSettings(slug)    Project settings → Research
 *   useIdeaResearch(key) · useAnswerResearchItem(key) · useClearResearchItem(key)
 *   useSimilarIdeas(key, { enabled })
 *   openResearchGate(…) / useResearchGate()   the 409 `research_incomplete` dialog
 *
 * The guarded requests (status change, first evaluator, "Ask AI to evaluate", "Start
 * proposal") open the gate dialog from their own hooks; the query client shows no
 * toast for `research_incomplete` (`query.ts`).
 */
import { queryOptions, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSyncExternalStore } from 'react'

import { patchIdea } from '@/api/cache'
import { api, unwrap } from '@/api/client'
import { hasErrorCode } from '@/api/errors'
import { queryKeys } from '@/api/keys'
import type {
  IdeaResearch,
  ProposalTemplate,
  ProposalTemplateUpdate,
  ResearchIncompleteProblem,
  ResearchOpenItem,
  ResearchOverride,
  ResearchSettings,
  ResearchSettingsUpdate,
} from '@/api/types'

/* ------------------------------------------------------------------ */
/* Project settings                                                    */
/* ------------------------------------------------------------------ */

export const proposalTemplateQueryOptions = (slug: string) =>
  queryOptions({
    queryKey: queryKeys.projects.proposalTemplate(slug),
    queryFn: ({ signal }) =>
      unwrap(
        api.GET('/api/v1/projects/{slug}/proposal-template', {
          params: { path: { slug } },
          signal,
        }),
      ),
  })

export function useProposalTemplate(slug: string) {
  return useQuery(proposalTemplateQueryOptions(slug))
}

/** Saving replaces the whole template; field errors (422) are left to the form. */
export function useReplaceProposalTemplate(slug: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: ProposalTemplateUpdate) =>
      unwrap(
        api.PUT('/api/v1/projects/{slug}/proposal-template', { params: { path: { slug } }, body }),
      ),
    onSuccess: (template) => {
      queryClient.setQueryData<ProposalTemplate>(
        queryKeys.projects.proposalTemplate(slug),
        template,
      )
      // Every proposal of the project follows the template at once.
      void queryClient.invalidateQueries({ queryKey: queryKeys.proposals.all })
    },
    meta: { silent: true },
  })
}

export const researchSettingsQueryOptions = (slug: string) =>
  queryOptions({
    queryKey: queryKeys.projects.research(slug),
    queryFn: ({ signal }) =>
      unwrap(api.GET('/api/v1/projects/{slug}/research', { params: { path: { slug } }, signal })),
  })

export function useResearchSettings(slug: string) {
  return useQuery(researchSettingsQueryOptions(slug))
}

/** The step and the checklist in one save (409 `ideas_in_research`, 422s: inline). */
export function useReplaceResearchSettings(slug: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: ResearchSettingsUpdate) =>
      unwrap(api.PUT('/api/v1/projects/{slug}/research', { params: { path: { slug } }, body })),
    onSuccess: (settings) => {
      queryClient.setQueryData<ResearchSettings>(queryKeys.projects.research(slug), settings)
      // The lifecycle (board columns, status menu, cards' progress) follows the step.
      void queryClient.invalidateQueries({ queryKey: queryKeys.projects.all })
      void queryClient.invalidateQueries({ queryKey: queryKeys.ideas.all })
      void queryClient.invalidateQueries({ queryKey: queryKeys.research.all })
      void queryClient.invalidateQueries({ queryKey: queryKeys.work.all })
      void queryClient.invalidateQueries({ queryKey: queryKeys.proposals.all })
      void queryClient.invalidateQueries({ queryKey: queryKeys.ai.all })
    },
    meta: { silent: true },
  })
}

/* ------------------------------------------------------------------ */
/* An idea's research                                                  */
/* ------------------------------------------------------------------ */

export const ideaResearchQueryOptions = (idea: string) =>
  queryOptions({
    queryKey: queryKeys.research.checklist(idea),
    queryFn: ({ signal }) =>
      unwrap(api.GET('/api/v1/ideas/{idea}/research', { params: { path: { idea } }, signal })),
  })

export function useIdeaResearch(idea: string, { enabled = true }: { enabled?: boolean } = {}) {
  return useQuery({ ...ideaResearchQueryOptions(idea), enabled })
}

/** After an answer or a clear: the panel, the cards' "2/3", and what the gate changes. */
function settleResearch(
  queryClient: ReturnType<typeof useQueryClient>,
  idea: string,
  research: IdeaResearch,
) {
  queryClient.setQueryData(queryKeys.research.checklist(idea), research)
  patchIdea(queryClient, idea, (current) =>
    current.research ? { research: research.progress } : {},
  )
  // invite_blocked_by_research, start_blocked_by_research and the AI menu's reason.
  void queryClient.invalidateQueries({ queryKey: queryKeys.ideas.detail(idea) })
  void queryClient.invalidateQueries({ queryKey: queryKeys.proposals.view(idea) })
  void queryClient.invalidateQueries({ queryKey: queryKeys.ai.runs(idea) })
}

/** Answer (or change the answer to) one item; the panel shows errors inline. */
export function useAnswerResearchItem(idea: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ itemId, answer }: { itemId: string; answer: string }) =>
      unwrap(
        api.PUT('/api/v1/ideas/{idea}/research/items/{item_id}', {
          params: { path: { idea, item_id: itemId } },
          body: { answer },
        }),
      ),
    onSuccess: (research) => settleResearch(queryClient, idea, research),
    meta: { silent: true },
  })
}

export function useClearResearchItem(idea: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ itemId }: { itemId: string }) =>
      unwrap(
        api.DELETE('/api/v1/ideas/{idea}/research/items/{item_id}', {
          params: { path: { idea, item_id: itemId } },
        }),
      ),
    onSuccess: (research) => settleResearch(queryClient, idea, research),
    meta: { errorTitle: 'Couldn’t clear the answer' },
  })
}

export const similarIdeasQueryOptions = (idea: string) =>
  queryOptions({
    queryKey: queryKeys.research.similar(idea),
    queryFn: ({ signal }) =>
      unwrap(api.GET('/api/v1/ideas/{idea}/similar-ideas', { params: { path: { idea } }, signal })),
    staleTime: 5 * 60_000,
  })

export function useSimilarIdeas(idea: string, { enabled = true }: { enabled?: boolean } = {}) {
  return useQuery({ ...similarIdeasQueryOptions(idea), enabled })
}

/* ------------------------------------------------------------------ */
/* The gate (contract-phase8 §3.5): 409 research_incomplete            */
/* ------------------------------------------------------------------ */

/** What the refused request was doing, for the dialog's words. */
export type GateAction = 'move' | 'invite' | 'evaluate' | 'proposal'

export interface ResearchGate {
  ideaKey: string
  action: GateAction
  /** The status it would have moved to ("Evaluating"), when it is a move. */
  targetLabel?: string
  openItems: ResearchOpenItem[]
  canOverride: boolean
  /** Sends the same request again with `override_research: true` (and the reason). */
  retry: (override: Required<ResearchOverride>) => void
  /**
   * Where focus goes when the dialog closes without leaving the page, when the control
   * that asked is gone or moved (a board card that snapped back to its column).
   */
  returnFocus?: () => HTMLElement | null
}

/** The 409's body when a guarded request was refused for open research items. */
export function researchIncomplete(error: unknown): ResearchIncompleteProblem | null {
  if (!hasErrorCode(error, 'research_incomplete')) return null
  return (error.problem ?? { code: 'research_incomplete' }) as ResearchIncompleteProblem
}

let gate: ResearchGate | null = null
const listeners = new Set<() => void>()

function setGate(next: ResearchGate | null) {
  gate = next
  listeners.forEach((listener) => listener())
}

/** Opens the "Finish the research first" dialog (mounted once in the signed-in layout). */
export function openResearchGate(
  error: unknown,
  request: Omit<ResearchGate, 'openItems' | 'canOverride'>,
): boolean {
  const problem = researchIncomplete(error)
  if (!problem) return false
  setGate({
    ...request,
    openItems: problem.open_items ?? [],
    canOverride: problem.can_override === true,
  })
  return true
}

export function closeResearchGate(): void {
  setGate(null)
}

export function useResearchGate(): ResearchGate | null {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener)
      return () => listeners.delete(listener)
    },
    () => gate,
    () => null,
  )
}

/** `{ override_research, override_reason }` for a request body, or nothing. */
export function overrideBody(override?: ResearchOverride | null): ResearchOverride {
  if (!override?.override_research) return {}
  return {
    override_research: true,
    ...(override.override_reason ? { override_reason: override.override_reason } : {}),
  }
}
