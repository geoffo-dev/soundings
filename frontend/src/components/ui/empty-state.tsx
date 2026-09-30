import type { ComponentProps, ReactNode } from 'react'

import { cn } from '@/lib/utils'

export interface EmptyStateProps extends Omit<ComponentProps<'div'>, 'title'> {
  icon?: ReactNode
  title: ReactNode
  description?: ReactNode
  /** The one thing to do next — usually a primary <Button>. */
  action?: ReactNode
  /** Optional quieter alternative (ghost/link button). */
  secondaryAction?: ReactNode
  /** `compact` for inside a section or card; default for a whole page/panel. */
  size?: 'default' | 'compact'
}

/** Friendly empty state: say what this place is for and what to do next. */
export function EmptyState({
  icon,
  title,
  description,
  action,
  secondaryAction,
  size = 'default',
  className,
  ...props
}: EmptyStateProps) {
  const compact = size === 'compact'
  return (
    <div
      data-slot="empty-state"
      className={cn(
        'flex flex-col items-center text-center',
        compact ? 'gap-2 px-4 py-8' : 'gap-3 px-6 py-16',
        className,
      )}
      {...props}
    >
      {icon && (
        <div
          aria-hidden="true"
          className={cn(
            'mb-1 flex items-center justify-center rounded-xl border bg-surface text-muted',
            compact ? 'size-9 [&_svg]:size-4.5' : 'size-12 [&_svg]:size-5.5',
          )}
        >
          {icon}
        </div>
      )}
      <h3 className={cn('font-semibold text-primary', compact ? 'text-base' : 'text-lg')}>
        {title}
      </h3>
      {description && (
        <p className={cn('max-w-sm text-muted', compact ? 'text-sm' : 'text-base')}>
          {description}
        </p>
      )}
      {(action ?? secondaryAction) && (
        <div
          className={cn(
            'flex flex-wrap items-center justify-center gap-2',
            compact ? 'mt-1' : 'mt-3',
          )}
        >
          {action}
          {secondaryAction}
        </div>
      )}
    </div>
  )
}
