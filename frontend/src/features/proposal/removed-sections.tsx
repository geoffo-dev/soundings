import { Copy } from 'lucide-react'
import { useSyncExternalStore } from 'react'

import { Button } from '@/components/ui/button'
import { Callout } from '@/components/ui/callout'
import { Textarea } from '@/components/ui/textarea'
import { toast, toastUndo } from '@/components/ui/toaster'

import type { ProposalSaveStore } from './save-store'

/**
 * Text typed into a section that was removed from the project's template meanwhile
 * (contract-phase8 §2.7): it is never dropped silently. Each such section shows its
 * text here, kept in this browser, with Copy and Discard; an admin can restore the
 * section in Project settings → Proposal.
 */
export function RemovedSections({
  store,
  activeKeys,
}: {
  store: ProposalSaveStore
  activeKeys: readonly string[]
}) {
  useSyncExternalStore(store.subscribe, store.getVersion)
  const removed = store.removed()
  if (removed.length === 0) return null
  return (
    <div className="flex flex-col gap-4 border-t border-subtle pt-6" aria-label="Removed sections">
      {removed.map(([key, state]) => {
        const back = activeKeys.includes(key.replace(/#kept$/, ''))
        const fieldId = `removed-section-${key.replace(/[^a-z0-9_]/g, '-')}`
        return (
          <Callout
            key={key}
            tone="warning"
            title={
              back
                ? `“${state.title}” is back in the template`
                : `“${state.title}” was removed from the template`
            }
          >
            <div className="flex flex-col gap-2 pt-1">
              <p>
                {back
                  ? 'Your text from before is kept here: copy it into the section above.'
                  : 'Your text is kept here; copy it, or ask an admin to restore the section.'}
              </p>
              <label htmlFor={fieldId} className="sr-only">
                Your text for {state.title}
              </label>
              <Textarea
                id={fieldId}
                value={state.draft}
                readOnly
                minRows={3}
                maxRows={10}
                className="bg-surface"
              />
              <div className="flex flex-wrap gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => {
                    navigator.clipboard
                      .writeText(state.draft)
                      .then(() => toast.message('Text copied'))
                      .catch(() =>
                        toast.error('Couldn’t copy the text', {
                          description: 'Select it and copy it by hand.',
                        }),
                      )
                  }}
                >
                  <Copy /> Copy text
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    const { title, draft } = state
                    store.discardRemoved(key)
                    toastUndo(`Your text for “${title}” discarded`, {
                      onUndo: () => store.restoreKept(key.replace(/#kept$/, ''), title, draft),
                    })
                  }}
                >
                  Discard
                </Button>
              </div>
            </div>
          </Callout>
        )
      })}
    </div>
  )
}
