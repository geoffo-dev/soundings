import type { ComponentProps, ReactNode } from 'react'

import { useFieldControl } from '@/components/ui/field'
import { cn } from '@/lib/utils'

/** Shared by Input, Textarea, DatePicker and Select triggers so fields line up. */
export const controlStyles = cn(
  'w-full min-w-0 rounded-md border border-strong bg-surface text-primary',
  // 16px on phones stops iOS zooming into the field; 14px from sm up.
  'text-lg placeholder:text-muted sm:text-base',
  'transition-[border-color,box-shadow] duration-150 outline-none',
  'hover:border-control/60 focus-visible:border-focus focus-visible:ring-3 focus-visible:ring-focus/20',
  'disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:border-strong',
  'aria-invalid:border-danger aria-invalid:focus-visible:ring-danger/20',
)

export interface InputProps extends ComponentProps<'input'> {
  /** Decorative icon inside the field's leading edge (e.g. search). */
  startIcon?: ReactNode
}

export function Input({ className, type = 'text', startIcon, ...props }: InputProps) {
  const fieldProps = useFieldControl(props)
  const input = (
    <input
      type={type}
      data-slot="input"
      className={cn(
        controlStyles,
        'h-9 px-2.5 sm:h-8',
        'file:mr-2 file:border-0 file:bg-transparent file:text-sm file:font-medium file:text-primary',
        startIcon ? 'pl-8' : undefined,
        !startIcon && className,
      )}
      {...fieldProps}
    />
  )
  if (!startIcon) return input
  return (
    <div className={cn('relative w-full', className)}>
      <span
        aria-hidden="true"
        className="pointer-events-none absolute inset-y-0 left-2.5 flex items-center text-muted [&_svg]:size-4"
      >
        {startIcon}
      </span>
      {input}
    </div>
  )
}
