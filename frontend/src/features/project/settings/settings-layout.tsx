import { useBlocker } from '@tanstack/react-router'
import { createContext, use, useCallback, useEffect, useId, useState, type ReactNode } from 'react'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { ariaKeys, ButtonShortcut } from '@/components/ui/kbd'
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

type ReportUnsaved = (id: string, form: string | null) => void

const UnsavedChangesContext = createContext<ReportUnsaved | null>(null)

function listNames(names: string[]): string {
  if (names.length <= 1) return names.join('')
  return `${names.slice(0, -1).join(', ')} and ${names.at(-1) ?? ''}`
}

/**
 * Around the settings forms: leaving the page (a link, Back, closing the tab) with
 * unsaved edits asks first. Switching tabs doesn't, since the forms stay mounted.
 */
export function UnsavedChangesGuard({ children }: { children: ReactNode }) {
  const [unsaved, setUnsaved] = useState<ReadonlyMap<string, string>>(new Map())
  const report = useCallback<ReportUnsaved>((id, form) => {
    setUnsaved((current) => {
      if ((current.get(id) ?? null) === form) return current
      const next = new Map(current)
      if (form) next.set(id, form)
      else next.delete(id)
      return next
    })
  }, [])
  const blocker = useBlocker({
    shouldBlockFn: ({ current, next }) => current.pathname !== next.pathname,
    disabled: unsaved.size === 0,
    withResolver: true,
  })
  const forms = [...unsaved.values()]

  return (
    <UnsavedChangesContext value={report}>
      {children}
      <Dialog
        open={blocker.status === 'blocked'}
        onOpenChange={(open) => {
          if (!open) blocker.reset?.()
        }}
      >
        <DialogContent size="sm" role="alertdialog">
          <DialogHeader>
            <DialogTitle>Leave without saving?</DialogTitle>
            <DialogDescription>
              Your changes to {listNames(forms)} haven’t been saved.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="pt-5">
            <Button variant="ghost" onClick={() => blocker.reset?.()}>
              Keep editing
            </Button>
            <Button variant="destructive" onClick={() => blocker.proceed?.()}>
              Discard changes
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </UnsavedChangesContext>
  )
}

/**
 * Discard + Save for one settings form. Save looks quiet until something
 * changed but still answers when pressed ("No changes to save"). With unsaved
 * changes the bar sticks to the bottom of the screen, and leaving the page asks
 * first (inside an UnsavedChangesGuard); on phones it always sticks.
 */
export function FormActions({
  form,
  dirty,
  saving,
  notice,
  onDiscard,
  saveLabel = 'Save changes',
}: {
  /** What this form is called in "Your changes to … haven’t been saved" (lower case). */
  form: string
  dirty: boolean
  saving: boolean
  notice?: string | null
  onDiscard: () => void
  saveLabel?: string
}) {
  const report = use(UnsavedChangesContext)
  const id = useId()
  useEffect(() => {
    report?.(id, dirty ? form : null)
    return () => report?.(id, null)
  }, [report, id, dirty, form])

  return (
    <div
      className={cn(
        'flex items-center justify-end gap-2 border-t border-subtle pt-4',
        'max-sm:sticky max-sm:bottom-0 max-sm:-mx-4 max-sm:bg-surface max-sm:px-4 max-sm:pb-3',
        dirty && 'sticky bottom-0 z-10 -mx-4 bg-surface px-4 pb-4',
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
        aria-keyshortcuts={ariaKeys(SHORTCUTS.saveSettings.keys)}
      >
        {saveLabel}
        <ButtonShortcut keys={SHORTCUTS.saveSettings.keys} tone={dirty ? 'accent' : 'default'} />
      </Button>
    </div>
  )
}
