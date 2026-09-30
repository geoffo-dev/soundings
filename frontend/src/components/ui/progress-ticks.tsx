import { cn } from '@/lib/utils'

export interface ProgressTicksProps {
  done: number
  total: number
  /** Accessible noun, e.g. "evaluations submitted". */
  noun?: string
  showLabel?: boolean
  className?: string
}

const MAX_TICKS = 8

/** Evaluator progress as ●●●○ 3/4. Turns green when complete. */
export function ProgressTicks({
  done,
  total,
  noun = 'evaluations submitted',
  showLabel = true,
  className,
}: ProgressTicksProps) {
  const complete = total > 0 && done >= total
  const clamped = Math.min(done, total)
  return (
    <span
      role="img"
      aria-label={`${clamped} of ${total} ${noun}`}
      className={cn('inline-flex items-center gap-2', className)}
    >
      {total <= MAX_TICKS ? (
        <span aria-hidden="true" className="inline-flex items-center gap-1">
          {Array.from({ length: total }, (_, i) => (
            <span
              key={i}
              className={cn(
                'size-1.5 rounded-full',
                i < clamped
                  ? complete
                    ? 'bg-success'
                    : 'bg-control'
                  : 'shadow-[inset_0_0_0_1px_var(--border-control)]',
              )}
            />
          ))}
        </span>
      ) : (
        <span
          aria-hidden="true"
          className="relative h-1.5 w-12 overflow-hidden rounded-full bg-subtle-hover"
        >
          <span
            className={cn(
              'absolute inset-y-0 left-0 rounded-full',
              complete ? 'bg-success' : 'bg-control',
            )}
            style={{ width: `${(clamped / total) * 100}%` }}
          />
        </span>
      )}
      {showLabel && (
        <span
          aria-hidden="true"
          className={cn('text-sm tabular-nums', complete ? 'text-success' : 'text-muted')}
        >
          {clamped}/{total}
        </span>
      )}
    </span>
  )
}
