import { Plus, X } from 'lucide-react'
import type { ComponentProps, ReactNode } from 'react'

import { cn } from '@/lib/utils'

const chipBase = cn(
  'inline-flex h-7 shrink-0 items-center gap-1.5 rounded-md border px-2.5 text-sm font-medium whitespace-nowrap',
  'transition-[background-color,border-color,color] duration-150',
  "[&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-3.5",
)

export interface FilterChipProps extends Omit<ComponentProps<'button'>, 'onChange'> {
  pressed: boolean
  onPressedChange: (pressed: boolean) => void
  icon?: ReactNode
  /** Optional count of matching items. */
  count?: number
}

/** Quick on/off filter, e.g. "Needs evaluators" or "High disagreement". */
export function FilterChip({
  pressed,
  onPressedChange,
  icon,
  count,
  className,
  children,
  ...props
}: FilterChipProps) {
  return (
    <button
      type="button"
      aria-pressed={pressed}
      onClick={() => onPressedChange(!pressed)}
      className={cn(
        chipBase,
        pressed
          ? 'border-accent/40 bg-accent-subtle text-accent'
          : 'bg-surface text-secondary hover:border-strong hover:text-primary',
        className,
      )}
      {...props}
    >
      {icon}
      {children}
      {count !== undefined && (
        <span className={cn('tabular-nums', pressed ? 'text-accent' : 'text-muted')}>{count}</span>
      )}
    </button>
  )
}

export interface FilterValueChipProps {
  /** Field being filtered, e.g. "Status". */
  field: string
  /** Human-readable value(s), e.g. "Evaluating, Shortlisted". */
  value: ReactNode
  icon?: ReactNode
  /** Open the value editor (typically a Popover trigger). */
  onEdit?: () => void
  onRemove: () => void
  className?: string
}

/** An applied filter: "Status  Evaluating ×". The value is editable, the × removes it. */
export function FilterValueChip({
  field,
  value,
  icon,
  onEdit,
  onRemove,
  className,
}: FilterValueChipProps) {
  return (
    <span
      data-slot="filter-value-chip"
      className={cn(
        'inline-flex h-7 shrink-0 items-stretch overflow-hidden rounded-md border bg-surface text-sm whitespace-nowrap',
        className,
      )}
    >
      <span className="inline-flex items-center gap-1.5 border-r border-subtle pr-2 pl-2.5 text-muted [&_svg]:size-3.5">
        {icon}
        {field}
      </span>
      <button
        type="button"
        onClick={onEdit}
        disabled={!onEdit}
        className="inline-flex items-center px-2 font-medium text-primary transition-colors hover:bg-subtle disabled:cursor-default disabled:hover:bg-transparent"
      >
        {value}
      </button>
      <button
        type="button"
        onClick={onRemove}
        aria-label={`Remove ${field} filter`}
        className="inline-flex w-7 items-center justify-center border-l border-subtle text-muted transition-colors hover:bg-subtle hover:text-primary"
      >
        <X className="size-3.5" />
      </button>
    </span>
  )
}

/** Dashed "add filter" affordance; usually the trigger of a filter menu. */
export function AddFilterChip({
  className,
  children = 'Filter',
  ...props
}: ComponentProps<'button'>) {
  return (
    <button
      type="button"
      className={cn(
        chipBase,
        'border-dashed border-strong bg-transparent text-muted hover:border-solid hover:bg-subtle hover:text-primary data-[state=open]:bg-subtle',
        className,
      )}
      {...props}
    >
      <Plus />
      {children}
    </button>
  )
}
