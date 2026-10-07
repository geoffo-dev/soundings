import { RadioGroup as RadioGroupPrimitive } from 'radix-ui'
import type { ComponentProps } from 'react'

import { useFieldContext } from '@/components/ui/field'
import { pressSubmitShortcut } from '@/components/ui/submit-shortcut'
import { cn } from '@/lib/utils'

export function RadioGroup({
  className,
  ...props
}: ComponentProps<typeof RadioGroupPrimitive.Root>) {
  const field = useFieldContext()
  return (
    <RadioGroupPrimitive.Root
      data-slot="radio-group"
      aria-labelledby={field?.labelId}
      aria-describedby={field?.describedBy}
      className={cn('grid gap-2.5', className)}
      {...props}
    />
  )
}

export function RadioGroupItem({
  className,
  onKeyDown,
  ...props
}: ComponentProps<typeof RadioGroupPrimitive.Item>) {
  return (
    <RadioGroupPrimitive.Item
      onKeyDown={(event) => {
        onKeyDown?.(event)
        // Mod+Enter still submits the form (Radix swallows Enter on radios).
        if (!event.defaultPrevented) pressSubmitShortcut(event)
      }}
      data-slot="radio-group-item"
      className={cn(
        'peer relative inline-flex size-4 shrink-0 items-center justify-center rounded-full border border-control bg-surface',
        'transition-[border-color] duration-150 hover:bg-subtle disabled:cursor-not-allowed disabled:opacity-50',
        'data-[state=checked]:border-accent-control',
        'after:absolute after:-inset-2 after:content-[""]',
        className,
      )}
      {...props}
    >
      <RadioGroupPrimitive.Indicator className="size-2 rounded-full bg-accent-control" />
    </RadioGroupPrimitive.Item>
  )
}
