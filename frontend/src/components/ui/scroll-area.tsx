import { ScrollArea as ScrollAreaPrimitive } from 'radix-ui'
import type { ComponentProps } from 'react'

import { cn } from '@/lib/utils'

export interface ScrollAreaProps extends ComponentProps<typeof ScrollAreaPrimitive.Root> {
  /**
   * Make the viewport keyboard-focusable so it can be scrolled with arrow keys.
   * Needed when the content has no focusable elements; pass `aria-label` too.
   */
  focusable?: boolean
}

/** Scroll container with a thin, theme-aware scrollbar (sidebars, popovers). */
export function ScrollArea({
  className,
  children,
  focusable = false,
  'aria-label': ariaLabel,
  ...props
}: ScrollAreaProps) {
  return (
    <ScrollAreaPrimitive.Root
      data-slot="scroll-area"
      className={cn('relative overflow-hidden', className)}
      {...props}
    >
      <ScrollAreaPrimitive.Viewport
        tabIndex={focusable ? 0 : undefined}
        role={focusable ? 'region' : undefined}
        aria-label={focusable ? ariaLabel : undefined}
        className="size-full rounded-[inherit] focus-visible:outline-offset-[-2px]"
      >
        {children}
      </ScrollAreaPrimitive.Viewport>
      <ScrollBar />
      <ScrollAreaPrimitive.Corner />
    </ScrollAreaPrimitive.Root>
  )
}

export function ScrollBar({
  className,
  orientation = 'vertical',
  ...props
}: ComponentProps<typeof ScrollAreaPrimitive.Scrollbar>) {
  return (
    <ScrollAreaPrimitive.Scrollbar
      orientation={orientation}
      className={cn(
        'flex touch-none p-px transition-colors select-none',
        orientation === 'vertical' ? 'h-full w-2' : 'h-2 flex-col',
        className,
      )}
      {...props}
    >
      <ScrollAreaPrimitive.Thumb className="relative flex-1 rounded-full bg-border hover:bg-control/50" />
    </ScrollAreaPrimitive.Scrollbar>
  )
}
