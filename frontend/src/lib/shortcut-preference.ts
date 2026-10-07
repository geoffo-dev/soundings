import { useSyncExternalStore } from 'react'

/**
 * "Single-key shortcuts" (WCAG 2.1.4 Character key shortcuts): letters, digits
 * and symbols on their own ("n", "g m", "?", "[") can be turned off in the "?"
 * sheet, for speech input or anyone who presses keys by accident. Shortcuts with
 * a modifier (⌘K, ⌘↵) always work, and so do keys that only act while a control
 * has focus (arrows in a list, digits on a score).
 *
 * Kept in this browser per person (no server preference), read again whenever the
 * signed-in user changes. On by default.
 */
const PREFIX = 'soundings-single-key-shortcuts:'

let userId: string | null = null
let enabled = true
const listeners = new Set<() => void>()

function storageKey(id: string): string {
  return `${PREFIX}${id}`
}

function read(id: string | null): boolean {
  if (!id) return true
  try {
    return localStorage.getItem(storageKey(id)) !== 'off'
  } catch {
    return true
  }
}

function notify() {
  listeners.forEach((listener) => listener())
}

/** Load the signed-in person's choice (null: signed out, so everything is on). */
export function loadShortcutPreference(id: string | null): void {
  if (id === userId) return
  userId = id
  const next = read(id)
  if (next !== enabled) {
    enabled = next
    notify()
  }
}

/** Whether single-key shortcuts fire right now (read on every key press). */
export function singleKeyShortcutsEnabled(): boolean {
  return enabled
}

export function setSingleKeyShortcuts(on: boolean): void {
  enabled = on
  if (userId) {
    try {
      if (on) localStorage.removeItem(storageKey(userId))
      else localStorage.setItem(storageKey(userId), 'off')
    } catch {
      // Storage unavailable: the choice lasts until the page reloads.
    }
  }
  notify()
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function useSingleKeyShortcuts(): boolean {
  return useSyncExternalStore(
    subscribe,
    () => enabled,
    () => true,
  )
}
