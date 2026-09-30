import { useSyncExternalStore } from 'react'

/**
 * App-wide dialogs that can be opened from anywhere (a button, a shortcut,
 * the palette) without prop drilling. They are mounted once in the signed-in
 * layout (routes/_app.tsx).
 *
 *   openNewIdea()                                  // "n", palette, sidebar
 *   openNewIdea({ projectSlug: 'customer-innovation' })  // project views preselect
 *   openCreateProject()                            // sidebar "New project" (platform admins)
 */
export type AppDialog = { name: 'newIdea'; projectSlug?: string } | { name: 'createProject' } | null

let current: AppDialog = null
const listeners = new Set<() => void>()

function set(next: AppDialog) {
  current = next
  listeners.forEach((listener) => listener())
}

export function openNewIdea(options: { projectSlug?: string } = {}): void {
  set({ name: 'newIdea', ...options })
}

export function openCreateProject(): void {
  set({ name: 'createProject' })
}

export function closeDialog(): void {
  set(null)
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

/** The open dialog (or null). Dialog components render when it names them. */
export function useAppDialog(): AppDialog {
  return useSyncExternalStore(
    subscribe,
    () => current,
    () => null,
  )
}
