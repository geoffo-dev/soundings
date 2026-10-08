import { cva } from 'class-variance-authority'
import type { ComponentProps } from 'react'

import {
  defaultStatusLabel,
  statusTone,
  type ClosedResolution,
  type IdeaStatus,
  type StatusTone,
} from '@/lib/status'
import { cn } from '@/lib/utils'

const dot = cva('size-2 shrink-0 rounded-full', {
  variants: {
    tone: {
      new: 'bg-status-new',
      research: 'bg-status-research',
      evaluating: 'bg-status-evaluating',
      shortlisted: 'bg-status-shortlisted',
      proposal: 'bg-status-proposal',
      accepted: 'bg-status-accepted',
      rejected: 'bg-status-rejected',
      parked: 'bg-status-parked',
    } satisfies Record<StatusTone, string>,
  },
})

export function StatusDot({ tone, className }: { tone: StatusTone; className?: string }) {
  return <span aria-hidden="true" className={cn(dot({ tone }), className)} />
}

export interface StatusBadgeProps extends Omit<ComponentProps<'span'>, 'children'> {
  status: IdeaStatus
  resolution?: ClosedResolution | null
  /** Project-specific label (admins can rename statuses). */
  label?: string
  /** `plain` drops the outline — for dense tables and board cards. */
  variant?: 'outline' | 'plain'
}

/** Status is always label + colour dot, never colour alone. */
export function StatusBadge({
  status,
  resolution,
  label,
  variant = 'outline',
  className,
  ...props
}: StatusBadgeProps) {
  const tone = statusTone(status, resolution)
  return (
    <span
      data-slot="status-badge"
      data-status={tone}
      className={cn(
        'inline-flex h-6 shrink-0 items-center gap-1.5 rounded-md text-sm font-medium whitespace-nowrap text-primary',
        variant === 'outline' ? 'border bg-surface px-2' : 'px-0',
        className,
      )}
      {...props}
    >
      <StatusDot tone={tone} />
      {label ?? defaultStatusLabel(status, resolution)}
    </span>
  )
}
