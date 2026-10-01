import { useCallback, useSyncExternalStore } from 'react'

/**
 * True while the CSS media query matches, e.g. `useMediaQuery('(min-width: 640px)')`
 * (Tailwind's `sm`). Server and first render: false.
 */
export function useMediaQuery(query: string): boolean {
  const subscribe = useCallback(
    (callback: () => void) => {
      const list = window.matchMedia(query)
      list.addEventListener('change', callback)
      return () => list.removeEventListener('change', callback)
    },
    [query],
  )
  return useSyncExternalStore(
    subscribe,
    () => window.matchMedia(query).matches,
    () => false,
  )
}

/** Tailwind's `sm` breakpoint (40rem): popovers above, full-height sheets below. */
export const SM_UP = '(min-width: 40rem)'
