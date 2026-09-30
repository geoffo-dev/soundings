import { cva, type VariantProps } from 'class-variance-authority'
import type { ComponentProps } from 'react'

import { cn } from '@/lib/utils'

export const badgeVariants = cva(
  [
    'inline-flex h-5 shrink-0 items-center gap-1 rounded-sm px-1.5 text-xs font-medium whitespace-nowrap',
    "[&_svg:not([class*='size-'])]:size-3",
  ],
  {
    variants: {
      variant: {
        neutral: 'bg-subtle text-secondary',
        outline: 'border text-secondary',
        accent: 'bg-accent-subtle text-accent',
        success: 'bg-success-subtle text-success',
        warning: 'bg-warning-subtle text-warning',
        danger: 'bg-danger-subtle text-danger',
        info: 'bg-info-subtle text-info',
        solid: 'bg-accent text-accent-foreground',
      },
    },
    defaultVariants: { variant: 'neutral' },
  },
)

export interface BadgeProps extends ComponentProps<'span'>, VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <span data-slot="badge" className={cn(badgeVariants({ variant }), className)} {...props} />
}

/** Small numeric count, e.g. next to a sidebar item. */
export function CountBadge({ className, ...props }: ComponentProps<'span'>) {
  return (
    <span
      className={cn(
        'inline-flex h-4.5 min-w-4.5 items-center justify-center rounded-full bg-subtle-hover px-1.5 text-xs font-medium text-secondary tabular-nums',
        className,
      )}
      {...props}
    />
  )
}
