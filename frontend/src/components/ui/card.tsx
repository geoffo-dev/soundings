import type { ComponentProps } from 'react'

import { cn } from '@/lib/utils'

/** Bordered surface. No shadow — elevation is reserved for overlays. */
export function Card({ className, ...props }: ComponentProps<'div'>) {
  return (
    <div
      data-slot="card"
      className={cn('flex flex-col rounded-lg border bg-surface text-primary', className)}
      {...props}
    />
  )
}

export function CardHeader({ className, ...props }: ComponentProps<'div'>) {
  return <div className={cn('flex flex-col gap-1 px-5 pt-4', className)} {...props} />
}

export function CardTitle({ className, children, ...props }: ComponentProps<'h3'>) {
  return (
    <h3 className={cn('text-base font-semibold text-primary', className)} {...props}>
      {children}
    </h3>
  )
}

export function CardDescription({ className, ...props }: ComponentProps<'p'>) {
  return <p className={cn('text-sm text-muted', className)} {...props} />
}

export function CardContent({ className, ...props }: ComponentProps<'div'>) {
  return <div className={cn('px-5 py-4', className)} {...props} />
}

export function CardFooter({ className, ...props }: ComponentProps<'div'>) {
  return (
    <div
      className={cn('flex items-center gap-2 border-t border-subtle px-5 py-3', className)}
      {...props}
    />
  )
}
