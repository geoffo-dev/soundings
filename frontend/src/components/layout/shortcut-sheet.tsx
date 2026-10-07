import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { KbdShortcut } from '@/components/ui/kbd'
import { Switch } from '@/components/ui/switch'
import { isSingleKeyShortcut } from '@/lib/hotkeys'
import { setSingleKeyShortcuts, useSingleKeyShortcuts } from '@/lib/shortcut-preference'
import { SHORTCUT_GROUPS, SHORTCUTS, type ShortcutDefinition } from '@/lib/shortcuts'
import { cn } from '@/lib/utils'

/** The "?" dialog. Lists everything in the shortcut registry, grouped. */
export function ShortcutSheet({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const all: ShortcutDefinition[] = Object.values(SHORTCUTS)
  const singleKeys = useSingleKeyShortcuts()
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
          {/* WCAG 2.1.4: single-key shortcuts can be turned off (speech input, stray keys). */}
          <div className="mt-3 flex items-start gap-3 rounded-lg border px-3 py-2.5">
            <Switch
              id="single-key-shortcuts"
              checked={singleKeys}
              onCheckedChange={setSingleKeyShortcuts}
              aria-describedby="single-key-shortcuts-hint"
              className="mt-0.5"
            />
            <div className="flex flex-col gap-0.5">
              <label htmlFor="single-key-shortcuts" className="text-sm font-medium text-primary">
                Single-key shortcuts
              </label>
              <p id="single-key-shortcuts-hint" className="text-sm text-muted">
                Keys on their own, like N or G then M. Turn them off if you use speech input or
                press keys by accident; shortcuts with ⌘ or Ctrl keep working. Saved in this
                browser.
              </p>
            </div>
          </div>
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
                  {items.map((shortcut) => {
                    const off = !singleKeys && isSingleKeyShortcut(shortcut.keys)
                    return (
                      <div
                        key={shortcut.keys}
                        className="flex min-h-9 items-center justify-between gap-4 py-1"
                      >
                        <dt className={cn('text-sm', off ? 'text-muted' : 'text-primary')}>
                          {shortcut.label}
                          {off && <span className="sr-only"> (turned off)</span>}
                        </dt>
                        <dd>
                          <KbdShortcut keys={shortcut.keys} always />
                        </dd>
                      </div>
                    )
                  })}
                </dl>
              </section>
            )
          })}
        </DialogBody>
      </DialogContent>
    </Dialog>
  )
}
