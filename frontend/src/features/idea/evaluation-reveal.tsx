import { TriangleAlert } from 'lucide-react'

import { useEvaluations } from '@/api/evaluations'
import type { RubricCriterion } from '@/api/types'
import { SheetBody } from '@/components/ui/sheet'
import { Skeleton, SkeletonGroup } from '@/components/ui/skeleton'
import { WithTooltip } from '@/components/ui/tooltip'
import { formatScore } from '@/lib/scores'
import { cn } from '@/lib/utils'

import type { EvaluationForm } from './evaluation-form'
import { useIdeaPage } from './idea-context'
import { RecommendationBadge, revealDelay, ScoreChip, useReducedMotion } from './score-display'
import { AggregateView } from './score-panel'

/**
 * After submitting: your scores next to everyone else's, per criterion, with
 * the server's mean and disagreement flag, then the aggregate. `animate` fades
 * the other scores in once (staggered; instant with reduced motion).
 */
export function EvaluationReveal({
  rubric,
  form,
  animate,
}: {
  rubric: RubricCriterion[]
  form: EvaluationForm
  animate: boolean
}) {
  const { idea, ideaKey, me } = useIdeaPage()
  const evaluations = useEvaluations(ideaKey)
  const reduced = useReducedMotion()
  // The idea refetches after submitting; until then it may still say "hidden".
  const hidden = idea.score_hidden || evaluations.data?.score_hidden !== false
  const others = (evaluations.data?.items ?? []).filter(
    (evaluation) => evaluation.evaluator.id !== me.id,
  )
  const aggregate = hidden ? null : idea.aggregate
  const byCriterion = new Map(aggregate?.criteria.map((c) => [c.criterion_id, c]))

  if (hidden || evaluations.isPending) {
    return (
      <SheetBody>
        <SkeletonGroup label="Loading everyone’s scores" className="flex flex-col gap-5">
          <Skeleton className="h-9 w-40" />
          {rubric.map((criterion) => (
            <div key={criterion.id} className="flex flex-col gap-2">
              <Skeleton className="h-4 w-32" />
              <Skeleton className="h-6 w-48" />
            </div>
          ))}
        </SkeletonGroup>
      </SheetBody>
    )
  }

  let step = 0
  const next = () => (animate ? revealDelay(++step, reduced) : undefined)

  return (
    // Focusable so the scores can be scrolled from the keyboard (nothing in here takes focus).
    <SheetBody
      tabIndex={0}
      role="region"
      aria-label="Everyone’s scores"
      className="flex flex-col gap-6 pt-4 focus-visible:outline-offset-[-2px]"
    >
      {others.length === 0 && (
        <p className="rounded-md bg-background px-3 py-2 text-sm text-secondary">
          You’re the first to submit. The other evaluators’ scores appear here as they come in.
        </p>
      )}

      {aggregate && (
        <section aria-label="Aggregate score" className="rounded-lg border bg-surface p-4">
          <AggregateView aggregate={aggregate} reveal={animate} compact />
        </section>
      )}

      <section aria-labelledby="reveal-criteria-heading" className="flex flex-col">
        <h3 id="reveal-criteria-heading" className="text-sm font-medium text-muted">
          Scores by criterion
        </h3>
        <ul className="flex flex-col">
          {rubric.map((criterion) => {
            const stats = byCriterion.get(criterion.id)
            const mine = form.criteria[criterion.id]?.score ?? null
            const disagreement = stats !== undefined && stats.count >= 2 && stats.spread >= 2
            return (
              <li
                key={criterion.id}
                className="flex flex-col gap-2 border-b border-subtle py-3.5 last:border-0"
              >
                <div className="flex items-baseline gap-2">
                  <span className="min-w-0 truncate font-medium text-primary">
                    {criterion.name}
                  </span>
                  {criterion.inverted && (
                    <span className="shrink-0 text-xs text-muted">lower is better</span>
                  )}
                  {stats && stats.count > 0 && (
                    <span
                      className={cn(
                        'ml-auto flex shrink-0 items-center gap-1.5 text-sm text-secondary',
                        animate && 'animate-reveal',
                      )}
                      style={next()}
                    >
                      {disagreement && (
                        <WithTooltip
                          content={`Scores range ${stats.min}–${stats.max}: evaluators disagree`}
                        >
                          <span className="inline-flex text-warning">
                            <TriangleAlert aria-hidden="true" className="size-3.5" />
                            <span className="sr-only">High disagreement.</span>
                          </span>
                        </WithTooltip>
                      )}
                      mean
                      <span className="font-semibold text-primary tabular-nums">
                        {formatScore(stats.mean)}
                      </span>
                    </span>
                  )}
                </div>
                <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-sm">
                  <span className="flex items-center gap-2">
                    <span className="text-muted">You</span>
                    {mine === null ? (
                      <span className="text-muted">–</span>
                    ) : (
                      <ScoreChip
                        score={mine}
                        inverted={criterion.inverted}
                        label={`Your score: ${mine} out of 5`}
                      />
                    )}
                  </span>
                  <span className="flex min-w-0 flex-wrap items-center gap-2">
                    <span className="text-muted">Others</span>
                    {others.length === 0 ? (
                      <span className="text-muted">none yet</span>
                    ) : (
                      others.map((evaluation) => {
                        const score = evaluation.scores.find(
                          (s) => s.criterion_id === criterion.id,
                        )?.score
                        const name = evaluation.evaluator.display_name
                        return score === undefined ? (
                          <span key={evaluation.id} className="text-muted">
                            –
                          </span>
                        ) : (
                          <WithTooltip key={evaluation.id} content={name}>
                            <span
                              className={cn('inline-flex', animate && 'animate-reveal')}
                              style={next()}
                            >
                              <ScoreChip
                                score={score}
                                inverted={criterion.inverted}
                                label={`${name}: ${score} out of 5`}
                              />
                            </span>
                          </WithTooltip>
                        )
                      })
                    )}
                  </span>
                </div>
              </li>
            )
          })}
        </ul>
      </section>

      {form.recommendation && (
        <section aria-label="Your recommendation" className="flex flex-col gap-2 text-sm">
          <p className="flex items-center gap-2">
            <span className="text-muted">Your recommendation</span>
            <RecommendationBadge value={form.recommendation} />
          </p>
          {form.comment.trim() && (
            <p className="whitespace-pre-line text-secondary">{form.comment.trim()}</p>
          )}
        </section>
      )}
    </SheetBody>
  )
}
