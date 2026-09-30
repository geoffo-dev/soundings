import { Tabs as TabsPrimitive } from 'radix-ui'
import type { ComponentProps } from 'react'

import { cn } from '@/lib/utils'

export const Tabs = TabsPrimitive.Root

/** Underlined tabs (the idea page's Overview / Evaluations / Proposal). */
export function TabsList({ className, ...props }: ComponentProps<typeof TabsPrimitive.List>) {
  return (
    <TabsPrimitive.List
      data-slot="tabs-list"
      className={cn('scrollbar-none flex items-center gap-4 overflow-x-auto border-b', className)}
      {...props}
    />
  )
}

export function TabsTrigger({ className, ...props }: ComponentProps<typeof TabsPrimitive.Trigger>) {
  return (
    <TabsPrimitive.Trigger
      data-slot="tabs-trigger"
      className={cn(
        'relative -mb-px inline-flex h-9 shrink-0 items-center gap-1.5 border-b-2 border-transparent px-0.5 text-sm font-medium whitespace-nowrap text-muted',
        'transition-colors duration-150 hover:text-primary',
        'focus-visible:rounded-sm focus-visible:outline-offset-0',
        'disabled:pointer-events-none disabled:opacity-50',
        'data-[state=active]:border-accent data-[state=active]:text-primary',
        "[&_svg:not([class*='size-'])]:size-4",
        className,
      )}
      {...props}
    />
  )
}

export function TabsContent({ className, ...props }: ComponentProps<typeof TabsPrimitive.Content>) {
  return (
    <TabsPrimitive.Content
      data-slot="tabs-content"
      className={cn('pt-5 focus-visible:outline-none', className)}
      {...props}
    />
  )
}
