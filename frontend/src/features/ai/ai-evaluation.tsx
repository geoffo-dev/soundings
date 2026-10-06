import { useId } from 'react'

import { useSetEvaluationInclusion } from '@/api/ai'
import type { Evaluation } from '@/api/types'
import { offerUndo } from '@/api/undo'
import { Switch } from '@/components/ui/switch'
import { WithTooltip } from '@/components/ui/tooltip'

import { BLOCKED_COPY } from './ai-copy'
import { useIdeaAi } from './idea-ai'

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
      disabled={!canToggle || setInclusion.isPending}
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
