import type { ComponentProps } from 'react'

import { cn } from '@/lib/utils'

/**
 * Inline spinner — only for in-button/in-field loading. For content loading use
 * <Skeleton> so layout doesn't jump.
 */
export function Spinner({
  className,
  label,
  ...props
}: ComponentProps<'svg'> & { label?: string }) {
  return (
    <svg
      viewBox="0 0 16 16"
      fill="none"
      role={label ? 'img' : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      className={cn('size-4 shrink-0 animate-spin', className)}
      {...props}
    >
      <circle cx="8" cy="8" r="6.25" stroke="currentColor" strokeOpacity="0.25" strokeWidth="1.5" />
      <path
        d="M14.25 8A6.25 6.25 0 0 0 8 1.75"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
    </svg>
  )
}
