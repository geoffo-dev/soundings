import { ArrowDown, ArrowUp, ChevronsUpDown } from 'lucide-react'
import { createContext, use, type ComponentProps, type ReactNode, type Ref } from 'react'

import { cn } from '@/lib/utils'

/**
 * How a table behaves when it is narrow:
 * - `scroll` (default): the table keeps its columns and scrolls sideways.
 * - `cards`: below `md` (768px viewport) the header is hidden and every row
 *   becomes a stacked card; each cell shows its `label` above the value, and
 *   the `primary` cell (the title) spans the full width. Explicit ARIA roles
 *   keep the table semantics that `display: block/flex` would otherwise drop
 *   in some browsers.
 * - `container-cards`: the same cards, but whenever the table's own container
 *   is narrower than 48rem (768px) — for tables that share the screen with a
 *   sidebar, where the viewport says little about the room left. The
 *   container is a CSS container, so cells can also use `@3xl:` / `@max-3xl:`
 *   (and wider) variants to hide columns as the table narrows.
 */
export type TableMobileLayout = 'scroll' | 'cards' | 'container-cards'

type CardLayout = Exclude<TableMobileLayout, 'scroll'>

/** The card styles per layout (static class names, so Tailwind generates them). */
const CARDS: Record<
  CardLayout,
  {
    container: string
    table: string
    header: string
    body: string
    row: string
    cell: string
    primary: string
    field: string
    label: string
  }
> = {
  cards: {
    container: 'md:overflow-x-auto',
    table: 'max-md:block',
    header: 'max-md:sr-only',
    body: 'max-md:block',
    row: 'max-md:flex max-md:flex-wrap max-md:items-center max-md:gap-x-4 max-md:gap-y-2 max-md:px-4 max-md:py-3',
    cell: 'max-md:h-auto max-md:p-0 max-md:first:pl-0 max-md:last:pr-0',
    primary: 'max-md:basis-full',
    field: 'max-md:flex max-md:flex-col max-md:gap-0.5',
    label: 'md:hidden',
  },
  'container-cards': {
    container: '@container overflow-x-auto',
    table: '@max-3xl:block',
    header: '@max-3xl:sr-only',
    body: '@max-3xl:block',
    row: '@max-3xl:flex @max-3xl:flex-wrap @max-3xl:items-center @max-3xl:gap-x-4 @max-3xl:gap-y-2 @max-3xl:px-4 @max-3xl:py-3',
    cell: '@max-3xl:h-auto @max-3xl:p-0 @max-3xl:first:pl-0 @max-3xl:last:pr-0',
    primary: '@max-3xl:basis-full',
    field: '@max-3xl:flex @max-3xl:flex-col @max-3xl:gap-0.5',
    label: '@3xl:hidden',
  },
}

const TableLayout = createContext<TableMobileLayout>('scroll')

/** The card styles of the table around, or null for a plain (scrolling) table. */
function useCards() {
  const layout = use(TableLayout)
  return layout === 'scroll' ? null : CARDS[layout]
}

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
  const cards = mobile === 'scroll' ? null : CARDS[mobile]
  return (
    <TableLayout value={mobile}>
      <div
        ref={containerRef}
        data-slot="table-container"
        className={cn(
          'relative w-full',
          cards ? cards.container : 'overflow-x-auto',
          containerClassName,
        )}
      >
        <table
          role={cards ? 'table' : undefined}
          className={cn('w-full caption-bottom border-collapse text-sm', cards?.table, className)}
          {...props}
        />
      </div>
    </TableLayout>
  )
}

export function TableHeader({ className, ...props }: ComponentProps<'thead'>) {
  const cards = useCards()
  return (
    <thead
      role={cards ? 'rowgroup' : undefined}
      className={cn('[&_tr]:border-b [&_tr]:hover:bg-transparent', cards?.header, className)}
      {...props}
    />
  )
}

export function TableBody({ className, ...props }: ComponentProps<'tbody'>) {
  const cards = useCards()
  return (
    <tbody
      role={cards ? 'rowgroup' : undefined}
      className={cn('[&_tr:last-child]:border-0', cards?.body, className)}
      {...props}
    />
  )
}

export function TableRow({ className, ...props }: ComponentProps<'tr'>) {
  const cards = useCards()
  return (
    <tr
      role={cards ? 'row' : undefined}
      className={cn(
        'border-b border-subtle transition-colors duration-100 hover:bg-subtle data-[state=selected]:bg-accent-subtle',
        cards?.row,
        className,
      )}
      {...props}
    />
  )
}

export function TableHead({ className, ...props }: ComponentProps<'th'>) {
  const cards = useCards()
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
  const cards = useCards()
  return (
    <td
      role={cards ? 'cell' : undefined}
      className={cn(
        'h-11 px-3 align-middle text-primary first:pl-4 last:pr-4',
        cards?.cell,
        cards && (primary ? cards.primary : cards.field),
        className,
      )}
      {...props}
    >
      {cards && label && !primary && (
        <span aria-hidden="true" className={cn('text-xs text-muted', cards.label)}>
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
