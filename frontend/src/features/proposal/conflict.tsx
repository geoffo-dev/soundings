import { GitCompareArrows } from 'lucide-react'
import { useId, useMemo } from 'react'

import type { ProposalSection, ProposalSectionKey } from '@/api/types'
import { Button } from '@/components/ui/button'
import { RelativeTime } from '@/components/ui/relative-time'
import { focusWhenRendered } from '@/lib/focus'
import { cn } from '@/lib/utils'

import { useProposalEditor } from './editor-context'
import { diffLines, sectionDomId, type DiffLine } from './text'

/** Back to the section's text once the prompt has gone (its textarea, or the preview). */
function focusSectionText(key: ProposalSectionKey) {
  focusWhenRendered(() => {
    const section = document.getElementById(sectionDomId(key))
    return (
      section?.querySelector<HTMLElement>('textarea[data-section-text]') ??
      document.getElementById(`${sectionDomId(key)}-preview`)
    )
  })
}

/**
 * Someone else saved this section after you started (409 `proposal_conflict`):
 * their version and yours side by side, changed lines marked, and a choice.
 * "Keep your version" saves yours over theirs; "Use {name}'s version" replaces
 * yours (when the other version is your own, from another tab: "Keep this
 * version" / "Use the saved version"). Until then your text stays in the editor
 * and nothing is saved for this section. Either way focus goes back to the text.
 */
export function ConflictPrompt({
  sectionKey,
  theirs,
  yours,
}: {
  sectionKey: ProposalSectionKey
  theirs: ProposalSection
  yours: string
}) {
  const { store, me } = useProposalEditor()
  const titleId = useId()
  const lines = useMemo(() => diffLines(theirs.body_md, yours), [theirs.body_md, yours])
  const byYou = theirs.updated_by?.id === me.id
  const who = byYou ? 'You' : (theirs.updated_by?.display_name ?? 'Someone')

  return (
    <div
      role="alert"
      aria-labelledby={titleId}
      className="flex flex-col gap-3 rounded-lg border border-strong bg-warning-subtle p-3.5"
    >
      <div className="flex items-start gap-2.5">
        <GitCompareArrows aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-warning" />
        <div className="flex min-w-0 flex-col gap-0.5 text-sm">
          <p id={titleId} className="font-medium text-primary">
            {byYou
              ? 'You changed this section in another tab or window'
              : `${who} changed this section while you were editing`}
          </p>
          <p className="text-secondary">
            Saved <RelativeTime date={theirs.updated_at} />. Choose which version to keep; yours
            stays in the editor until you do.
          </p>
        </div>
      </div>
      <div className="grid gap-2 md:grid-cols-2">
        <Version
          title={byYou ? 'The saved version' : `${who}’s version`}
          lines={lines}
          side="theirs"
        />
        <Version title={byYou ? 'This version' : 'Your version'} lines={lines} side="yours" />
      </div>
      <div className="flex flex-wrap justify-end gap-2">
        <Button
          variant="outline"
          size="sm"
          onClick={() => {
            store.takeTheirs(sectionKey)
            focusSectionText(sectionKey)
          }}
        >
          {byYou ? 'Use the saved version' : `Use ${who}’s version`}
        </Button>
        <Button
          variant="secondary"
          size="sm"
          onClick={() => {
            void store.keepMine(sectionKey)
            focusSectionText(sectionKey)
          }}
        >
          {byYou ? 'Keep this version' : 'Keep your version'}
        </Button>
      </div>
    </div>
  )
}

function Version({
  title,
  lines,
  side,
}: {
  title: string
  lines: DiffLine[]
  side: 'theirs' | 'yours'
}) {
  const shown = lines.filter((line) => line.kind === 'same' || line.kind === side)
  const changed = shown.filter((line) => line.kind === side).length
  return (
    <figure className="flex min-w-0 flex-col overflow-hidden rounded-md border bg-surface">
      <figcaption className="flex items-center justify-between gap-2 border-b border-subtle px-3 py-1.5 text-xs font-medium text-secondary">
        {title}
        <span className="font-normal text-muted">
          {changed === 0
            ? 'no other lines'
            : `${String(changed)} changed ${changed === 1 ? 'line' : 'lines'}`}
        </span>
      </figcaption>
      <div className="max-h-56 overflow-auto py-1 font-mono text-xs leading-relaxed">
        {shown.length === 1 && shown[0]?.text === '' ? (
          <p className="px-3 text-muted">(empty)</p>
        ) : (
          shown.map((line, index) => (
            <p
              key={index}
              className={cn(
                'border-l-2 px-2.5 break-words whitespace-pre-wrap',
                line.kind === side ? 'border-strong bg-warning-subtle' : 'border-transparent',
              )}
            >
              {line.kind === side && <span className="sr-only">Changed: </span>}
              {line.text || ' '}
            </p>
          ))
        )}
      </div>
    </figure>
  )
}
