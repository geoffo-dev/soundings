import type { ReactNode } from 'react'

import { cn } from '@/lib/utils'

export interface PageProps {
  children: ReactNode
  /** `default` for reading/forms (max ~960px), `wide` for tables, `full` for boards. */
  width?: 'default' | 'wide' | 'full'
  className?: string
}

/** Content column inside the shell: consistent max-width, gutters and vertical rhythm. */
export function Page({ children, width = 'default', className }: PageProps) {
  return (
    <div
      className={cn(
        'mx-auto flex w-full flex-col gap-8 px-4 py-6 sm:px-6 lg:px-10 lg:py-8',
        width === 'default' && 'max-w-5xl',
        width === 'wide' && 'max-w-7xl',
        className,
      )}
    >
      {children}
    </div>
  )
}

export interface PageHeaderProps {
  title: ReactNode
  description?: ReactNode
  /** The page's one primary action (plus optional quiet secondary ones). */
  actions?: ReactNode
  /**
   * Phones: keep the (small) actions beside the title and the description to one
   * line, so the content starts high on a screen that has little room (a board).
   */
  compact?: boolean
  className?: string
}

export function PageHeader({
  title,
  description,
  actions,
  compact = false,
  className,
}: PageHeaderProps) {
  return (
    <div
      className={cn(
        'flex sm:flex-row sm:items-start sm:justify-between',
        compact ? 'flex-row items-start justify-between gap-3' : 'flex-col gap-4',
        className,
      )}
    >
      <div className="flex min-w-0 flex-col gap-1">
        <h1 className="text-2xl font-semibold text-primary">{title}</h1>
        {description && (
          <p
            className={cn(
              'max-w-2xl text-base text-muted',
              compact && 'max-sm:line-clamp-1 max-sm:text-sm',
            )}
          >
            {description}
          </p>
        )}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  )
}

export interface PageSectionProps {
  title: ReactNode
  description?: ReactNode
  actions?: ReactNode
  children: ReactNode
  /** Anchor for links such as /#evaluations; also labels the section for screen readers. */
  id?: string
  className?: string
}

export function PageSection({
  title,
  description,
  actions,
  children,
  id,
  className,
}: PageSectionProps) {
  return (
    <section
      id={id}
      aria-labelledby={id ? `${id}-heading` : undefined}
      className={cn('flex scroll-mt-6 flex-col gap-3', className)}
    >
      <div className="flex items-end justify-between gap-4">
        <div className="flex flex-col gap-0.5">
          <h2
            id={id ? `${id}-heading` : undefined}
            className="flex items-center gap-2 text-base font-semibold text-primary"
          >
            {title}
          </h2>
          {description && <p className="text-sm text-muted">{description}</p>}
        </div>
        {actions}
      </div>
      {children}
    </section>
  )
}
