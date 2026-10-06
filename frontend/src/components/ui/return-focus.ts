import { useCallback, useEffect, useRef, useState, type Ref } from 'react'

/**
 * Where focus goes when a dialog or sheet closes (WCAG 2.4.3). Radix returns it to
 * a `<Trigger>`, but most overlays here open from code (a shortcut, the palette, a
 * menu item) and have none, so focus would fall to `<body>` and keyboard users would
 * start again from the top of the page. Instead each overlay remembers what had focus
 * when it opened and goes back there when it closes.
 *
 * - Opened from a menu item: back to the menu's button (the item is gone by then).
 * - Opened as another overlay closes (palette → New idea): back to where that one
 *   came from.
 * - It took you to another page (palette, New idea, New project): to that page's
 *   main content, like following a link.
 * - Something else took focus meanwhile (another overlay): it stays there.
 * - The element is gone (a "Close" that became "Reopen"): the overlay's
 *   `onCloseAutoFocus` can pick its replacement; it runs first and wins if it
 *   calls `preventDefault()`.
 */

interface Origin {
  element: HTMLElement | null
  /** The page it opened on. */
  pathname: string
}

/** Overlay content element → where it came from. */
const origins = new WeakMap<Element, Origin>()

const OVERLAY_SELECTOR = ':is([data-slot="dialog-content"], [data-slot="sheet-content"])'

function focusOrigin(): Origin {
  const pathname = window.location.pathname
  const active = document.activeElement
  if (!(active instanceof HTMLElement) || active === document.body) {
    return { element: null, pathname }
  }
  const closing = active.closest(`${OVERLAY_SELECTOR}[data-state="closed"]`)
  if (closing) return origins.get(closing) ?? { element: null, pathname }
  const menu = active.closest('[role="menu"]')
  return { element: (menu && menuTrigger(menu)) ?? active, pathname }
}

/**
 * A Radix menu's button. The menu names it (`aria-labelledby`) for as long as it is
 * mounted; the button points back (`aria-controls`) only while the menu is open, so
 * an overlay that opens as the menu animates closed (a fast "Test connection") would
 * otherwise remember the menu item, which is about to go.
 */
function menuTrigger(menu: Element): HTMLElement | null {
  const labelledBy = menu.getAttribute('aria-labelledby')
  const named = labelledBy ? document.getElementById(labelledBy) : null
  if (named && !menu.contains(named)) {
    // A submenu is named by its item in the parent menu: that menu's button, then.
    const parent = named.closest('[role="menu"]')
    return parent ? menuTrigger(parent) : named
  }
  return menu.id
    ? document.querySelector<HTMLElement>(`[aria-controls="${CSS.escape(menu.id)}"]`)
    : null
}

function assignRef<T>(ref: Ref<T> | undefined, value: T | null) {
  if (typeof ref === 'function') ref(value)
  else if (ref) ref.current = value
}

/**
 * For DialogContent and SheetContent: pass the caller's `ref` and
 * `onCloseAutoFocus`; put `attach` (the content's ref) and `closeAutoFocus`
 * (its `onCloseAutoFocus`) on the Radix content, and render
 * `<FocusOrigin capture={capture} />` inside it.
 */
export function useReturnFocus<T extends HTMLElement>(
  ref: Ref<T> | undefined,
  onCloseAutoFocus: ((event: Event) => void) | undefined,
) {
  const content = useRef<T | null>(null)
  const setContent = useCallback(
    (node: T | null) => {
      content.current = node
      assignRef(ref, node)
    },
    [ref],
  )
  const capture = useCallback((origin: Origin) => {
    if (content.current) origins.set(content.current, origin)
  }, [])
  const handleCloseAutoFocus = (event: Event) => {
    onCloseAutoFocus?.(event)
    if (event.defaultPrevented) return
    // Radix fires this on the content element just after it has unmounted.
    const origin = event.target instanceof Element ? origins.get(event.target) : undefined
    if (!origin) return
    const target =
      origin.pathname !== window.location.pathname
        ? document.getElementById('main')
        : origin.element
    if (!target?.isConnected) return
    event.preventDefault()
    const active = document.activeElement
    if (active && active !== document.body) return
    target.focus({ preventScroll: true })
  }
  return { attach: setContent, closeAutoFocus: handleCloseAutoFocus, capture }
}

/**
 * Renders nothing. Reads the focused element while the overlay first renders:
 * after that, an `autoFocus` field inside it would already have moved focus.
 * Hands it over once the content element is attached.
 */
export function FocusOrigin({ capture }: { capture: (origin: Origin) => void }) {
  const [origin] = useState(focusOrigin)
  useEffect(() => capture(origin), [capture, origin])
  return null
}
