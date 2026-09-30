import { ArrowDown, ArrowUp, ChevronsUpDown } from 'lucide-react'
import type { ComponentProps } from 'react'

import { cn } from '@/lib/utils'

export function Table({ className, ...props }: ComponentProps<'table'>) {
  return (
    <div data-slot="table-container" className="relative w-full overflow-x-auto">
      <table
        className={cn('w-full caption-bottom border-collapse text-sm', className)}
        {...props}
      />
    </div>
  )
}

export function TableHeader({ className, ...props }: ComponentProps<'thead'>) {
  return (
    <thead className={cn('[&_tr]:border-b [&_tr]:hover:bg-transparent', className)} {...props} />
  )
}

export function TableBody({ className, ...props }: ComponentProps<'tbody'>) {
  return <tbody className={cn('[&_tr:last-child]:border-0', className)} {...props} />
}

export function TableRow({ className, ...props }: ComponentProps<'tr'>) {
  return (
    <tr
      className={cn(
        'border-b border-subtle transition-colors duration-100 hover:bg-subtle data-[state=selected]:bg-accent-subtle',
        className,
      )}
      {...props}
    />
  )
}

export function TableHead({ className, ...props }: ComponentProps<'th'>) {
  return (
    <th
      className={cn(
        'h-9 px-3 text-left align-middle text-xs font-medium whitespace-nowrap text-muted first:pl-4 last:pr-4',
        className,
      )}
      {...props}
    />
  )
}

export type SortDirection = 'asc' | 'desc'

export interface SortableTableHeadProps extends Omit<ComponentProps<'th'>, 'onClick'> {
  /** Current direction if the table is sorted by this column, otherwise false. */
  sorted: SortDirection | false
  onSort: () => void
  align?: 'left' | 'right'
}

/** Column header that toggles sorting; announces state via aria-sort. */
export function SortableTableHead({
  sorted,
  onSort,
  align = 'left',
  className,
  children,
  ...props
}: SortableTableHeadProps) {
  const Icon = sorted === 'asc' ? ArrowUp : sorted === 'desc' ? ArrowDown : ChevronsUpDown
  return (
    <TableHead
      aria-sort={sorted === 'asc' ? 'ascending' : sorted === 'desc' ? 'descending' : 'none'}
      className={cn(align === 'right' && 'text-right', className)}
      {...props}
    >
      <button
        type="button"
        onClick={onSort}
        className={cn(
          'group -mx-1.5 inline-flex h-7 items-center gap-1 rounded-md px-1.5 transition-colors hover:bg-subtle hover:text-primary',
          sorted && 'text-primary',
          align === 'right' && 'flex-row-reverse',
        )}
      >
        {children}
        <Icon
          aria-hidden="true"
          className={cn(
            'size-3.5 transition-opacity',
            sorted
              ? 'opacity-100'
              : 'opacity-0 group-hover:opacity-100 group-focus-visible:opacity-100',
          )}
        />
      </button>
    </TableHead>
  )
}

export function TableCell({ className, ...props }: ComponentProps<'td'>) {
  return (
    <td
      className={cn('h-11 px-3 align-middle text-primary first:pl-4 last:pr-4', className)}
      {...props}
    />
  )
}

export function TableCaption({ className, ...props }: ComponentProps<'caption'>) {
  return <caption className={cn('mt-3 text-sm text-muted', className)} {...props} />
}
