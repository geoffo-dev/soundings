import { CalendarDays } from 'lucide-react'
import { useState } from 'react'

import { useSetEvaluationDueDate } from '@/api/ideas'
import { Button } from '@/components/ui/button'
import { DatePicker } from '@/components/ui/date-picker'
import { DueDateLabel } from '@/components/ui/due-date'
import { Field } from '@/components/ui/field'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { dueDate, formatDate, formatDateTime } from '@/lib/dates'

import { dateInputInDays, fromDateInput, toDateInput, todayInput } from './due-date'
import { useIdeaPage } from './idea-context'

const QUICK_PICKS = [
  { days: 3, label: 'In 3 days' },
  { days: 7, label: 'In a week' },
  { days: 14, label: 'In 2 weeks' },
] as const

/**
 * The evaluation due date: a label for everyone, a small editor for the owner
 * and admins while evaluation is open (`idea.set_due_date` has the same
 * conditions as inviting, so `can_invite_evaluators` decides).
 */
export function DueDateField() {
  const { idea } = useIdeaPage()
  const [open, setOpen] = useState(false)
  const { submitted, total } = idea.evaluator_progress
  // Once everyone has submitted (or evaluation ended) the date is history, not a warning.
  const settled = !idea.evaluation_open || (total > 0 && submitted >= total)
  const label =
    settled && idea.evaluation_due_at ? (
      <span
        title={formatDateTime(idea.evaluation_due_at)}
        className="inline-flex items-center gap-1.5 text-sm whitespace-nowrap text-muted"
      >
        <CalendarDays aria-hidden="true" className="size-3.5 shrink-0" />
        {formatDate(idea.evaluation_due_at)}
      </span>
    ) : (
      <DueDateLabel value={idea.evaluation_due_at} />
    )
  if (!idea.permissions.can_invite_evaluators) return label
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="ghost"
          size="sm"
          className="-ml-2 font-normal"
          aria-label={`${
            settled && idea.evaluation_due_at
              ? `Due ${formatDate(idea.evaluation_due_at)}`
              : dueDate(idea.evaluation_due_at).label
          }. Change due date`}
        >
          {label}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" collisionPadding={16} className="w-72">
        {open && <DueDateEditor onDone={() => setOpen(false)} />}
      </PopoverContent>
    </Popover>
  )
}

function DueDateEditor({ onDone }: { onDone: () => void }) {
  const { idea, ideaKey } = useIdeaPage()
  const setDueDate = useSetEvaluationDueDate(ideaKey)
  const current = toDateInput(idea.evaluation_due_at)
  const [value, setValue] = useState(current)

  const save = (next: string) => {
    onDone()
    if (next === current) return
    setDueDate.mutate(next ? fromDateInput(next) : null)
  }

  return (
    <form
      className="flex flex-col gap-3"
      onSubmit={(event) => {
        event.preventDefault()
        save(value)
      }}
    >
      <Field label="Due date" description="Evaluators see it in My work.">
        <DatePicker value={value} onValueChange={setValue} min={todayInput()} className="w-full" />
      </Field>
      <div className="flex flex-wrap gap-1.5">
        {QUICK_PICKS.map((pick) => (
          <Button
            key={pick.days}
            type="button"
            size="sm"
            variant="outline"
            onClick={() => setValue(dateInputInDays(pick.days))}
          >
            {pick.label}
          </Button>
        ))}
      </div>
      <div className="flex items-center justify-between gap-2 border-t border-subtle pt-3">
        {current ? (
          <Button
            type="button"
            size="sm"
            variant="ghost"
            className="-ml-1"
            onClick={() => save('')}
          >
            Remove due date
          </Button>
        ) : (
          <span />
        )}
        <Button type="submit" size="sm" variant="primary" disabled={!value || value === current}>
          Save
        </Button>
      </div>
    </form>
  )
}
