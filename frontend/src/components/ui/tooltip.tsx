import { Slot, Tooltip as TooltipPrimitive } from 'radix-ui'
import {
  useEffect,
  useRef,
  useState,
  type ComponentProps,
  type FocusEvent,
  type ReactNode,
} from 'react'

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

const OVERLAY = '[role="menu"], [role="dialog"], [role="alertdialog"], [role="listbox"]'

/**
 * Focus handed back rather than moved here: from nothing (an element that went, a
 * menu that closed) or from an overlay the trigger isn't in (a menu or dialog closing
 * returns focus to its button). A tooltip popping up then answers a question nobody
 * asked ("Ask an AI agent" right after choosing from that menu).
 */
function isReturnedFocus(event: FocusEvent<HTMLElement>): boolean {
  const from = event.relatedTarget
  if (!(from instanceof Element)) return true
  const overlay = from.closest(OVERLAY)
  return overlay !== null && !overlay.contains(event.currentTarget)
}

/**
 * Convenience wrapper: `<WithTooltip content="New idea" shortcut="n"><Button …/></WithTooltip>`.
 * Opens on hover and when the keyboard moves focus here; not when focus is only
 * returned to the trigger (a menu or dialog closing).
 */
export function WithTooltip({ content, shortcut, side, align, children }: WithTooltipProps) {
  const [open, setOpen] = useState(false)
  const returned = useRef(false)
  return (
    <Tooltip
      open={open}
      onOpenChange={(next) => {
        if (next && returned.current) return
        setOpen(next)
      }}
    >
      <TooltipTrigger
        asChild
        onFocus={(event) => {
          returned.current = isReturnedFocus(event)
        }}
        onBlur={() => {
          returned.current = false
        }}
        onPointerMove={() => {
          // The pointer is here: hovering shows it as usual.
          returned.current = false
        }}
      >
        {children}
      </TooltipTrigger>
      <TooltipContent side={side} align={align}>
        <span>{content}</span>
        {shortcut && <KbdShortcut keys={shortcut} />}
      </TooltipContent>
    </Tooltip>
  )
}

/** The provider's delay, for HoverTooltip's first opening (TooltipProvider). */
const HOVER_DELAY_MS = 400

/**
 * A tooltip for a trigger that never takes focus (a row's lock or warning icon) in
 * lists of thousands: until the pointer first arrives the trigger is a plain
 * element, and only then does it get a Radix tooltip (opening after the usual
 * delay). Keyboard users get the same words from the trigger's own label. Use
 * WithTooltip for anything focusable.
 */
export function HoverTooltip({
  content,
  side,
  align,
  children,
}: Omit<WithTooltipProps, 'shortcut'>) {
  const [armed, setArmed] = useState(false)
  const [open, setOpen] = useState(false)
  const timer = useRef<number | undefined>(undefined)
  useEffect(() => () => window.clearTimeout(timer.current), [])

  if (!armed) {
    return (
      <Slot.Root
        onPointerEnter={() => {
          setArmed(true)
          timer.current = window.setTimeout(() => setOpen(true), HOVER_DELAY_MS)
        }}
      >
        {children}
      </Slot.Root>
    )
  }
  return (
    <Tooltip
      open={open}
      onOpenChange={(next) => {
        window.clearTimeout(timer.current)
        setOpen(next)
      }}
    >
      <TooltipTrigger asChild>{children}</TooltipTrigger>
      <TooltipContent side={side} align={align}>
        <span>{content}</span>
      </TooltipContent>
    </Tooltip>
  )
}
