import { useEffect, useState } from 'react'

/**
 * Focus follows an action (WCAG 2.4.3). Many actions replace the control that
 * was used: "Resolve" collapses its thread, "Approve" takes the card out of the
 * queue, posting a comment closes its composer. Without help, focus falls to
 * `<body>` and keyboard and screen-reader users start again from the top.
 *
 * `focusWhenRendered(find)` waits for the next frames until `find()` returns
 * the element the action produced (React renders after the click handler) and
 * focuses it, scrolled into view. It leaves focus alone if the person has
 * already moved it somewhere else meanwhile, unless `force` is set (which also
 * wins over the toaster returning focus after a toast's Undo).
 */
export function focusWhenRendered(
  find: () => HTMLElement | null | undefined,
  { frames = 30, force = false }: { frames?: number; force?: boolean } = {},
): void {
  if (typeof window === 'undefined') return
  const origin = document.activeElement
  let left = frames
  const attempt = () => {
    if (!force && !focusIsFree(origin)) return
    const target = find()
    if (target?.isConnected) {
      target.focus({ preventScroll: true })
      // From a toast's Undo the toaster hands focus back to where it was before the toast
      // was used as soon as focus leaves it. Without `force` that wins (the moderation
      // queue relies on it); with `force` a second focus stays.
      if (force && document.activeElement !== target) target.focus({ preventScroll: true })
      // jsdom has no scrollIntoView.
      if (typeof target.scrollIntoView === 'function') target.scrollIntoView({ block: 'nearest' })
      return
    }
    if (--left > 0) window.requestAnimationFrame(attempt)
  }
  window.requestAnimationFrame(attempt)
}

/** Focus is where the action left it, or was lost (its element removed, or `<body>`). */
function focusIsFree(origin: Element | null): boolean {
  const active = document.activeElement
  return (
    !active ||
    active === document.body ||
    active === origin ||
    !active.isConnected ||
    active.id === 'main'
  )
}

/** `document.getElementById`, as a finder for `focusWhenRendered`. */
export const byId = (id: string) => () => document.getElementById(id)

const NOT_TEXT_INPUTS = new Set([
  'button',
  'checkbox',
  'color',
  'file',
  'hidden',
  'image',
  'radio',
  'range',
  'reset',
  'submit',
])

/** Whether an element takes typed text (a text field, a textarea, contenteditable). */
export function isTextEntry(element: Element | null): boolean {
  if (!(element instanceof HTMLElement)) return false
  if (element instanceof HTMLTextAreaElement) return !element.readOnly
  if (element instanceof HTMLInputElement) {
    return !NOT_TEXT_INPUTS.has(element.type) && !element.readOnly
  }
  return element.isContentEditable
}

/**
 * True while focus is in a text field: a phone's sticky action bar steps aside
 * then (the on-screen keyboard already takes half the screen, and the bar's
 * action isn't what the person is doing).
 */
export function useTyping(): boolean {
  const [typing, setTyping] = useState(() =>
    typeof document === 'undefined' ? false : isTextEntry(document.activeElement),
  )
  useEffect(() => {
    // focusout fires before focus lands elsewhere: read activeElement a frame later.
    const update = () =>
      window.requestAnimationFrame(() => setTyping(isTextEntry(document.activeElement)))
    document.addEventListener('focusin', update)
    document.addEventListener('focusout', update)
    return () => {
      document.removeEventListener('focusin', update)
      document.removeEventListener('focusout', update)
    }
  }, [])
  return typing
}
