import { CircleHelp, ThumbsDown, ThumbsUp } from 'lucide-react'
import { useSyncExternalStore } from 'react'

import type { Recommendation } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { SCORE_MAX, SCORE_TINT, scoreBand } from '@/lib/scores'
import { cn } from '@/lib/utils'

import { RECOMMENDATION_LABELS } from './evaluation-form'

const RECOMMENDATION_STYLE = {
  go: { variant: 'success', Icon: ThumbsUp },
  maybe: { variant: 'warning', Icon: CircleHelp },
  no: { variant: 'danger', Icon: ThumbsDown },
} as const

/** Go / Maybe / No: icon and word, never colour alone. */
export function RecommendationBadge({
  value,
  compact = false,
  className,
}: {
  value: Recommendation
  /** Icon only on phones (the word stays for screen readers), for tight tables. */
  compact?: boolean
  className?: string
}) {
  const { variant, Icon } = RECOMMENDATION_STYLE[value]
  return (
    <Badge variant={variant} className={className}>
      <Icon aria-hidden="true" />
      <span className={cn(compact && 'max-sm:sr-only')}>{RECOMMENDATION_LABELS[value]}</span>
    </Badge>
  )
}

/**
 * One evaluator's 1–5 score as a small tinted square. Inverted criteria are
 * tinted by the inverted score, so the colour always means "good" or "bad".
 */
export function ScoreChip({
  score,
  inverted = false,
  muted = false,
  label,
  className,
}: {
  score: number
  inverted?: boolean
  /**
   * Not counted in the score (an AI evaluation left out): no tint and a dashed
   * outline, so it never reads like the scores that are.
   */
  muted?: boolean
  /** Accessible name, e.g. "Value: 4 out of 5". Defaults to "4 out of 5". */
  label?: string
  className?: string
}) {
  const band = scoreBand(inverted ? SCORE_MAX + 1 - score : score)
  return (
    <span
      role="img"
      aria-label={label ?? `${score} out of 5`}
      className={cn(
        'inline-flex size-6 shrink-0 items-center justify-center rounded-md text-sm font-semibold tabular-nums',
        muted
          ? 'border border-dashed border-strong font-medium text-secondary'
          : ['text-primary', SCORE_TINT[band]],
        className,
      )}
    >
      <span aria-hidden="true">{score}</span>
    </span>
  )
}

const REDUCED_MOTION = '(prefers-reduced-motion: reduce)'

function subscribe(callback: () => void) {
  const query = window.matchMedia(REDUCED_MOTION)
  query.addEventListener('change', callback)
  return () => query.removeEventListener('change', callback)
}

/** True when the user asked for less motion (no staggered reveal then). */
export function useReducedMotion(): boolean {
  return useSyncExternalStore(
    subscribe,
    () => window.matchMedia(REDUCED_MOTION).matches,
    () => true,
  )
}

/** Inline style for the n-th item of a staggered reveal (none with reduced motion). */
export function revealDelay(index: number, reduced: boolean) {
  return reduced ? undefined : { animationDelay: `${index * 60}ms` }
}
