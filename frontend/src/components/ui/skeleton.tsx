import type { ComponentProps } from 'react'

import { cn } from '@/lib/utils'

/**
 * Placeholder shaped like the content that is loading. Prefer skeletons over
 * spinners: the layout stays put and the page feels faster.
 */
export function Skeleton({ className, ...props }: ComponentProps<'div'>) {
  return (
    <div
      data-slot="skeleton"
      aria-hidden="true"
      className={cn('animate-pulse rounded-md bg-subtle-hover', className)}
      {...props}
    />
  )
}

/** Wraps skeletons so assistive tech hears "Loading…" once. */
export function SkeletonGroup({
  label = 'Loading…',
  className,
  children,
  ...props
}: ComponentProps<'div'> & { label?: string }) {
  return (
    <div role="status" aria-live="polite" className={className} {...props}>
      <span className="sr-only">{label}</span>
      {children}
    </div>
  )
}

/** One row of an idea list/table. */
export function SkeletonListRow({ className }: { className?: string }) {
  return (
    <div className={cn('flex h-11 items-center gap-3 border-b border-subtle px-4', className)}>
      <Skeleton className="size-2 rounded-full" />
      <Skeleton className="h-3.5 w-[min(22rem,45%)]" />
      <div className="ml-auto flex items-center gap-4">
        <Skeleton className="hidden h-3 w-10 sm:block" />
        <Skeleton className="hidden h-5 w-10 sm:block" />
        <Skeleton className="size-6 rounded-full" />
      </div>
    </div>
  )
}

/** A card in a board column. */
export function SkeletonBoardCard({ className }: { className?: string }) {
  return (
    <div className={cn('flex flex-col gap-3 rounded-lg border bg-surface p-3', className)}>
      <Skeleton className="h-3.5 w-4/5" />
      <Skeleton className="h-3 w-3/5" />
      <div className="flex items-center justify-between pt-1">
        <Skeleton className="h-5 w-9" />
        <Skeleton className="size-5 rounded-full" />
      </div>
    </div>
  )
}

/** The idea page: content column plus details sidebar. */
export function SkeletonIdeaPage({ className }: { className?: string }) {
  return (
    <div className={cn('grid gap-8 lg:grid-cols-[minmax(0,1fr)_18rem]', className)}>
      <div className="flex flex-col gap-4">
        <Skeleton className="h-7 w-3/5" />
        <Skeleton className="h-4 w-4/5" />
        <div className="mt-2 flex gap-4 border-b border-subtle pb-2">
          <Skeleton className="h-4 w-16" />
          <Skeleton className="h-4 w-20" />
          <Skeleton className="h-4 w-16" />
        </div>
        <div className="flex flex-col gap-2.5 pt-2">
          <Skeleton className="h-3.5 w-full" />
          <Skeleton className="h-3.5 w-11/12" />
          <Skeleton className="h-3.5 w-4/5" />
          <Skeleton className="h-3.5 w-2/3" />
        </div>
      </div>
      <div className="flex flex-col gap-5">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="flex flex-col gap-2">
            <Skeleton className="h-3 w-16" />
            <Skeleton className="h-6 w-32" />
          </div>
        ))}
      </div>
    </div>
  )
}
