import {
  closestCenter,
  DndContext,
  KeyboardSensor,
  MouseSensor,
  TouchSensor,
  useSensor,
  useSensors,
  type Announcements,
  type DragEndEvent,
} from '@dnd-kit/core'
import {
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { ArrowDown, ArrowUp, ArrowUpDown, GripVertical, Trash2 } from 'lucide-react'
import type { KeyboardEvent, ReactNode } from 'react'

import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { WithTooltip } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'

/**
 * A reorderable list of settings rows, as the rubric editor does it (Phase 8: the
 * proposal template and the research checklist): drag the handle (mouse, long press,
 * Space and the arrow keys, announced), Alt+↑/↓ in any field of a row, or the row's
 * Move menu (so reordering never needs a drag or a key combination, WCAG 2.5.7).
 */
export function SortableRows<T>({
  items,
  idOf,
  nameOf,
  label,
  onMove,
  children,
}: {
  items: readonly T[]
  idOf: (item: T) => string
  /** "Problem", or "Untitled section" while empty: what the announcements say. */
  nameOf: (item: T) => string
  /** The list's accessible name ("Sections"). */
  label: string
  onMove: (from: number, to: number) => void
  children: (item: T, index: number) => ReactNode
}) {
  const sensors = useSensors(
    useSensor(MouseSensor, { activationConstraint: { distance: 4 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 200, tolerance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  )
  const ids = items.map(idOf)
  const name = (id: string | number) => {
    const item = items.find((candidate) => idOf(candidate) === id)
    return item === undefined ? 'The row' : nameOf(item)
  }
  const position = (id: string | number) => ids.indexOf(String(id)) + 1
  const announcements: Announcements = {
    onDragStart: ({ active }) =>
      `Picked up ${name(active.id)}, position ${position(active.id)} of ${ids.length}.`,
    onDragOver: ({ active, over }) =>
      over ? `${name(active.id)} is over position ${position(over.id)}.` : undefined,
    onDragEnd: ({ active, over }) =>
      over
        ? `${name(active.id)} dropped at position ${position(over.id)} of ${ids.length}.`
        : `${name(active.id)} dropped.`,
    onDragCancel: ({ active }) => `Reordering cancelled. ${name(active.id)} is back.`,
  }
  const onDragEnd = ({ active, over }: DragEndEvent) => {
    if (!over || active.id === over.id) return
    onMove(position(active.id) - 1, position(over.id) - 1)
  }
  return (
    <DndContext
      sensors={sensors}
      collisionDetection={closestCenter}
      onDragEnd={onDragEnd}
      accessibility={{
        announcements,
        screenReaderInstructions: {
          draggable:
            'To reorder, press Space, use the up and down arrow keys, then press Space again to drop, or Escape to cancel. You can also press Alt with the up or down arrow in any field of a row.',
        },
      }}
    >
      <SortableContext items={ids} strategy={verticalListSortingStrategy}>
        <ol className="flex flex-col gap-3" aria-label={label}>
          {items.map((item, index) => children(item, index))}
        </ol>
      </SortableContext>
    </DndContext>
  )
}

/** Alt+↑/↓ from a field moves its row. */
export function moveKeysFor(index: number, onMove: (to: number) => void) {
  return {
    onKeyDown: (event: KeyboardEvent) => {
      if (!event.altKey || (event.key !== 'ArrowUp' && event.key !== 'ArrowDown')) return
      event.preventDefault()
      onMove(index + (event.key === 'ArrowUp' ? -1 : 1))
    },
  }
}

/**
 * One row: the drag handle, the row's fields (`children`), and Move + Remove at the end
 * (`controls`, placed by the row: beside the title on phones, at the end on wider screens).
 */
export function SortableRow({
  id,
  label,
  children,
}: {
  id: string
  /** The row's accessible name ("Problem"). */
  label: string
  children: ReactNode
}) {
  const {
    attributes,
    listeners,
    setNodeRef,
    setActivatorNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id })
  return (
    <li
      ref={setNodeRef}
      style={{ transform: CSS.Translate.toString(transform), transition }}
      aria-label={label}
      className={cn(
        'relative flex gap-2 rounded-lg border bg-surface p-3 pl-1.5',
        isDragging && 'z-10 border-strong shadow-raised',
      )}
    >
      <button
        type="button"
        ref={setActivatorNodeRef}
        {...attributes}
        {...listeners}
        aria-label={`Reorder ${label}`}
        className="flex h-8 w-6 shrink-0 cursor-grab touch-none items-center justify-center rounded-md text-muted transition-colors hover:bg-subtle hover:text-primary active:cursor-grabbing"
      >
        <GripVertical aria-hidden="true" className="size-4" />
      </button>
      <div className="flex min-w-0 flex-1 flex-col gap-3">{children}</div>
    </li>
  )
}

/** Move (a menu with Move up / Move down) and Remove for a row. */
export function RowControls({
  label,
  index,
  count,
  onMove,
  onRemove,
  removeDisabledReason,
  className,
}: {
  label: string
  index: number
  count: number
  onMove: (to: number) => void
  onRemove: () => void
  /** Why Remove is off ("A template needs at least 1 section"); undefined while allowed. */
  removeDisabledReason?: string
  className?: string
}) {
  const keys = moveKeysFor(index, onMove)
  return (
    <div className={cn('flex items-center gap-0.5', className)}>
      <DropdownMenu>
        <WithTooltip content={`Move ${label}`}>
          <DropdownMenuTrigger asChild>
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label={`Move ${label}`}
              disabled={count < 2}
              {...keys}
            >
              <ArrowUpDown />
            </Button>
          </DropdownMenuTrigger>
        </WithTooltip>
        <DropdownMenuContent align="end">
          <DropdownMenuItem disabled={index === 0} onSelect={() => onMove(index - 1)}>
            <ArrowUp /> Move up
          </DropdownMenuItem>
          <DropdownMenuItem disabled={index === count - 1} onSelect={() => onMove(index + 1)}>
            <ArrowDown /> Move down
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      <WithTooltip content={removeDisabledReason ?? `Remove ${label}`}>
        <span>
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label={`Remove ${label}`}
            disabled={removeDisabledReason !== undefined}
            onClick={onRemove}
            {...keys}
          >
            <Trash2 />
          </Button>
        </span>
      </WithTooltip>
    </div>
  )
}
