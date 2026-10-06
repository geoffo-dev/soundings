import { cva, type VariantProps } from 'class-variance-authority'
import { Slot } from 'radix-ui'
import type { ComponentProps } from 'react'

import { Spinner } from '@/components/ui/spinner'
import { cn } from '@/lib/utils'

export const buttonVariants = cva(
  [
    'relative inline-flex shrink-0 items-center justify-center gap-1.5 rounded-md font-medium whitespace-nowrap select-none',
    'transition-[background-color,border-color,color,box-shadow,opacity] duration-150',
    'disabled:pointer-events-none disabled:opacity-50 aria-disabled:pointer-events-none aria-disabled:opacity-50',
    "[&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  ],
  {
    variants: {
      variant: {
        primary: 'bg-accent text-accent-foreground hover:bg-accent-hover active:bg-accent-hover',
        secondary: 'bg-subtle text-primary hover:bg-subtle-hover',
        outline: 'border bg-surface text-primary hover:border-strong hover:bg-subtle',
        ghost: 'text-secondary hover:bg-subtle hover:text-primary data-[state=open]:bg-subtle',
        destructive: 'bg-danger text-danger-foreground hover:bg-danger-hover',
        link: 'h-auto! px-0! text-accent underline-offset-4 hover:underline',
      },
      size: {
        sm: "h-7 px-2.5 text-sm [&_svg:not([class*='size-'])]:size-3.5",
        md: 'h-8 px-3 text-sm',
        lg: 'h-10 gap-2 px-4 text-base',
        icon: 'size-8',
        'icon-sm': "size-7 [&_svg:not([class*='size-'])]:size-3.5",
      },
    },
    defaultVariants: { variant: 'secondary', size: 'md' },
  },
)

export interface ButtonProps extends ComponentProps<'button'>, VariantProps<typeof buttonVariants> {
  /** Render the child element (e.g. a router <Link>) with button styles. */
  asChild?: boolean
  /**
   * Shows a spinner, sets aria-busy and ignores presses until it is done. It stays
   * focusable (`aria-disabled`, not `disabled`): a pending "Cancel" or "Save" keeps
   * focus, where a disabled button would drop it to `<body>` (WCAG 2.4.3).
   */
  loading?: boolean
}

/** Keys that press a button or open a menu trigger. */
const PRESS_KEYS = new Set(['Enter', ' ', 'ArrowDown', 'ArrowUp'])

export function Button({
  className,
  variant,
  size,
  asChild = false,
  loading = false,
  disabled,
  children,
  type,
  onClick,
  onKeyDown,
  onPointerDown,
  ...props
}: ButtonProps) {
  const classes = cn(buttonVariants({ variant, size }), className)
  if (asChild) {
    return (
      <Slot.Root
        data-slot="button"
        className={classes}
        onClick={onClick}
        onKeyDown={onKeyDown}
        onPointerDown={onPointerDown}
        {...props}
      >
        {children}
      </Slot.Root>
    )
  }
  // Busy but focusable: presses do nothing (a form's Enter included: its click is
  // cancelled), and a menu trigger's Radix handlers see them prevented.
  const busy = loading && !disabled
  return (
    <button
      data-slot="button"
      type={type ?? 'button'}
      className={classes}
      disabled={disabled}
      aria-disabled={busy || undefined}
      aria-busy={loading || undefined}
      onClick={(event) => {
        if (busy) {
          event.preventDefault()
          return
        }
        onClick?.(event)
      }}
      onKeyDown={(event) => {
        if (busy) {
          if (PRESS_KEYS.has(event.key)) event.preventDefault()
          return
        }
        onKeyDown?.(event)
      }}
      onPointerDown={(event) => {
        if (busy) {
          event.preventDefault()
          return
        }
        onPointerDown?.(event)
      }}
      {...props}
    >
      {loading && <Spinner />}
      {children}
    </button>
  )
}
