import { useSyncExternalStore } from 'react'

/**
 * "Open research" (the gate's dialog, the primary action "Finish research", a card's
 * badge) asks the idea page's Research panel to take focus: the first open item's
 * field, or the panel's heading for people who only read it. The panel takes the
 * request when it is (or becomes) mounted for that idea.
 */
interface Request {
  ideaKey: string
  n: number
}

let request: Request | null = null
const listeners = new Set<() => void>()

export function requestResearchFocus(ideaKey: string): void {
  request = { ideaKey: ideaKey.toUpperCase(), n: (request?.n ?? 0) + 1 }
  listeners.forEach((listener) => listener())
}

/** True once per request for this idea: the panel moves focus, then the request is spent. */
export function takeResearchFocus(ideaKey: string): boolean {
  if (request?.ideaKey !== ideaKey.toUpperCase()) return false
  request = null
  return true
}

/** Changes whenever focus is requested, so a mounted panel checks again. */
export function useResearchFocusRequest(): number {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener)
      return () => listeners.delete(listener)
    },
    () => request?.n ?? 0,
    () => 0,
  )
}
