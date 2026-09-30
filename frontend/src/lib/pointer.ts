import { useSyncExternalStore } from 'react'

const COARSE = '(pointer: coarse)'

function subscribe(callback: () => void): () => void {
  const query = window.matchMedia(COARSE)
  query.addEventListener('change', callback)
  return () => query.removeEventListener('change', callback)
}

function snapshot(): boolean {
  return window.matchMedia(COARSE).matches
}

/** True on touch-first devices (no hover): say "Tap", not "Hover". */
export function useCoarsePointer(): boolean {
  return useSyncExternalStore(subscribe, snapshot, () => false)
}
