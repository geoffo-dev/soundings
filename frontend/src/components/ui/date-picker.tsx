import { CalendarDays } from 'lucide-react'
import type { ComponentProps } from 'react'

import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'

export interface DatePickerProps extends Omit<
  ComponentProps<'input'>,
  'type' | 'value' | 'onChange'
> {
  /** ISO date `YYYY-MM-DD`, or '' for none. */
  value: string
  onValueChange: (value: string) => void
}

/**
 * Native date input, styled. Native gives us locale formatting, keyboard entry
 * and a mobile-friendly picker for free.
 */
export function DatePicker({ value, onValueChange, className, ...props }: DatePickerProps) {
  return (
    <Input
      type="date"
      value={value}
      onChange={(event) => onValueChange(event.target.value)}
      onClick={(event) => {
        // Open the picker on click anywhere in the field (Chromium hides it behind the icon).
        try {
          event.currentTarget.showPicker()
        } catch {
          // Not supported or not allowed — typing still works.
        }
      }}
      startIcon={<CalendarDays />}
      className={cn('w-44 [&_input::-webkit-calendar-picker-indicator]:hidden', className)}
      {...props}
    />
  )
}
