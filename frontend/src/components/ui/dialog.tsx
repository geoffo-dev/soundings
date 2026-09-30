import { X } from 'lucide-react'
import { Dialog as DialogPrimitive } from 'radix-ui'
import type { ComponentProps } from 'react'

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
}

export function DialogContent({
  className,
  children,
  size = 'md',
  hideClose = false,
  position = 'center',
  ...props
}: DialogContentProps) {
  return (
    <DialogPortal>
      <DialogOverlay />
      <DialogPrimitive.Content
        data-slot="dialog-content"
        className={cn(
          'fixed left-1/2 z-50 flex max-h-[calc(100dvh-2rem)] w-[calc(100%-2rem)] -translate-x-1/2 flex-col',
          'rounded-xl border bg-elevated text-primary shadow-dialog outline-none',
          'data-[state=closed]:animate-pop-out data-[state=open]:animate-pop-in',
          position === 'center' ? 'top-1/2 -translate-y-1/2' : 'top-[12dvh] max-h-[76dvh]',
          sizes[size],
          className,
        )}
        {...props}
      >
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
