import { Switch as SwitchPrimitive } from 'radix-ui'
import type { ComponentProps } from 'react'

import { useFieldControl } from '@/components/ui/field'
import { cn } from '@/lib/utils'

export interface SwitchProps extends ComponentProps<typeof SwitchPrimitive.Root> {
  /**
   * The last change is being saved: presses are ignored until it is, but the switch
   * keeps focus (`aria-disabled`, not `disabled`, which would drop it to `<body>`).
   */
  pending?: boolean
}

export function Switch({ className, pending = false, ...props }: SwitchProps) {
  const fieldProps = useFieldControl(props)
  const busy = pending && !props.disabled
  return (
    <SwitchPrimitive.Root
      data-slot="switch"
      className={cn(
        'peer relative inline-flex h-5 w-8 shrink-0 items-center rounded-full border border-transparent p-px',
        'transition-colors duration-150 disabled:cursor-not-allowed disabled:opacity-50',
        'aria-busy:cursor-progress',
        'data-[state=checked]:bg-accent data-[state=unchecked]:bg-control',
        'after:absolute after:-inset-1.5 after:content-[""]',
        className,
      )}
      {...fieldProps}
      aria-disabled={busy || fieldProps['aria-disabled']}
      aria-busy={busy || undefined}
      onClick={(event) => {
        // Radix toggles on click: a prevented click changes nothing.
        if (busy) event.preventDefault()
        fieldProps.onClick?.(event)
      }}
      onCheckedChange={(checked) => {
        if (!busy) fieldProps.onCheckedChange?.(checked)
      }}
    >
      <SwitchPrimitive.Thumb
        className={cn(
          'pointer-events-none block size-4 rounded-full bg-white shadow-[0_1px_2px_rgb(0_0_0/0.2)]',
          'transition-transform duration-150 ease-out data-[state=checked]:translate-x-3 data-[state=unchecked]:translate-x-0',
        )}
      />
    </SwitchPrimitive.Root>
  )
}
