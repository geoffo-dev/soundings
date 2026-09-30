import { useEffect, useLayoutEffect, useRef, useSyncExternalStore } from 'react'

import type { CommandAction } from '@/components/ui/command-palette'

/**
 * Context actions for the ⌘K palette. A page registers a group while it is
 * mounted; the palette lists registered groups first, above the global ones.
 *
 *   useCommands({
 *     id: 'idea',
 *     heading: idea.key,
 *     actions: [
 *       { id: 'assign-owner', label: 'Assign owner…', icon: <UserRound />, onSelect: openOwnerPicker },
 *       { id: 'evaluate', label: 'Evaluate', shortcut: 'e', icon: <Gauge />, onSelect: openEvaluate },
 *     ],
 *   })
 *
 * Only register actions the user may take (use the API's `permissions`).
 * `onSelect` may change every render; the latest one runs.
 */
export interface CommandGroupRegistration {
  /** Unique per group, e.g. "idea" or "project". A later registration with the same id replaces it. */
  id: string
  heading: string
  actions: CommandAction[]
  /** Lower comes first (default 0). */
  order?: number
}

let groups: CommandGroupRegistration[] = []
const listeners = new Set<() => void>()

function emit() {
  listeners.forEach((listener) => listener())
}

export function registerCommands(group: CommandGroupRegistration): () => void {
  groups = [...groups.filter((g) => g.id !== group.id), group].sort(
    (a, b) => (a.order ?? 0) - (b.order ?? 0),
  )
  emit()
  return () => {
    groups = groups.filter((g) => g !== group)
    emit()
  }
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

/** Registered context groups, in order (for the palette). */
export function useRegisteredCommands(): CommandGroupRegistration[] {
  return useSyncExternalStore(
    subscribe,
    () => groups,
    () => groups,
  )
}

/** Registers palette actions while the calling component is mounted. */
export function useCommands(group: CommandGroupRegistration | null): void {
  const latest = useRef(group)
  useLayoutEffect(() => {
    latest.current = group
  })
  // Re-register only when what the palette shows changes, not on every render.
  const signature = group
    ? [
        group.id,
        group.heading,
        group.order ?? 0,
        ...group.actions.map((a) =>
          [a.id, a.label, a.hint ?? '', a.shortcut ?? '', (a.keywords ?? []).join(' ')].join(':'),
        ),
      ].join('|')
    : ''
  useEffect(() => {
    const snapshot = latest.current
    if (!snapshot) return
    return registerCommands({
      ...snapshot,
      actions: snapshot.actions.map((action) => ({
        ...action,
        onSelect: () => latest.current?.actions.find((a) => a.id === action.id)?.onSelect(),
      })),
    })
  }, [signature])
}
