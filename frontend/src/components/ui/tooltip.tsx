import { Tooltip as TooltipPrimitive } from 'radix-ui'
import type { ComponentProps, ReactNode } from 'react'

import { KbdShortcut } from '@/components/ui/kbd'
import { cn } from '@/lib/utils'

/** Mounted once in the root route. */
export function TooltipProvider({
  delayDuration = 400,
  skipDelayDuration = 200,
  ...props
}: ComponentProps<typeof TooltipPrimitive.Provider>) {
  return (
    <TooltipPrimitive.Provider
      delayDuration={delayDuration}
      skipDelayDuration={skipDelayDuration}
      {...props}
    />
  )
}

export const Tooltip = TooltipPrimitive.Root
export const TooltipTrigger = TooltipPrimitive.Trigger

export function TooltipContent({
  className,
  sideOffset = 6,
  children,
  ...props
}: ComponentProps<typeof TooltipPrimitive.Content>) {
  return (
    <TooltipPrimitive.Portal>
      <TooltipPrimitive.Content
        data-slot="tooltip-content"
        sideOffset={sideOffset}
        className={cn(
          'z-50 flex max-w-72 items-center gap-2 rounded-md border bg-elevated px-2 py-1 text-sm text-primary shadow-overlay',
          'origin-(--radix-tooltip-content-transform-origin) animate-pop-in data-[state=closed]:animate-pop-out',
          className,
        )}
        {...props}
      >
        {children}
      </TooltipPrimitive.Content>
    </TooltipPrimitive.Portal>
  )
}

export interface WithTooltipProps {
  content: ReactNode
  /** Shortcut shown next to the text, e.g. "n" or "mod+k". */
  shortcut?: string
  side?: ComponentProps<typeof TooltipPrimitive.Content>['side']
  align?: ComponentProps<typeof TooltipPrimitive.Content>['align']
  children: ReactNode
}

/** Convenience wrapper: `<WithTooltip content="New idea" shortcut="n"><Button …/></WithTooltip>`. */
export function WithTooltip({ content, shortcut, side, align, children }: WithTooltipProps) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>{children}</TooltipTrigger>
      <TooltipContent side={side} align={align}>
        <span>{content}</span>
        {shortcut && <KbdShortcut keys={shortcut} />}
      </TooltipContent>
    </Tooltip>
  )
}
