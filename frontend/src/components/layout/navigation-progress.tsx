import { useRouterState } from '@tanstack/react-router'
import { useEffect, useState } from 'react'

/** Quick navigations (most of them) show nothing; slower ones get the bar. */
const SHOW_AFTER_MS = 300

/**
 * A thin bar along the top of the content panel while a navigation waits (a
 * route's code or data on a slow network), so the old page staying on screen
 * doesn't read as "nothing happened". Shown only after 300 ms.
 */
export function NavigationProgress() {
  const loading = useRouterState({ select: (state) => state.status === 'pending' })
  const [shown, setShown] = useState(false)
  useEffect(() => {
    if (!loading) return
    const timer = window.setTimeout(() => setShown(true), SHOW_AFTER_MS)
    return () => {
      window.clearTimeout(timer)
      setShown(false)
    }
  }, [loading])
  if (!loading || !shown) return null
  return (
    <div
      role="progressbar"
      aria-label="Loading the page"
      className="pointer-events-none absolute inset-x-0 top-0 z-30 h-0.5 overflow-hidden"
    >
      <div className="h-full w-2/5 animate-progress rounded-full bg-accent" />
    </div>
  )
}
