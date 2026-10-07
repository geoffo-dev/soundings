import { Lock } from 'lucide-react'

import { HoverTooltip } from '@/components/ui/tooltip'
import { formatScore, SCORE_FILL, SCORE_TINT, scoreBand } from '@/lib/scores'
import { cn } from '@/lib/utils'

export interface ScoreBadgeProps {
  /** Aggregate 1–5, or null when there are no submitted evaluations. */
  score: number | null | undefined
  /** Blind evaluation: the viewer hasn't submitted yet, so scores are hidden. */
  hidden?: boolean
  /** Number of evaluations behind the aggregate. */
  count?: number
  size?: 'sm' | 'md'
  className?: string
}

export function ScoreBadge({
  score,
  hidden = false,
  count,
  size = 'md',
  className,
}: ScoreBadgeProps) {
  const base = cn(
    'inline-flex shrink-0 items-center gap-1.5 rounded-md font-semibold tabular-nums',
    size === 'sm' ? 'h-5 px-1.5 text-xs' : 'h-6 px-2 text-sm',
    className,
  )

  if (hidden) {
    return (
      <HoverTooltip content="Submit your evaluation to see scores">
        <span
          role="img"
          aria-label="Scores hidden until you submit your evaluation"
          className={cn(base, 'bg-subtle text-muted')}
        >
          <Lock aria-hidden="true" className="size-3.5" />
        </span>
      </HoverTooltip>
    )
  }

  if (score === null || score === undefined) {
    return (
      <span
        role="img"
        aria-label="No score yet"
        className={cn(base, 'bg-subtle font-medium text-muted')}
      >
        –
      </span>
    )
  }

  const band = scoreBand(score)
  const label = `Score ${formatScore(score)} out of 5${count !== undefined ? ` from ${count} evaluation${count === 1 ? '' : 's'}` : ''}`
  return (
    <span role="img" aria-label={label} className={cn(base, SCORE_TINT[band], 'text-primary')}>
      <span aria-hidden="true" className={cn('size-1.5 rounded-full', SCORE_FILL[band])} />
      <span aria-hidden="true">{formatScore(score)}</span>
      {count !== undefined && (
        <span aria-hidden="true" className="font-normal text-secondary">
          · {count}
        </span>
      )}
    </span>
  )
}
