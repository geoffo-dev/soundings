import { cva } from 'class-variance-authority'
import { X } from 'lucide-react'
import { Dialog as SheetPrimitive } from 'radix-ui'
import { useEffect, useSyncExternalStore, type ComponentProps } from 'react'

import { DialogOverlay } from '@/components/ui/dialog'
import { FocusOrigin, useReturnFocus } from '@/components/ui/return-focus'
import { cn } from '@/lib/utils'

export const Sheet = SheetPrimitive.Root
export const SheetTrigger = SheetPrimitive.Trigger
export const SheetClose = SheetPrimitive.Close

const sheet = cva('fixed z-50 flex flex-col bg-elevated text-primary shadow-dialog outline-none', {
  variants: {
    side: {
      // Bottom sheet on phones (thumb-friendly), side panel from `sm` up.
      right: [
        'inset-x-0 bottom-0 h-[calc(100dvh-1.5rem)] rounded-t-xl border-t',
        'data-[state=closed]:animate-sheet-out-bottom data-[state=open]:animate-sheet-in-bottom',
        'sm:inset-x-auto sm:inset-y-0 sm:right-0 sm:h-dvh sm:w-full sm:rounded-none sm:border-t-0 sm:border-l',
        'sm:data-[state=closed]:animate-sheet-out-right sm:data-[state=open]:animate-sheet-in-right',
      ],
      // Navigation drawer.
      left: [
        'inset-y-0 left-0 h-dvh w-[85vw] max-w-72 border-r',
        'data-[state=closed]:animate-sheet-out-left data-[state=open]:animate-sheet-in-left',
      ],
    },
    size: { sm: '', md: '', lg: '' },
  },
  compoundVariants: [
    { side: 'right', size: 'sm', className: 'sm:max-w-sm' },
    { side: 'right', size: 'md', className: 'sm:max-w-lg' },
    { side: 'right', size: 'lg', className: 'sm:max-w-2xl' },
  ],
  defaultVariants: { side: 'right', size: 'md' },
})

/*
 * Open side sheets, so toasts can move up out of the way of a sheet's footer
 * actions (toaster.tsx) instead of covering them.
 */
let openSideSheets = 0
const sheetListeners = new Set<() => void>()

function subscribeToSheets(listener: () => void) {
  sheetListeners.add(listener)
  return () => {
    sheetListeners.delete(listener)
  }
}

/** True while a side sheet (`side="right"`, a bottom sheet on phones) is open. */
export function useSideSheetOpen(): boolean {
  return useSyncExternalStore(
    subscribeToSheets,
    () => openSideSheets > 0,
    () => false,
  )
}

/** Rendered inside an open side sheet's content: counts it as open while mounted. */
function SideSheetPresence() {
  useEffect(() => {
    openSideSheets += 1
    sheetListeners.forEach((listener) => listener())
    return () => {
      openSideSheets -= 1
      sheetListeners.forEach((listener) => listener())
    }
  }, [])
  return null
}

export interface SheetContentProps extends ComponentProps<typeof SheetPrimitive.Content> {
  side?: 'right' | 'left'
  size?: 'sm' | 'md' | 'lg'
  hideClose?: boolean
}

export function SheetContent({
  className,
  children,
  side = 'right',
  size = 'md',
  hideClose = false,
  onOpenAutoFocus,
  onCloseAutoFocus,
  ref,
  ...props
}: SheetContentProps) {
  // Opened from code (no Trigger): focus goes back to where it was (return-focus.ts).
  const { attach, capture, closeAutoFocus } = useReturnFocus(ref, onCloseAutoFocus)
  return (
    <SheetPrimitive.Portal>
      <DialogOverlay />
      <SheetPrimitive.Content
        ref={attach}
        data-slot="sheet-content"
        className={cn(sheet({ side, size }), className)}
        onOpenAutoFocus={(event) => {
          onOpenAutoFocus?.(event)
          if (event.defaultPrevented) return
          // A sheet is a view, not a form: it opens with focus on itself (its title is
          // announced; Tab goes to the first control). Radix would focus the first field,
          // with its text selected (one stray key rewrites it) or the phone keyboard up,
          // and where that lands would depend on whether the content was still loading.
          event.preventDefault()
          ;(event.currentTarget as HTMLElement | null)?.focus({ preventScroll: true })
        }}
        onCloseAutoFocus={closeAutoFocus}
        {...props}
      >
        <FocusOrigin capture={capture} />
        {side === 'right' && <SideSheetPresence />}
        {side === 'right' && (
          <span
            aria-hidden="true"
            className="mx-auto mt-2 h-1 w-9 shrink-0 rounded-full bg-subtle-hover sm:hidden"
          />
        )}
        {children}
        {!hideClose && (
          <SheetPrimitive.Close
            aria-label="Close"
            className="absolute top-4 right-4 inline-flex size-7 items-center justify-center rounded-md text-muted transition-colors hover:bg-subtle hover:text-primary sm:top-3.5"
          >
            <X className="size-4" />
          </SheetPrimitive.Close>
        )}
      </SheetPrimitive.Content>
    </SheetPrimitive.Portal>
  )
}

export function SheetHeader({ className, ...props }: ComponentProps<'div'>) {
  return (
    <div
      className={cn(
        'flex shrink-0 flex-col gap-1 border-b border-subtle px-5 py-4 pr-14',
        className,
      )}
      {...props}
    />
  )
}

export function SheetBody({ className, ...props }: ComponentProps<'div'>) {
  return <div className={cn('min-h-0 flex-1 overflow-y-auto px-5 py-5', className)} {...props} />
}

export function SheetFooter({ className, ...props }: ComponentProps<'div'>) {
  return (
    <div
      className={cn(
        'flex shrink-0 items-center justify-end gap-2 border-t border-subtle px-5 py-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]',
        className,
      )}
      {...props}
    />
  )
}

export function SheetTitle({ className, ...props }: ComponentProps<typeof SheetPrimitive.Title>) {
  return (
    <SheetPrimitive.Title
      className={cn('text-lg font-semibold text-primary', className)}
      {...props}
    />
  )
}

export function SheetDescription({
  className,
  ...props
}: ComponentProps<typeof SheetPrimitive.Description>) {
  return <SheetPrimitive.Description className={cn('text-sm text-muted', className)} {...props} />
}
