import { KbdShortcut } from '@/components/ui/kbd'

/**
 * A shortcut hint inside a primary button ("Submit ⌘↵"), on the accent fill.
 * Hidden from assistive tech (the button carries `aria-keyshortcuts`) and on
 * phones (no keyboard).
 */
export function ButtonShortcut({ keys }: { keys: string }) {
  return (
    <KbdShortcut
      keys={keys}
      aria-hidden="true"
      tone="accent"
      className="ml-1 hidden sm:inline-flex"
    />
  )
}

/** `aria-keyshortcuts` for the registry's key syntax ("e" → "E", "mod+enter" → both platforms). */
export function ariaKeys(keys: string): string {
  if (keys === 'mod+enter') return 'Control+Enter Meta+Enter'
  return keys.toUpperCase()
}
