import { Check, Minus } from 'lucide-react'
import { Checkbox as CheckboxPrimitive } from 'radix-ui'
import type { ComponentProps } from 'react'

import { useFieldControl } from '@/components/ui/field'
import { cn } from '@/lib/utils'

export function Checkbox({ className, ...props }: ComponentProps<typeof CheckboxPrimitive.Root>) {
  const fieldProps = useFieldControl(props)
  return (
    <CheckboxPrimitive.Root
      data-slot="checkbox"
      className={cn(
        'peer inline-flex size-4 shrink-0 items-center justify-center rounded-sm border border-control bg-surface text-accent-foreground',
        'transition-[background-color,border-color] duration-150',
        'hover:bg-subtle disabled:cursor-not-allowed disabled:opacity-50',
        'data-[state=checked]:border-accent data-[state=checked]:bg-accent data-[state=indeterminate]:border-accent data-[state=indeterminate]:bg-accent',
        'aria-invalid:border-danger',
        // Larger hit area without changing the visual size.
        'relative after:absolute after:-inset-2 after:content-[""]',
        className,
      )}
      {...fieldProps}
    >
      <CheckboxPrimitive.Indicator className="group flex items-center justify-center">
        <Check strokeWidth={3} className="size-3 group-data-[state=indeterminate]:hidden" />
        <Minus strokeWidth={3} className="hidden size-3 group-data-[state=indeterminate]:block" />
      </CheckboxPrimitive.Indicator>
    </CheckboxPrimitive.Root>
  )
}
