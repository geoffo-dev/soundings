import { CalendarDays, CalendarX2, Clock, TriangleAlert } from 'lucide-react'

import { useNow } from '@/components/ui/relative-time'
import { WithTooltip } from '@/components/ui/tooltip'
import { dueDate, type DateInput, type DueTone } from '@/lib/dates'
import { cn } from '@/lib/utils'

const TONE: Record<DueTone, { className: string; Icon: typeof Clock }> = {
  overdue: { className: 'text-danger', Icon: TriangleAlert },
  soon: { className: 'text-warning', Icon: Clock },
  later: { className: 'text-muted', Icon: CalendarDays },
  none: { className: 'text-muted', Icon: CalendarX2 },
}

export interface DueDateLabelProps {
  value: DateInput | null | undefined
  className?: string
  /** Hide the "No due date" text (show nothing instead). */
  hideWhenNone?: boolean
}

/**
 * "Due tomorrow" / "Due Fri 3 Oct" / "Overdue 2 days" with an icon, so the
 * state is never colour alone. The full date and time is in a tooltip.
 */
export function DueDateLabel({ value, className, hideWhenNone = false }: DueDateLabelProps) {
  const now = useNow()
  const due = dueDate(value, { now })
  if (due.tone === 'none' && hideWhenNone) return null
  const { className: tone, Icon } = TONE[due.tone]
  const label = (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 text-sm whitespace-nowrap',
        tone,
        due.tone === 'overdue' && 'font-medium',
        className,
      )}
    >
      <Icon aria-hidden="true" className="size-3.5 shrink-0" />
      {due.label}
    </span>
  )
  return due.full ? <WithTooltip content={due.full}>{label}</WithTooltip> : label
}
