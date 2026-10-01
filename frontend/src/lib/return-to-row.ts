import { useEffect, useRef } from 'react'

/**
 * Back to the row you came from (WCAG 2.4.3). A list row that opens a detail
 * view (a sheet route over the list, or a page of its own) carries
 * `data-row-id`. When the detail closes, focus goes back to that row, scrolled
 * into view, instead of falling to `<main>` or `<body>` at the top of the page,
 * where a keyboard user would have to find their place again in a long list.
 *
 * - A sheet over the list: its `onCloseAutoFocus` calls `focusRow(id)`.
 * - A page: it calls `rememberRow(list, id)` while open; the list calls
 *   `useReturnToRow(list, …)`, which focuses the row once it has rendered, but
 *   only if focus was lost on the way (a click on another tab keeps its focus).
 */
export const ROW_ID_ATTRIBUTE = 'data-row-id'

/** Focus the rendered row `[data-row-id="id"]`, scrolled into view. False if it isn't rendered. */
export function focusRow(id: string, root: ParentNode = document): boolean {
  const row = root.querySelector<HTMLElement>(`[${ROW_ID_ATTRIBUTE}="${CSS.escape(id)}"]`)
  if (!row) return false
  row.scrollIntoView({ block: 'nearest' })
  row.focus({ preventScroll: true })
  return true
}

let remembered: { list: string; id: string } | null = null

/** A detail page notes which row of `list` it belongs to (the last one wins). */
export function rememberRow(list: string, id: string): void {
  remembered = { list, id }
}

/** Focus fell out of the page (the element that had it was removed), or to `<main>`. */
function focusWasLost(): boolean {
  const active = document.activeElement
  return !active || active === document.body || active.id === 'main'
}

/**
 * On the list: once `ready` (rows rendered), return focus to the row this list's
 * detail page remembered, if focus was lost getting here. Runs once per mount.
 */
export function useReturnToRow(list: string, ready: boolean): void {
  const done = useRef(false)
  useEffect(() => {
    if (!ready || done.current) return
    done.current = true
    const row = remembered?.list === list ? remembered.id : null
    remembered = null
    if (row && focusWasLost()) focusRow(row)
  }, [list, ready])
}
