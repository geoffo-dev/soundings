import {
  DndContext,
  DragOverlay,
  KeyboardSensor,
  MouseSensor,
  pointerWithin,
  rectIntersection,
  TouchSensor,
  useSensor,
  useSensors,
  type Announcements,
  type CollisionDetection,
  type DragEndEvent,
  type DragStartEvent,
} from '@dnd-kit/core'
import { useCallback, useRef, useState, type FocusEvent } from 'react'

import { useChangeIdeaStatus } from '@/api/ideas'
import type { Board, IdeaFilters, IdeaStatus, IdeaSummary, Project, Resolution } from '@/api/types'
import { Popover, PopoverAnchor, PopoverContent } from '@/components/ui/popover'
import { StatusDot } from '@/components/ui/status-badge'
import { Kbd } from '@/components/ui/kbd'
import { useListNavigation } from '@/lib/list-navigation'
import { CLOSED_RESOLUTIONS } from '@/lib/status'
import { cn } from '@/lib/utils'

import { CardBody, type CardDragData } from './board-card'
import { BoardColumn, columnId } from './board-column'
import { BoardFocusContext, createBoardFocus } from './board-focus'
import { columnCoordinates, type ColumnDropData } from './keyboard'

const INSTRUCTIONS =
  'Press Enter to open this idea. To change its status, press Space to pick it up, ' +
  'use the left and right arrow keys to choose a column, then press Space again to drop it, ' +
  'or Escape to cancel.'

/** The column a keyboard move is heading for (one drag at a time, app-wide). */
const keyboardTarget: { current: string | null } = { current: null }
const keyboardCoordinates = columnCoordinates(keyboardTarget)

/** Mouse first; keyboard moves have no pointer, so fall back to overlap. */
const collisions: CollisionDetection = (args) => {
  const hits = pointerWithin(args)
  return hits.length > 0 ? hits : rectIntersection(args)
}

/** `column:new` → `new` (keyboard moves track their target column by id). */
const statusOfColumn = (id: string | null) =>
  id?.startsWith('column:') ? (id.slice('column:'.length) as IdeaStatus) : undefined

const cardOf = (data: unknown) => (data as CardDragData | undefined)?.idea
const statusOf = (data: unknown) =>
  (data as ColumnDropData | undefined)?.status as IdeaStatus | undefined

/**
 * The Board (SPEC §5 screen 2): five columns by status with the project's
 * labels. Owners and admins drag cards between columns (mouse, long press,
 * or Space + arrow keys, announced to screen readers); dropping on Closed asks
 * how it was closed. Moves are optimistic with an Undo toast.
 */
export function BoardView({
  project,
  board,
  filters,
  stale = false,
}: {
  project: Project
  board: Board
  filters: IdeaFilters
  /** Showing the previous results while new filters load. */
  stale?: boolean
}) {
  const labels = project.status_labels
  const move = useChangeIdeaStatus()
  const [focus] = useState(createBoardFocus)
  const [dragging, setDragging] = useState<IdeaSummary | null>(null)
  const [closing, setClosing] = useState<IdeaSummary | null>(null)
  // The lifted card keeps the width of the card you picked up.
  const [liftedWidth, setLiftedWidth] = useState<number | undefined>()
  const [closedExpanded, setClosedExpanded] = useClosedExpanded(project.slug)
  const { listRef } = useListNavigation({ enabled: !dragging && !closing })
  const suppressClickUntil = useRef(0)
  // Whether the card being moved has left its own column yet (for announcements),
  // and whether the move is a keyboard one (its target is `keyboardTarget`, not the collision).
  const leftOrigin = useRef(false)
  const keyboardMove = useRef(false)
  // The card waiting for a resolution, and whether one was chosen (for focus afterwards).
  const picker = useRef<{ idea: IdeaSummary; chosen: boolean } | null>(null)

  const sensors = useSensors(
    useSensor(MouseSensor, { activationConstraint: { distance: 6 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 250, tolerance: 8 } }),
    useSensor(KeyboardSensor, {
      coordinateGetter: keyboardCoordinates,
      keyboardCodes: { start: ['Space'], cancel: ['Escape'], end: ['Space', 'Enter'] },
    }),
  )

  const labelOf = (status: IdeaStatus | undefined) => (status ? labels[status] : 'no column')

  const announcements: Announcements = {
    onDragStart: ({ active }) => {
      const idea = cardOf(active.data.current)
      return idea ? `Picked up ${idea.key}, ${idea.title}, in ${labelOf(idea.status)}.` : undefined
    },
    onDragOver: ({ active, over }) => {
      const idea = cardOf(active.data.current)
      if (!idea) return undefined
      const to = statusOf(over?.data.current)
      // Don't talk over "Picked up…" while the card is still in its own column.
      if (!leftOrigin.current && to === idea.status) return undefined
      leftOrigin.current = true
      return to ? `${idea.key} is over ${labelOf(to)}.` : `${idea.key} is not over a column.`
    },
    onDragEnd: ({ active, over }) => {
      const idea = cardOf(active.data.current)
      const to = dropTarget(over?.data.current)
      if (!idea) return undefined
      if (!to || to === idea.status) return `${idea.key} stays in ${labelOf(idea.status)}.`
      if (to === 'closed')
        return `${idea.key} dropped on ${labels.closed}. Choose how it was closed.`
      return `${idea.key} moved to ${labelOf(to)}.`
    },
    onDragCancel: ({ active }) => {
      const idea = cardOf(active.data.current)
      return idea ? `Move cancelled. ${idea.key} stays in ${labelOf(idea.status)}.` : undefined
    },
  }

  const onDragStart = ({ active, activatorEvent }: DragStartEvent) => {
    const idea = cardOf(active.data.current) ?? null
    keyboardTarget.current = idea ? columnId(idea.status) : null
    keyboardMove.current = activatorEvent instanceof KeyboardEvent
    leftOrigin.current = false
    setLiftedWidth(active.rect.current.initial?.width)
    setDragging(idea)
  }

  // Keyboard moves drop where the arrow keys pointed, even if collision detection lags a frame.
  const dropTarget = (overData: unknown) =>
    keyboardMove.current ? statusOfColumn(keyboardTarget.current) : statusOf(overData)

  const onDragEnd = ({ active, over, activatorEvent }: DragEndEvent) => {
    setDragging(null)
    suppressClickUntil.current = performance.now() + 250
    const idea = cardOf(active.data.current)
    const to = dropTarget(over?.data.current)
    if (!idea || !to || to === idea.status) return
    if (to === 'closed') {
      picker.current = { idea, chosen: false }
      setClosing(idea)
      return
    }
    // Keyboard moves keep focus on the card in its new column.
    if (activatorEvent instanceof KeyboardEvent) focus.request(idea.id)
    move.mutate({ idea: idea.key, status: to })
  }

  const close = (idea: IdeaSummary, resolution: Resolution) => {
    if (picker.current) picker.current.chosen = true
    focus.request(idea.id)
    setClosing(null)
    move.mutate({ idea: idea.key, status: 'closed', resolution })
  }

  // A drag that ends over a card must not also open it.
  const containerRef = useCallback(
    (node: HTMLDivElement | null) => {
      const cleanupNav = listRef(node)
      if (!node) return cleanupNav
      const onClick = (event: MouseEvent) => {
        if (performance.now() < suppressClickUntil.current) {
          event.preventDefault()
          event.stopPropagation()
        }
      }
      node.addEventListener('click', onClick, true)
      return () => {
        cleanupNav?.()
        node.removeEventListener('click', onClick, true)
      }
    },
    [listRef],
  )

  return (
    <BoardFocusContext value={focus}>
      <DndContext
        sensors={sensors}
        collisionDetection={collisions}
        onDragStart={onDragStart}
        onDragEnd={onDragEnd}
        onDragCancel={() => setDragging(null)}
        accessibility={{ announcements, screenReaderInstructions: { draggable: INSTRUCTIONS } }}
      >
        <Popover
          open={closing !== null}
          onOpenChange={(open) => {
            if (!open) setClosing(null)
          }}
        >
          <div
            ref={containerRef}
            aria-busy={stale || undefined}
            onFocus={revealFocusedColumn}
            className={cn(
              'transition-opacity duration-150',
              stale && 'opacity-60',
              '-mx-4 flex min-h-0 flex-1 snap-x snap-mandatory scroll-px-4 items-stretch gap-3 overflow-x-auto px-4 pb-2',
              'sm:mx-0 sm:snap-none sm:px-0',
            )}
          >
            {board.columns.map((column) => {
              const closed = column.status === 'closed'
              return (
                <BoardColumn
                  key={column.status}
                  slug={project.slug}
                  column={column}
                  filters={filters}
                  labels={labels}
                  canDrop={dragging !== null && dragging.status !== column.status}
                  collapsed={closed && !closedExpanded}
                  onToggleCollapsed={closed ? () => setClosedExpanded(!closedExpanded) : undefined}
                  headerAnchor={
                    closed ? (header) => <PopoverAnchor asChild>{header}</PopoverAnchor> : undefined
                  }
                />
              )
            })}
          </div>
          <PopoverContent
            align="end"
            className="w-60 p-1.5"
            aria-label={closing ? `Close ${closing.key} as` : undefined}
            onCloseAutoFocus={(event) => {
              // Back to the card: where it was (cancelled), or in Closed if that is open.
              event.preventDefault()
              const done = picker.current
              picker.current = null
              if (!done) return
              if (!done.chosen) {
                document.querySelector<HTMLElement>(`[data-card-id="${done.idea.id}"]`)?.focus()
              } else if (!closedExpanded) {
                document.getElementById('board-column-closed-toggle')?.focus()
              }
            }}
            onKeyDown={(event) => {
              const index = Number(event.key) - 1
              const resolution = CLOSED_RESOLUTIONS[index]
              if (closing && resolution) {
                event.preventDefault()
                close(closing, resolution)
              }
            }}
          >
            {closing && (
              <div className="flex flex-col">
                <p className="px-2 pt-1 pb-1.5 text-sm text-muted">
                  Close <span className="font-medium text-primary">{closing.key}</span> as…
                </p>
                {CLOSED_RESOLUTIONS.map((resolution, index) => (
                  <button
                    key={resolution}
                    type="button"
                    onClick={() => close(closing, resolution)}
                    className="flex h-8 items-center gap-2 rounded-md px-2 text-sm text-primary transition-colors outline-none hover:bg-subtle-hover focus-visible:bg-subtle-hover focus-visible:highlight-ring"
                  >
                    <StatusDot tone={resolution} />
                    {labels[resolution]}
                    <Kbd className="ml-auto">{index + 1}</Kbd>
                  </button>
                ))}
              </div>
            )}
          </PopoverContent>
        </Popover>
        <DragOverlay dropAnimation={null}>
          {dragging && (
            <div className="cursor-grabbing" style={{ width: liftedWidth }}>
              <CardBody idea={dragging} lifted />
            </div>
          )}
        </DragOverlay>
      </DndContext>
    </BoardFocusContext>
  )
}

/**
 * Phones show one column at a time and snap to column starts, so the browser's own
 * "scroll the focused card into view" can leave it almost off-screen (the snap pulls
 * the row back). Tabbing into another column brings that whole column into view
 * (WCAG 2.4.11 focus not obscured).
 */
function revealFocusedColumn(event: FocusEvent<HTMLDivElement>) {
  const scroller = event.currentTarget
  const column = event.target.closest('section')
  if (!column || !scroller.contains(column)) return
  const shown = scroller.getBoundingClientRect()
  const box = column.getBoundingClientRect()
  if (box.left >= shown.left - 1 && box.right <= shown.right + 1) return
  column.scrollIntoView({ inline: 'start', block: 'nearest' })
}

/** Whether the Closed column is expanded, remembered per project (collapsed by default). */
function useClosedExpanded(slug: string): [boolean, (expanded: boolean) => void] {
  const key = `soundings-board-closed:${slug}`
  const [expanded, setExpanded] = useState(() => {
    try {
      return localStorage.getItem(key) === 'open'
    } catch {
      return false
    }
  })
  return [
    expanded,
    (next) => {
      setExpanded(next)
      try {
        localStorage.setItem(key, next ? 'open' : 'closed')
      } catch {
        // Not remembered; fine.
      }
    },
  ]
}
