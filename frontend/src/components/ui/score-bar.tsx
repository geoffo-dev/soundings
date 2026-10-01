import { TriangleAlert } from 'lucide-react'
import type { CSSProperties, ReactElement } from 'react'

import { WithTooltip } from '@/components/ui/tooltip'
import { formatScore, SCORE_FILL, SCORE_MAX, scoreBand } from '@/lib/scores'
import { cn } from '@/lib/utils'

export interface ScoreBarProps {
  label: string
  /** Aggregate for this criterion, 1–5; null when nobody has scored it. */
  value: number | null
  /** Lowest and highest individual scores — draws the spread marker. */
  min?: number
  max?: number
  /** Evaluators disagree strongly (e.g. spread ≥ 2). */
  disagreement?: boolean
  /**
   * A high score is bad (Effort, Risk). The value stays as entered, the label
   * says "lower is better" and the colour follows the inverted score (6 − value).
   */
  inverted?: boolean
  /** Animate in (used when blind scores are revealed). */
  reveal?: boolean
  className?: string
  style?: CSSProperties
}

const pct = (score: number) => `${(Math.min(Math.max(score, 0), SCORE_MAX) / SCORE_MAX) * 100}%`

/**
 * One rubric criterion on a 1–5 scale. An optional whisker under the bar shows
 * the lowest–highest individual score; ⚠ flags high disagreement.
 */
export function ScoreBar({
  label,
  value,
  min,
  max,
  disagreement = false,
  inverted = false,
  reveal = false,
  className,
  style,
}: ScoreBarProps) {
  const hasRange = min !== undefined && max !== undefined
  const hasSpread = hasRange && max > min
  const valueText =
    value === null
      ? 'Not scored yet'
      : `${formatScore(value)} out of 5${inverted ? ', lower is better' : ''}${hasSpread ? `, individual scores range from ${min} to ${max}` : ''}${disagreement ? ', high disagreement' : ''}`

  return (
    <div
      className={cn('flex flex-col gap-1.5', reveal && 'animate-reveal', className)}
      style={style}
    >
      <div className="flex items-center gap-2 text-sm">
        <span className="min-w-0 truncate text-secondary">{label}</span>
        {inverted && (
          <span aria-hidden="true" className="shrink-0 text-xs text-muted">
            lower is better
          </span>
        )}
        {disagreement && (
          <WithTooltip
            content={
              hasSpread ? `High disagreement: scores range ${min}–${max}` : 'High disagreement'
            }
          >
            <span className="inline-flex text-warning">
              <TriangleAlert aria-hidden="true" className="size-3.5" />
            </span>
          </WithTooltip>
        )}
        <span className="ml-auto font-medium text-primary tabular-nums">{formatScore(value)}</span>
      </div>
      {/* Hover the bar for what the whisker under it means (screen readers get it in
          the meter's value text). */}
      <ScoreRangeTooltip min={min} max={max}>
        <div className="flex flex-col gap-1.5">
          <div
            role="meter"
            aria-label={label}
            aria-valuemin={0}
            aria-valuemax={SCORE_MAX}
            aria-valuenow={value ?? 0}
            aria-valuetext={valueText}
            className="h-1.5 overflow-hidden rounded-full bg-subtle-hover"
          >
            {value !== null && (
              <div
                className={cn(
                  'h-full rounded-full',
                  SCORE_FILL[scoreBand(inverted ? SCORE_MAX + 1 - value : value)],
                )}
                style={{ width: pct(value) }}
              />
            )}
          </div>
          {hasRange && (
            // Range whisker: lowest to highest individual score (a single tick when all agree).
            <div aria-hidden="true" className="relative -mt-0.5 h-1.5">
              {hasSpread && (
                <span
                  className="absolute top-1/2 h-px -translate-y-1/2 bg-control"
                  style={{ left: pct(min), width: `calc(${pct(max)} - ${pct(min)})` }}
                />
              )}
              <span className="absolute inset-y-0 w-px bg-control" style={{ left: pct(min) }} />
              <span
                className="absolute inset-y-0 w-px -translate-x-full bg-control"
                style={{ left: pct(max) }}
              />
            </div>
          )}
        </div>
      </ScoreRangeTooltip>
    </div>
  )
}

function ScoreRangeTooltip({
  min,
  max,
  children,
}: {
  min?: number
  max?: number
  children: ReactElement
}) {
  if (min === undefined || max === undefined) return children
  return (
    <WithTooltip
      content={max > min ? `Individual scores ${min}–${max}` : `Every score was ${min}`}
      side="bottom"
    >
      {children}
    </WithTooltip>
  )
}
