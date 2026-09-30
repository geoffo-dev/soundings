import type { KeyboardCoordinateGetter } from '@dnd-kit/core'

export interface ColumnDropData {
  type: 'column'
  status: string
}

/**
 * Keyboard moves on the board: ← and → jump to the previous or next column
 * (cards within a column are ordered by the sort, so ↑/↓ do nothing).
 * `target` remembers the column the card is heading for, so quick key presses
 * don't depend on collision detection having caught up. Returns the top-left
 * of the dragged card centred in the target column.
 */
export function columnCoordinates(target: { current: string | null }): KeyboardCoordinateGetter {
  return (event, { context, currentCoordinates }) => {
    const { active, collisionRect, droppableRects, droppableContainers, over } = context
    if (event.code === 'ArrowUp' || event.code === 'ArrowDown') {
      event.preventDefault()
      return undefined
    }
    if (event.code !== 'ArrowLeft' && event.code !== 'ArrowRight') return undefined
    event.preventDefault()
    if (!active || !collisionRect) return undefined

    const columns = droppableContainers
      .getEnabled()
      .filter(
        (container) => (container.data.current as ColumnDropData | undefined)?.type === 'column',
      )
      .map((container) => ({ id: container.id, rect: droppableRects.get(container.id) }))
      .flatMap(({ id, rect }) => (rect ? [{ id, rect }] : []))
      .sort((a, b) => a.rect.left - b.rect.left)

    const from = target.current ?? (over?.id === undefined ? null : String(over.id))
    const index = columns.findIndex((column) => column.id === from)
    if (index === -1) return undefined
    const next = columns[index + (event.code === 'ArrowRight' ? 1 : -1)]
    if (!next) return undefined
    target.current = String(next.id)
    return {
      x: next.rect.left + (next.rect.width - collisionRect.width) / 2,
      y: Math.max(
        next.rect.top,
        Math.min(currentCoordinates.y, next.rect.bottom - collisionRect.height),
      ),
    }
  }
}
