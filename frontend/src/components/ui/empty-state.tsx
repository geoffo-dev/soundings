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
  /**
   * `compact` for inside a section or card; default for a whole page/panel;
   * `inline`: one quiet row (icon, title, description, action) for a section
   * that is empty most of the time and shouldn't take the page's room.
   */
  size?: 'default' | 'compact' | 'inline'
  /** Heading level of the title: 1 when it is the whole page (a 404), 2 right under a page title. */
  headingLevel?: 1 | 2 | 3
}

/** Friendly empty state: say what this place is for and what to do next. */
export function EmptyState({
  icon,
  title,
  description,
  action,
  secondaryAction,
  size = 'default',
  headingLevel = 3,
  className,
  ...props
}: EmptyStateProps) {
  const compact = size === 'compact'
  const Heading = `h${headingLevel}` as const
  if (size === 'inline') {
    return (
      <div
        data-slot="empty-state"
        className={cn('flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-3', className)}
        {...props}
      >
        {icon && (
          <span aria-hidden="true" className="flex shrink-0 text-muted [&_svg]:size-4">
            {icon}
          </span>
        )}
        <div className="flex min-w-0 flex-1 flex-col gap-0.5 sm:flex-row sm:items-baseline sm:gap-2">
          <Heading className="text-sm font-medium text-primary">{title}</Heading>
          {description && <p className="text-sm text-muted">{description}</p>}
        </div>
        {(action ?? secondaryAction) && (
          <div className="flex shrink-0 flex-wrap items-center gap-2">
            {action}
            {secondaryAction}
          </div>
        )}
      </div>
    )
  }
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
      <Heading className={cn('font-semibold text-primary', compact ? 'text-base' : 'text-lg')}>
        {title}
      </Heading>
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
