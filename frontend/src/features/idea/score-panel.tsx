import { Lock, TriangleAlert } from 'lucide-react'
import { useEffect, useId, useState, type ReactNode } from 'react'

import type { AggregateScore, IdeaDetail } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { ScoreBar } from '@/components/ui/score-bar'
import { AiNotCounted } from '@/features/ai/ai-evaluation'
import { formatScore } from '@/lib/scores'
import { cn } from '@/lib/utils'

import { RECOMMENDATION_LABELS, RECOMMENDATIONS } from './evaluation-form'
import { useIdeaPage } from './idea-context'
import { revealDelay, useReducedMotion } from './score-display'

/** Criteria where evaluators differ by 2 or more (the disagreement rule, contract §3.8). */
export function disagreedCriteria(aggregate: AggregateScore): string[] {
  return aggregate.criteria.filter((c) => c.count >= 2 && c.spread >= 2).map((c) => c.name)
}

function joinNames(names: string[]): string {
  if (names.length <= 1) return names.join('')
  return `${names.slice(0, -1).join(', ')} and ${names.at(-1) ?? ''}`
}

/**
 * True for one render after the viewer's scores stop being hidden (they just
 * submitted), so the numbers can fade in once.
 */
export function useRevealOnce(hidden: boolean): boolean {
  const [previous, setPrevious] = useState(hidden)
  const [revealing, setRevealing] = useState(false)
  if (previous !== hidden) {
    // Adjusting state while rendering (React's "previous props" pattern).
    setPrevious(hidden)
    setRevealing(previous && !hidden)
  }
  useEffect(() => {
    if (!revealing) return
    // Long enough for the staggered animation to finish, then drop the class.
    const timer = window.setTimeout(() => setRevealing(false), 1500)
    return () => window.clearTimeout(timer)
  }, [revealing])
  return revealing
}

/**
 * The sidebar's score: the aggregate with `n`, the disagreement flag and one
 * bar per criterion — or, for a pending evaluator, nothing but a lock (blind
 * evaluation: no numbers, no counts, no flag; role matrix §3).
 */
export function ScorePanel({ className }: { className?: string }) {
  const { idea, ideaKey, setTab } = useIdeaPage()
  return (
    <ScoreSummary idea={idea} className={className}>
      <AiNotCounted ideaKey={ideaKey} idea={idea} setTab={setTab} />
    </ScoreSummary>
  )
}

export function ScoreSummary({
  idea,
  className,
  children,
}: {
  idea: IdeaDetail
  className?: string
  /** Under the score (e.g. "1 AI evaluation not counted · Review"). */
  children?: ReactNode
}) {
  const reveal = useRevealOnce(idea.score_hidden)
  const headingId = useId()
  return (
    <section aria-labelledby={headingId} className={cn('flex flex-col gap-3', className)}>
      <h2 id={headingId} className="text-sm font-medium text-primary">
        Score
      </h2>
      {idea.score_hidden ? (
        <HiddenScore evaluationOpen={idea.evaluation_open} />
      ) : idea.aggregate ? (
        <AggregateView aggregate={idea.aggregate} reveal={reveal} />
      ) : (
        <p className="text-sm text-muted">
          {idea.evaluator_progress.total > 0
            ? 'Scores appear here as evaluators submit.'
            : 'No scores yet.'}
        </p>
      )}
      {children}
    </section>
  )
}

export function HiddenScore({ evaluationOpen }: { evaluationOpen: boolean }) {
  return (
    <div className="flex flex-col gap-1.5 rounded-lg bg-background px-3.5 py-3">
      <p className="flex items-center gap-2 text-sm font-medium text-primary">
        <Lock aria-hidden="true" className="size-3.5 text-muted" />
        Hidden until you submit
      </p>
      <p className="text-sm text-muted">
        {evaluationOpen
          ? 'Submit your evaluation to see scores. Others’ scores stay hidden so they don’t sway yours.'
          : 'Evaluation closed before you submitted, so scores stay hidden. The owner can remove you as an evaluator.'}
      </p>
    </div>
  )
}

export function AggregateView({
  aggregate,
  reveal = false,
  compact = false,
}: {
  aggregate: AggregateScore
  reveal?: boolean
  /** Hide the per-criterion bars (the evaluate sheet shows its own). */
  compact?: boolean
}) {
  const reduced = useReducedMotion()
  const disagreed = disagreedCriteria(aggregate)
  const { recommendations } = aggregate
  return (
    <div className="flex flex-col gap-4">
      <div className={cn('flex flex-col gap-1.5', reveal && 'animate-reveal')}>
        <p className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
          <span className="text-3xl font-semibold text-primary tabular-nums">
            {formatScore(aggregate.overall)}
          </span>
          <span className="text-sm text-muted">
            / 5 · {aggregate.count} {aggregate.count === 1 ? 'evaluation' : 'evaluations'}
          </span>
        </p>
        {aggregate.high_disagreement && (
          <div className="flex flex-col items-start gap-1">
            <Badge variant="warning">
              <TriangleAlert aria-hidden="true" />
              High disagreement
            </Badge>
            {disagreed.length > 0 && (
              <p className="text-xs text-muted">
                Scores for {joinNames(disagreed)} differ by 2 or more.
              </p>
            )}
          </div>
        )}
        <p className="flex flex-wrap gap-x-3 text-sm text-secondary tabular-nums">
          {RECOMMENDATIONS.map((value) => (
            <span key={value}>
              {RECOMMENDATION_LABELS[value]}{' '}
              <span className="font-medium text-primary">{recommendations[value]}</span>
            </span>
          ))}
        </p>
      </div>
      {!compact && (
        <div className="flex flex-col gap-3.5">
          {aggregate.criteria.map((criterion, index) => (
            <ScoreBar
              key={criterion.criterion_id}
              label={criterion.name}
              value={criterion.count > 0 ? criterion.mean : null}
              min={criterion.count > 1 ? criterion.min : undefined}
              max={criterion.count > 1 ? criterion.max : undefined}
              disagreement={criterion.count >= 2 && criterion.spread >= 2}
              inverted={criterion.inverted}
              reveal={reveal}
              style={reveal ? revealDelay(index + 1, reduced) : undefined}
            />
          ))}
        </div>
      )}
    </div>
  )
}
