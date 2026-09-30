import type { ReactNode } from 'react'

import { Button } from '@/components/ui/button'
import { KbdShortcut } from '@/components/ui/kbd'
import { SHORTCUTS } from '@/lib/shortcuts'
import { cn } from '@/lib/utils'

/** A settings panel: heading, one-line explanation, then the form. */
export function SettingsSection({
  title,
  description,
  actions,
  children,
}: {
  title: string
  description?: ReactNode
  actions?: ReactNode
  children: ReactNode
}) {
  return (
    <section className="flex flex-col gap-5" aria-label={title}>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex max-w-2xl flex-col gap-1">
          <h2 className="text-xl font-semibold text-primary">{title}</h2>
          {description && <p className="text-sm text-muted">{description}</p>}
        </div>
        {actions}
      </div>
      {children}
    </section>
  )
}

/**
 * Discard + Save for one settings form. Save looks quiet until something
 * changed but still answers when pressed ("No changes to save"). On phones the
 * bar sticks to the bottom of the screen.
 */
export function FormActions({
  dirty,
  saving,
  notice,
  onDiscard,
  saveLabel = 'Save changes',
}: {
  dirty: boolean
  saving: boolean
  notice?: string | null
  onDiscard: () => void
  saveLabel?: string
}) {
  return (
    <div
      className={cn(
        'flex items-center justify-end gap-2 border-t border-subtle pt-4',
        'max-sm:sticky max-sm:bottom-0 max-sm:-mx-4 max-sm:bg-surface max-sm:px-4 max-sm:pb-3',
      )}
    >
      <p aria-live="polite" className="mr-auto text-sm text-muted">
        {notice ?? (dirty ? 'Unsaved changes' : '')}
      </p>
      {dirty && (
        <Button variant="ghost" onClick={onDiscard} disabled={saving}>
          Discard
        </Button>
      )}
      <Button
        type="submit"
        variant={dirty ? 'primary' : 'secondary'}
        loading={saving}
        className={cn(!dirty && 'text-muted')}
      >
        {saveLabel}
        <KbdShortcut
          keys={SHORTCUTS.saveSettings.keys}
          className={cn(
            'ml-1 hidden sm:inline-flex',
            dirty &&
              '[&_kbd]:border-white/25 [&_kbd]:bg-white/15 [&_kbd]:text-accent-foreground [&_kbd]:shadow-none',
          )}
        />
      </Button>
    </div>
  )
}
