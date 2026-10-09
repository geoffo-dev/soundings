import { useRouter } from '@tanstack/react-router'
import { useEffect } from 'react'

/**
 * After a navigation to another page, focus that had nowhere to stay (the link
 * that was followed went with the old page, or Back was pressed) moves to the new
 * page's heading, so a screen reader announces where you are and Tab continues
 * from the top of the content (a11y review: focus on route change). Focus that is
 * still somewhere (a sidebar link, a dialog the page opened) is left alone.
 */
export function useRouteFocus() {
  const router = useRouter()
  useEffect(
    () =>
      router.subscribe('onRendered', (event) => {
        if (!event.pathChanged || !event.fromLocation) return
        // After the page's own effects (a sheet opening, a field taking focus).
        requestAnimationFrame(() =>
          requestAnimationFrame(() => {
            const active = document.activeElement
            if (active && active !== document.body && active.isConnected) return
            pageHeading()?.focus({ preventScroll: true })
          }),
        )
      }),
    [router],
  )
}

/**
 * The page's h1, made focusable without a ring of its own (`data-route-focus`), else
 * `#main`: where focus goes when a page's content was replaced under it (a route
 * change, or an idea whose access ended while it was open). For `focusWhenRendered`.
 */
export function pageHeading(): HTMLElement | null {
  const main = document.getElementById('main')
  const heading = main?.querySelector<HTMLElement>('h1')
  if (heading && !heading.hasAttribute('tabindex')) {
    heading.setAttribute('tabindex', '-1')
    heading.setAttribute('data-route-focus', '')
  }
  return heading ?? main
}
