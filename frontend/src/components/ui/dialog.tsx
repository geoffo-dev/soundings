import { X } from 'lucide-react'
import { Dialog as DialogPrimitive } from 'radix-ui'
import type { ComponentProps } from 'react'

import { FocusOrigin, useReturnFocus } from '@/components/ui/return-focus'
import { cn } from '@/lib/utils'

export const Dialog = DialogPrimitive.Root
export const DialogTrigger = DialogPrimitive.Trigger
export const DialogClose = DialogPrimitive.Close
export const DialogPortal = DialogPrimitive.Portal

export function DialogOverlay({
  className,
  ...props
}: ComponentProps<typeof DialogPrimitive.Overlay>) {
  return (
    <DialogPrimitive.Overlay
      data-slot="dialog-overlay"
      className={cn(
        'fixed inset-0 z-50 bg-overlay data-[state=closed]:animate-fade-out data-[state=open]:animate-fade-in',
        className,
      )}
      {...props}
    />
  )
}

const sizes = { sm: 'max-w-sm', md: 'max-w-md', lg: 'max-w-lg', xl: 'max-w-2xl' } as const

export interface DialogContentProps extends ComponentProps<typeof DialogPrimitive.Content> {
  size?: keyof typeof sizes
  /** Hide the corner close button (Esc and overlay click still close). */
  hideClose?: boolean
  /** `top` pins the dialog near the top (command palette); default is centred. */
  position?: 'center' | 'top'
  /**
   * `fullscreen` makes the dialog a full-screen sheet below `sm` (forms people
   * fill in on a phone, e.g. New idea); put the actions in a DialogFooter so
   * they stay at the bottom.
   */
  mobile?: 'inset' | 'fullscreen'
}

export function DialogContent({
  className,
  children,
  size = 'md',
  hideClose = false,
  position = 'center',
  mobile = 'inset',
  onEscapeKeyDown,
  onCloseAutoFocus,
  ref,
  ...props
}: DialogContentProps) {
  // Opened from code (no Trigger): focus goes back to where it was (return-focus.ts).
  const { attach, capture, closeAutoFocus } = useReturnFocus(ref, onCloseAutoFocus)
  return (
    <DialogPortal>
      <DialogOverlay />
      <DialogPrimitive.Content
        ref={attach}
        data-slot="dialog-content"
        data-mobile={mobile}
        onCloseAutoFocus={closeAutoFocus}
        onEscapeKeyDown={(event) => {
          // Esc first closes an open autocomplete inside the dialog (TagInput, comboboxes).
          // cmdk's search field is always aria-expanded (its list is inline), so it doesn't count.
          const target = event.target instanceof Element ? event.target : null
          if (target?.closest('[role="combobox"][aria-expanded="true"]:not([cmdk-input])')) {
            event.preventDefault()
          }
          onEscapeKeyDown?.(event)
        }}
        className={cn(
          'fixed left-1/2 z-50 flex max-h-[calc(100dvh-2rem)] w-[calc(100%-2rem)] -translate-x-1/2 flex-col',
          'rounded-xl border bg-elevated text-primary shadow-dialog outline-none',
          'data-[state=closed]:animate-pop-out data-[state=open]:animate-pop-in',
          position === 'center' ? 'top-1/2 -translate-y-1/2' : 'top-[12dvh] max-h-[76dvh]',
          sizes[size],
          mobile === 'fullscreen' &&
            'max-sm:top-0 max-sm:h-dvh max-sm:max-h-dvh max-sm:w-full max-sm:max-w-none max-sm:translate-y-0 max-sm:rounded-none max-sm:border-0',
          className,
        )}
        {...props}
      >
        <FocusOrigin capture={capture} />
        {children}
        {!hideClose && (
          <DialogPrimitive.Close
            aria-label="Close"
            className="absolute top-3.5 right-3.5 inline-flex size-7 items-center justify-center rounded-md text-muted transition-colors hover:bg-subtle hover:text-primary"
          >
            <X className="size-4" />
          </DialogPrimitive.Close>
        )}
      </DialogPrimitive.Content>
    </DialogPortal>
  )
}

export function DialogHeader({ className, ...props }: ComponentProps<'div'>) {
  return <div className={cn('flex flex-col gap-1 px-5 pt-5 pr-12', className)} {...props} />
}

export function DialogBody({ className, ...props }: ComponentProps<'div'>) {
  return <div className={cn('min-h-0 flex-1 overflow-y-auto px-5 py-4', className)} {...props} />
}

export function DialogFooter({ className, ...props }: ComponentProps<'div'>) {
  return (
    <div
      className={cn(
        'flex flex-col-reverse gap-2 px-5 pb-5 sm:flex-row sm:items-center sm:justify-end',
        // Full-screen on phones: a fixed action bar at the bottom.
        'in-data-[mobile=fullscreen]:max-sm:border-t in-data-[mobile=fullscreen]:max-sm:border-subtle in-data-[mobile=fullscreen]:max-sm:pt-3 in-data-[mobile=fullscreen]:max-sm:pb-[max(0.75rem,env(safe-area-inset-bottom))]',
        className,
      )}
      {...props}
    />
  )
}

export function DialogTitle({ className, ...props }: ComponentProps<typeof DialogPrimitive.Title>) {
  return (
    <DialogPrimitive.Title
      className={cn('text-lg font-semibold text-primary', className)}
      {...props}
    />
  )
}

export function DialogDescription({
  className,
  ...props
}: ComponentProps<typeof DialogPrimitive.Description>) {
  return <DialogPrimitive.Description className={cn('text-sm text-muted', className)} {...props} />
}
