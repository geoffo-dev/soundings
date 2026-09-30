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
      <DialogContent size="md">
        <DialogHeader>
          <DialogTitle>Keyboard shortcuts</DialogTitle>
          <DialogDescription>Shortcuts work anywhere except while you’re typing.</DialogDescription>
        </DialogHeader>
        <DialogBody className="flex flex-col gap-5 pb-5">
          {SHORTCUT_GROUPS.map((group) => {
            const items = all.filter((shortcut) => shortcut.group === group)
            if (items.length === 0) return null
            return (
              <section key={group} aria-labelledby={`shortcuts-${group}`}>
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
