import type { KeyboardEvent } from 'react'

/**
 * ⌘/Ctrl+Enter from a checkbox or radio button. Radix stops Enter on those (WAI-ARIA:
 * Enter doesn't toggle them), which also hides the key from the form's "submit" shortcut,
 * so a hint like "Register agent ⌘↵" did nothing while a checkbox had focus. This presses
 * the button that advertises the shortcut (`aria-keyshortcuts` with Enter) in the same
 * form or dialog, exactly as a click would (a busy button ignores it).
 */
export function pressSubmitShortcut(event: KeyboardEvent<HTMLElement>): void {
  if (event.key !== 'Enter' || !(event.metaKey || event.ctrlKey) || event.altKey) return
  const scope =
    event.currentTarget.closest('form') ??
    event.currentTarget.closest('[role="dialog"], [role="alertdialog"]')
  const button = scope?.querySelector<HTMLButtonElement>(
    'button[aria-keyshortcuts*="Enter"]:not(:disabled)',
  )
  if (!button) return
  // Pressed once: no form or window shortcut handler runs it again.
  event.preventDefault()
  event.stopPropagation()
  button.click()
}
