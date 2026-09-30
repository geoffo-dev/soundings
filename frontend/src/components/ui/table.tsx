import { ArrowDown, ArrowUp, ChevronsUpDown } from 'lucide-react'
import { createContext, use, type ComponentProps, type ReactNode, type Ref } from 'react'

import { cn } from '@/lib/utils'

/**
 * How a table behaves below `md` (768px):
 * - `scroll` (default): the table keeps its columns and scrolls sideways.
 * - `cards`: the header is hidden and every row becomes a stacked card; each
 *   cell shows its `label` above the value, and the `primary` cell (the title)
 *   spans the full width. Explicit ARIA roles keep the table semantics that
 *   `display: block/flex` would otherwise drop in some browsers.
 */
export type TableMobileLayout = 'scroll' | 'cards'

const TableLayout = createContext<TableMobileLayout>('scroll')

export interface TableProps extends ComponentProps<'table'> {
  mobile?: TableMobileLayout
  /** The scrolling wrapper, e.g. to give a virtualised table its own vertical scroll. */
  containerRef?: Ref<HTMLDivElement>
  containerClassName?: string
}

export function Table({
  className,
  mobile = 'scroll',
  containerRef,
  containerClassName,
  ...props
}: TableProps) {
  const cards = mobile === 'cards'
  return (
    <TableLayout value={mobile}>
      <div
        ref={containerRef}
        data-slot="table-container"
        className={cn(
          'relative w-full',
          cards ? 'md:overflow-x-auto' : 'overflow-x-auto',
          containerClassName,
        )}
      >
        <table
          role={cards ? 'table' : undefined}
          className={cn(
            'w-full caption-bottom border-collapse text-sm',
            cards && 'max-md:block',
            className,
          )}
          {...props}
        />
      </div>
    </TableLayout>
  )
}

export function TableHeader({ className, ...props }: ComponentProps<'thead'>) {
  const cards = use(TableLayout) === 'cards'
  return (
    <thead
      role={cards ? 'rowgroup' : undefined}
      className={cn(
        '[&_tr]:border-b [&_tr]:hover:bg-transparent',
        cards && 'max-md:sr-only',
        className,
      )}
      {...props}
    />
  )
}

export function TableBody({ className, ...props }: ComponentProps<'tbody'>) {
  const cards = use(TableLayout) === 'cards'
  return (
    <tbody
      role={cards ? 'rowgroup' : undefined}
      className={cn('[&_tr:last-child]:border-0', cards && 'max-md:block', className)}
      {...props}
    />
  )
}

export function TableRow({ className, ...props }: ComponentProps<'tr'>) {
  const cards = use(TableLayout) === 'cards'
  return (
    <tr
      role={cards ? 'row' : undefined}
      className={cn(
        'border-b border-subtle transition-colors duration-100 hover:bg-subtle data-[state=selected]:bg-accent-subtle',
        cards &&
          'max-md:flex max-md:flex-wrap max-md:items-center max-md:gap-x-4 max-md:gap-y-2 max-md:px-4 max-md:py-3',
        className,
      )}
      {...props}
    />
  )
}

export function TableHead({ className, ...props }: ComponentProps<'th'>) {
  const cards = use(TableLayout) === 'cards'
  return (
    <th
      role={cards ? 'columnheader' : undefined}
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

export interface TableCellProps extends ComponentProps<'td'> {
  /** Card layout: the column name shown above the value on phones. */
  label?: ReactNode
  /** Card layout: this cell (usually the title) takes the full card width. */
  primary?: boolean
}

export function TableCell({
  className,
  label,
  primary = false,
  children,
  ...props
}: TableCellProps) {
  const cards = use(TableLayout) === 'cards'
  return (
    <td
      role={cards ? 'cell' : undefined}
      className={cn(
        'h-11 px-3 align-middle text-primary first:pl-4 last:pr-4',
        cards && 'max-md:h-auto max-md:p-0 max-md:first:pl-0 max-md:last:pr-0',
        cards && primary && 'max-md:basis-full',
        cards && !primary && 'max-md:flex max-md:flex-col max-md:gap-0.5',
        className,
      )}
      {...props}
    >
      {cards && label && !primary && (
        <span aria-hidden="true" className="text-xs text-muted md:hidden">
          {label}
        </span>
      )}
      {children}
    </td>
  )
}

export function TableCaption({ className, ...props }: ComponentProps<'caption'>) {
  return <caption className={cn('mt-3 text-sm text-muted', className)} {...props} />
}
