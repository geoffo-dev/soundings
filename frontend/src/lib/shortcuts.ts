import { useHotkey, type HotkeyOptions } from '@/lib/hotkeys'

/**
 * The single registry of keyboard shortcuts. The "?" sheet renders this list,
 * so a shortcut only exists if it is registered here and bound with
 * useShortcut(). Add page-specific shortcuts with their own `group`.
 */
export interface ShortcutDefinition {
  keys: string
  label: string
  group: 'General' | 'Navigation' | 'Lists' | 'Ideas' | 'Idea page' | 'Proposal'
}

export const SHORTCUTS = {
  commandPalette: { keys: 'mod+k', label: 'Open command palette', group: 'General' },
  shortcutSheet: { keys: '?', label: 'Show keyboard shortcuts', group: 'General' },
  toggleSidebar: { keys: '[', label: 'Collapse or expand sidebar', group: 'General' },
  // Handled by the toaster (sonner's hotkey), listed so people can find it: messages
  // stay while focus or the pointer is on them (components/ui/toaster.tsx).
  focusMessages: {
    keys: 'alt+t',
    label: 'Go to messages such as Undo (they wait while you’re there)',
    group: 'General',
  },
  goToMyWork: { keys: 'g m', label: 'Go to My work', group: 'Navigation' },
  goToNotifications: { keys: 'g i', label: 'Go to notifications (inbox)', group: 'Navigation' },
  nextItem: { keys: 'j', label: 'Next item (or ↓)', group: 'Lists' },
  previousItem: { keys: 'k', label: 'Previous item (or ↑)', group: 'Lists' },
  // ←/→ are handled by useListNavigation while a board card has focus.
  previousColumn: { keys: 'arrowleft', label: 'Previous column (board)', group: 'Lists' },
  nextColumn: { keys: 'arrowright', label: 'Next column (board)', group: 'Lists' },
  openItem: { keys: 'enter', label: 'Open the focused item', group: 'Lists' },
  toggleView: { keys: 'v', label: 'Switch between Board and List', group: 'Lists' },
  focusFilters: { keys: 'f', label: 'Search and filter ideas', group: 'Lists' },
  moveCard: { keys: 'space', label: 'Pick up or drop a board card', group: 'Lists' },
  saveSettings: { keys: 'mod+s', label: 'Save settings', group: 'General' },
  newIdea: { keys: 'n', label: 'New idea', group: 'Ideas' },
  evaluate: { keys: 'e', label: 'Evaluate (focused or open idea)', group: 'Ideas' },
  submitForm: { keys: 'mod+enter', label: 'Submit a form or comment', group: 'Ideas' },
  // The idea page (features/idea): "e" evaluates there too.
  changeStatus: { keys: 's', label: 'Change status', group: 'Idea page' },
  assignOwner: { keys: 'a', label: 'Assign owner', group: 'Idea page' },
  focusComment: { keys: 'c', label: 'Write a comment', group: 'Idea page' },
  overviewTab: { keys: '1', label: 'Overview tab', group: 'Idea page' },
  evaluationsTab: { keys: '2', label: 'Evaluations tab', group: 'Idea page' },
  proposalTab: { keys: '3', label: 'Proposal tab', group: 'Idea page' },
  // The proposal editor (features/proposal, wireframe 05).
  proposalSave: { keys: 'mod+s', label: 'Save the proposal now', group: 'Proposal' },
  proposalPreview: {
    keys: 'mod+enter',
    label: 'Switch the section between Write and Preview',
    group: 'Proposal',
  },
  proposalNextSection: { keys: 'j', label: 'Next section', group: 'Proposal' },
  proposalPreviousSection: { keys: 'k', label: 'Previous section', group: 'Proposal' },
  proposalComment: { keys: 'c', label: 'Comment on the section in view', group: 'Proposal' },
  proposalBold: { keys: 'mod+b', label: 'Bold (while writing)', group: 'Proposal' },
  proposalItalic: { keys: 'mod+i', label: 'Italic (while writing)', group: 'Proposal' },
} as const satisfies Record<string, ShortcutDefinition>

export type ShortcutId = keyof typeof SHORTCUTS

export const SHORTCUT_GROUPS: ShortcutDefinition['group'][] = [
  'General',
  'Navigation',
  'Lists',
  'Ideas',
  'Idea page',
  'Proposal',
]

export function useShortcut(
  id: ShortcutId,
  handler: (event: KeyboardEvent) => void,
  options?: HotkeyOptions,
): void {
  useHotkey(SHORTCUTS[id].keys, handler, options)
}
