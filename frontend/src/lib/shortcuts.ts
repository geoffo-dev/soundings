import { useHotkey, type HotkeyOptions } from '@/lib/hotkeys'

/**
 * The single registry of keyboard shortcuts. The "?" sheet renders this list,
 * so a shortcut only exists if it is registered here and bound with
 * useShortcut(). Add page-specific shortcuts with their own `group`.
 */
export interface ShortcutDefinition {
  keys: string
  label: string
  group: 'General' | 'Navigation' | 'Ideas'
}

export const SHORTCUTS = {
  commandPalette: { keys: 'mod+k', label: 'Open command palette', group: 'General' },
  shortcutSheet: { keys: '?', label: 'Show keyboard shortcuts', group: 'General' },
  toggleSidebar: { keys: '[', label: 'Collapse or expand sidebar', group: 'General' },
  goToMyWork: { keys: 'g m', label: 'Go to My work', group: 'Navigation' },
  newIdea: { keys: 'n', label: 'New idea', group: 'Ideas' },
} as const satisfies Record<string, ShortcutDefinition>

export type ShortcutId = keyof typeof SHORTCUTS

export const SHORTCUT_GROUPS: ShortcutDefinition['group'][] = ['General', 'Navigation', 'Ideas']

export function useShortcut(
  id: ShortcutId,
  handler: (event: KeyboardEvent) => void,
  options?: HotkeyOptions,
): void {
  useHotkey(SHORTCUTS[id].keys, handler, options)
}
