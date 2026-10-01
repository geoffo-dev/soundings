import { useCallback, useRef } from 'react'

import { useShortcut } from '@/lib/shortcuts'

export const NAV_ITEM_ATTRIBUTE = 'data-nav-item'
/** Marks a column of items (the board): ←/→ move between columns. */
export const NAV_COLUMN_ATTRIBUTE = 'data-nav-column'

export interface ListNavigation {
  /** Callback ref for the container (one container may span several sections). */
  listRef: (node: HTMLElement | null) => (() => void) | undefined
  /** Focus the first (or last) row, e.g. ↓ from a filter field above the list. */
  focusFirst: () => void
}

/**
 * Linear-style row navigation: `j`/`k` anywhere on the page (and ↑/↓ while a
 * row has focus) move focus between elements marked `data-nav-item` in
 * document order; Enter opens the focused row (rows are links or buttons, so
 * that is native). In columns (`data-nav-column`, the board), ←/→ move to the
 * nearest item in the previous or next column that has any.
 *
 *   const { listRef } = useListNavigation()
 *   <div ref={listRef}>
 *     <Link data-nav-item …>…</Link>
 */
export function useListNavigation({ enabled = true }: { enabled?: boolean } = {}): ListNavigation {
  const container = useRef<HTMLElement | null>(null)

  const move = useCallback((delta: 1 | -1, from: 'current' | 'start' = 'current') => {
    const root = container.current
    if (!root) return false
    const items = [...root.querySelectorAll<HTMLElement>(`[${NAV_ITEM_ATTRIBUTE}]`)]
    if (items.length === 0) return false
    const active = document.activeElement
    const current =
      from === 'start' ? -1 : items.findIndex((item) => item === active || item.contains(active))
    const next =
      current === -1
        ? delta === 1
          ? 0
          : items.length - 1
        : Math.min(items.length - 1, Math.max(0, current + delta))
    const target = items[next]
    target?.focus()
    target?.scrollIntoView({ block: 'nearest' })
    return true
  }, [])

  useShortcut('nextItem', () => move(1), { enabled })
  useShortcut('previousItem', () => move(-1), { enabled })

  const moveColumn = useCallback((item: HTMLElement, delta: 1 | -1) => {
    const root = container.current
    const column = item.closest(`[${NAV_COLUMN_ATTRIBUTE}]`)
    if (!root || !column) return false
    const columns = [...root.querySelectorAll(`[${NAV_COLUMN_ATTRIBUTE}]`)]
    const top = item.getBoundingClientRect().top
    const distance = (element: HTMLElement) => Math.abs(element.getBoundingClientRect().top - top)
    const step =
      delta === 1
        ? columns.slice(columns.indexOf(column) + 1)
        : columns.slice(0, columns.indexOf(column)).reverse()
    for (const next of step) {
      const items = [...next.querySelectorAll<HTMLElement>(`[${NAV_ITEM_ATTRIBUTE}]`)]
      // The card level with this one, so moving across and back returns to it.
      const target = items.reduce<HTMLElement | undefined>(
        (best, candidate) => (!best || distance(candidate) < distance(best) ? candidate : best),
        undefined,
      )
      if (target) {
        target.focus()
        target.scrollIntoView({ block: 'nearest', inline: 'nearest' })
        return true
      }
    }
    return false
  }, [])

  const listRef = useCallback(
    (node: HTMLElement | null) => {
      container.current = node
      if (!node || !enabled) return undefined
      const onKeyDown = (event: KeyboardEvent) => {
        if (event.altKey || event.metaKey || event.ctrlKey || event.shiftKey) return
        if (!(event.target instanceof HTMLElement)) return
        const item = event.target.closest<HTMLElement>(`[${NAV_ITEM_ATTRIBUTE}]`)
        if (!item) return
        if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
          if (move(event.key === 'ArrowDown' ? 1 : -1)) event.preventDefault()
        } else if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
          if (moveColumn(item, event.key === 'ArrowRight' ? 1 : -1)) event.preventDefault()
        }
      }
      node.addEventListener('keydown', onKeyDown)
      return () => node.removeEventListener('keydown', onKeyDown)
    },
    [enabled, move, moveColumn],
  )

  const focusFirst = useCallback(() => void move(1, 'start'), [move])

  return { listRef, focusFirst }
}
