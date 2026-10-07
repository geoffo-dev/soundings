import { Tabs as TabsPrimitive } from 'radix-ui'
import { type ComponentProps, useMemo } from 'react'

import { cn, mergeRefs } from '@/lib/utils'

import { useScrollFade } from './scroll-fade'

export const Tabs = TabsPrimitive.Root

/**
 * Underlined tabs (the idea page's Overview / Evaluations / Proposal). Too many
 * for the width (a phone), the row scrolls sideways and fades the edge with more.
 */
export function TabsList({ className, ref, ...props }: ComponentProps<typeof TabsPrimitive.List>) {
  const fade = useScrollFade<HTMLDivElement>()
  const merged = useMemo(() => mergeRefs(fade, ref), [fade, ref])
  return (
    <TabsPrimitive.List
      ref={merged}
      data-slot="tabs-list"
      className={cn(
        'scrollbar-none flex items-center gap-4 overflow-x-auto border-b scroll-fade-x',
        className,
      )}
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
        'data-[state=active]:border-accent-control data-[state=active]:text-primary',
        "[&_svg:not([class*='size-'])]:size-4",
        className,
      )}
      {...props}
    />
  )
}

/**
 * Radix makes each panel a Tab stop (so a panel without focusable content can
 * still be reached); it shows the standard focus ring like everything else
 * (WCAG 2.4.7).
 */
export function TabsContent({ className, ...props }: ComponentProps<typeof TabsPrimitive.Content>) {
  return (
    <TabsPrimitive.Content
      data-slot="tabs-content"
      className={cn('rounded-sm pt-5', className)}
      {...props}
    />
  )
}
