import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { KbdShortcut } from '@/components/ui/kbd'
import { SHORTCUT_GROUPS, SHORTCUTS, type ShortcutDefinition } from '@/lib/shortcuts'

/** The "?" dialog. Lists everything in the shortcut registry, grouped. */
export function ShortcutSheet({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const all: ShortcutDefinition[] = Object.values(SHORTCUTS)
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        size="xl"
        // Informational: focus the sheet itself, not the close button.
        onOpenAutoFocus={(event) => {
          event.preventDefault()
          ;(event.currentTarget as HTMLElement | null)?.focus()
        }}
      >
        <DialogHeader>
          <DialogTitle>Keyboard shortcuts</DialogTitle>
          <DialogDescription>Shortcuts work anywhere except while you’re typing.</DialogDescription>
        </DialogHeader>
        {/* Two columns from sm, so it fits a laptop screen without scrolling. Scrolls on
            short screens: focusable so the keyboard can scroll it too (axe
            scrollable-region-focusable); a named region says what it is. */}
        <DialogBody
          tabIndex={0}
          role="region"
          aria-label="Shortcuts"
          className="pb-5 focus-visible:outline-offset-[-2px] sm:columns-2 sm:gap-8"
        >
          {SHORTCUT_GROUPS.map((group) => {
            const items = all.filter((shortcut) => shortcut.group === group)
            if (items.length === 0) return null
            return (
              <section
                key={group}
                aria-labelledby={`shortcuts-${group}`}
                className="mb-5 break-inside-avoid last:mb-0"
              >
                <h3 id={`shortcuts-${group}`} className="mb-1.5 text-xs font-medium text-muted">
                  {group}
                </h3>
                <dl className="divide-y divide-subtle">
                  {items.map((shortcut) => (
                    <div
                      key={shortcut.keys}
                      className="flex h-9 items-center justify-between gap-4"
                    >
                      <dt className="text-sm text-primary">{shortcut.label}</dt>
                      <dd>
                        <KbdShortcut keys={shortcut.keys} />
                      </dd>
                    </div>
                  ))}
                </dl>
              </section>
            )
          })}
        </DialogBody>
      </DialogContent>
    </Dialog>
  )
}
