import { Check, ChevronDown, X } from 'lucide-react'
import { useState, type ReactNode } from 'react'

import { CommandItem } from '@/components/ui/command'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { cn } from '@/lib/utils'

const chip = cn(
  'inline-flex h-7 shrink-0 items-center rounded-md border text-sm whitespace-nowrap',
  'transition-[background-color,border-color,color] duration-150',
)

export interface FilterMenuProps {
  label: string
  icon: ReactNode
  /** Human-readable value; undefined when the filter is off. */
  value: ReactNode
  onClear: () => void
  /** The menu (usually a `Command` list); `close` closes it after a single choice. */
  children: (close: () => void) => ReactNode
  /** Width class of the menu (default `w-64`). */
  menuClassName?: string
}

/**
 * A filter chip with a menu: "Owner ▾" when unset, "Owner · Alice Anders ▾ ×"
 * when set (the × clears it). Same look as the project filter bar's chips.
 */
export function FilterMenu({
  label,
  icon,
  value,
  onClear,
  children,
  menuClassName,
}: FilterMenuProps) {
  const [open, setOpen] = useState(false)
  const active = value !== undefined && value !== null
  return (
    <span
      data-slot="filter-menu"
      className={cn(
        chip,
        active
          ? 'border-accent/40 bg-accent-subtle text-accent'
          : 'bg-surface text-secondary hover:border-strong hover:text-primary',
      )}
    >
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <button
            type="button"
            className={cn(
              'inline-flex h-full items-center gap-1.5 rounded-md pr-1.5 pl-2.5 font-medium',
              'data-[state=open]:bg-subtle [&_svg]:size-3.5 [&_svg]:shrink-0',
              active && 'rounded-r-none pr-2',
            )}
          >
            {icon}
            {label}
            {active && (
              <>
                <span aria-hidden="true" className="text-accent/60">
                  ·
                </span>
                <span className="max-w-40 truncate">{value}</span>
              </>
            )}
            <ChevronDown aria-hidden="true" className="opacity-60" />
          </button>
        </PopoverTrigger>
        <PopoverContent
          className={cn('w-64 p-0', menuClassName)}
          align="start"
          aria-label={`Filter by ${label.toLowerCase()}`}
        >
          {children(() => setOpen(false))}
        </PopoverContent>
      </Popover>
      {active && (
        <button
          type="button"
          aria-label={`Remove ${label.toLowerCase()} filter`}
          onClick={onClear}
          className="inline-flex h-full w-7 items-center justify-center rounded-r-md border-l border-accent/25 transition-colors hover:bg-accent/10"
        >
          <X aria-hidden="true" className="size-3.5" />
        </button>
      )}
    </span>
  )
}

/**
 * A checkable row in a filter menu. With a `description` the row grows to two
 * lines (the label, then the description muted), instead of overflowing the
 * menu's one-line row height.
 */
export function FilterMenuOption({
  value,
  checked,
  onSelect,
  children,
  description,
  keywords,
}: {
  value: string
  checked: boolean
  onSelect: () => void
  children: ReactNode
  /** A second, muted line under the label. */
  description?: ReactNode
  keywords?: string[]
}) {
  return (
    <CommandItem
      value={value}
      keywords={keywords}
      onSelect={onSelect}
      aria-checked={checked}
      className={cn('gap-2', description !== undefined && 'h-auto py-1.5 sm:h-auto')}
    >
      {description !== undefined ? (
        <span className="flex min-w-0 flex-col">
          <span>{children}</span>
          <span className="text-xs text-muted">{description}</span>
        </span>
      ) : (
        children
      )}
      <Check
        aria-hidden="true"
        className={cn('ml-auto text-accent!', checked ? 'opacity-100' : 'opacity-0')}
      />
    </CommandItem>
  )
}
