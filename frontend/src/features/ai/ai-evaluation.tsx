import { Sparkles } from 'lucide-react'
import { useId } from 'react'

import { useSetEvaluationInclusion } from '@/api/ai'
import { useEvaluations } from '@/api/evaluations'
import type { Evaluation, IdeaDetail } from '@/api/types'
import { offerUndo } from '@/api/undo'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import { WithTooltip } from '@/components/ui/tooltip'
import type { IdeaTab } from '@/features/idea/idea-search'
import { focusWhenRendered } from '@/lib/focus'

import { BLOCKED_COPY } from './ai-copy'
import { evaluationCardDomId } from './dom-ids'
import { useIdeaAi } from './idea-ai'

/** The idea's submitted AI evaluations still left out of the score (none while blind). */
export function useUncountedAiEvaluations(ideaKey: string, idea: IdeaDetail): Evaluation[] {
  const submittedAi = idea.evaluators.some(
    (evaluator) => evaluator.is_ai && evaluator.state === 'submitted',
  )
  const evaluations = useEvaluations(ideaKey, { enabled: submittedAi && !idea.score_hidden })
  if (idea.score_hidden || !submittedAi) return []
  return evaluations.data?.items.filter((item) => item.is_ai && !item.include_in_aggregate) ?? []
}

/**
 * Under the score: "1 AI evaluation not counted · Review" (contract-phase6 §3.7), so
 * the number never reads as if the agent's scores were in it. Review opens the
 * Evaluations tab on that evaluation, where the owner can include it.
 */
export function AiNotCounted({
  ideaKey,
  idea,
  setTab,
}: {
  ideaKey: string
  idea: IdeaDetail
  setTab: (tab: IdeaTab) => void
}) {
  const uncounted = useUncountedAiEvaluations(ideaKey, idea)
  const first = uncounted[0]
  if (!first) return null
  const count = uncounted.length
  return (
    <p className="flex flex-wrap items-center gap-x-1.5 text-sm text-muted">
      <Sparkles aria-hidden="true" className="size-3.5 shrink-0" />
      <span>{count === 1 ? '1 AI evaluation' : `${count} AI evaluations`} not counted</span>
      <span aria-hidden="true">·</span>
      <Button
        variant="link"
        size="sm"
        className="h-auto text-sm"
        aria-label={`Review the AI ${count === 1 ? 'evaluation' : 'evaluations'} not counted in the score`}
        onClick={() => {
          setTab('evaluations')
          focusWhenRendered(() => document.getElementById(evaluationCardDomId(first.id)), {
            force: true,
            frames: 60,
          })
        }}
      >
        Review
      </Button>
    </p>
  )
}

/**
 * An AI evaluation's place in the score (contract-phase6 §3.7): left out by
 * default; the idea's owner and admins switch it in ("Include in score") or
 * out again, with Undo. A changed re-submission is left out again. Everyone
 * else reads where it stands. Shown only to people who can see evaluations
 * (pending evaluators never get here: the tab is blind for them).
 */
export function AiInclusionControl({
  ideaKey,
  evaluation,
}: {
  ideaKey: string
  evaluation: Evaluation
}) {
  const ai = useIdeaAi(ideaKey)
  const setInclusion = useSetEvaluationInclusion(ideaKey)
  const descriptionId = useId()
  const name = evaluation.evaluator.display_name
  const included = evaluation.include_in_aggregate
  const permissions = ai.permissions
  const canToggle = permissions?.can_include_ai === true
  const reason = permissions?.include_ai_blocked_by ?? null
  const explain = included
    ? 'It counts in the score like a person’s evaluation. If it re-submits with different scores, it is left out again.'
    : 'AI evaluations don’t count in the score unless the owner or an admin includes them. If it re-submits with different scores, it is left out again.'

  const change = (include: boolean) =>
    setInclusion.mutate(
      { evaluationId: evaluation.id, include },
      {
        onSuccess: () =>
          offerUndo(
            include
              ? `${name}’s evaluation now counts in the score`
              : `${name}’s evaluation is out of the score`,
            () => setInclusion.mutate({ evaluationId: evaluation.id, include: !include }),
            { description: 'The aggregate and the disagreement flag are updated.' },
          ),
      },
    )

  // Visible to everyone; the switch only to whoever may decide (never role checks here).
  if (!permissions || (reason === 'not_allowed' && !canToggle)) {
    return (
      <p className="border-b border-subtle bg-background px-4 py-2.5 text-sm text-secondary">
        {included
          ? 'Counted in the score: the owner or an admin included it.'
          : 'Not counted in the score: AI evaluations are left out unless the owner or an admin includes them.'}
      </p>
    )
  }

  const control = (
    <Switch
      checked={included}
      disabled={!canToggle}
      // Saving (or its Undo): presses wait, focus stays on the switch.
      pending={setInclusion.isPending}
      aria-describedby={descriptionId}
      aria-label={`Include ${name}’s evaluation in the score`}
      onCheckedChange={change}
    />
  )
  return (
    <div className="flex items-start gap-3 border-b border-subtle bg-background px-4 py-2.5">
      <div className="flex h-5 items-center">
        {canToggle || !reason ? (
          control
        ) : (
          <WithTooltip content={BLOCKED_COPY[reason]}>
            {/* A disabled control can't show a tooltip: the wrapper takes the hover. */}
            <span className="inline-flex">{control}</span>
          </WithTooltip>
        )}
      </div>
      <div className="flex min-w-0 flex-col gap-0.5">
        <span className="text-sm font-medium text-primary">Include in score</span>
        <p id={descriptionId} className="text-sm text-muted">
          {explain}
          {!canToggle && reason ? ` ${BLOCKED_COPY[reason]}.` : ''}
        </p>
      </div>
    </div>
  )
}
