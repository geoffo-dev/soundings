import { cva } from 'class-variance-authority'
import { X } from 'lucide-react'
import { Dialog as SheetPrimitive } from 'radix-ui'
import type { ComponentProps } from 'react'

import { DialogOverlay } from '@/components/ui/dialog'
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
  ...props
}: SheetContentProps) {
  return (
    <SheetPrimitive.Portal>
      <DialogOverlay />
      <SheetPrimitive.Content
        data-slot="sheet-content"
        className={cn(sheet({ side, size }), className)}
        {...props}
      >
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
