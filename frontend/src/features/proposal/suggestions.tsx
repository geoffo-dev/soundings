import { useQueryClient } from '@tanstack/react-query'
import { Check, GitCompareArrows, History, Sparkles, X } from 'lucide-react'
import { useId, useMemo, useState } from 'react'

import { describeError, hasErrorCode } from '@/api/errors'
import { queryKeys } from '@/api/keys'
import { useAcceptProposalSuggestion, useDiscardProposalSuggestion } from '@/api/proposals'
import type { ProposalSection, ProposalSuggestion } from '@/api/types'
import { offerUndo } from '@/api/undo'
import { Avatar } from '@/components/ui/avatar'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Callout } from '@/components/ui/callout'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Markdown } from '@/components/ui/markdown'
import { RelativeTime } from '@/components/ui/relative-time'
import { SegmentedControl } from '@/components/ui/segmented-control'
import { toast } from '@/components/ui/toaster'
import { focusWhenRendered } from '@/lib/focus'
import { cn } from '@/lib/utils'

import { useProposalEditor } from './editor-context'
import { useSectionSave } from './save-store'
import { hasContent, sectionDomId, suggestionDiff, type SuggestionLine } from './text'

/** The DOM id of a suggestion card (focus moves between them). */
export function suggestionDomId(id: string): string {
  return `proposal-suggestion-${id}`
}

/** "Research agent", "Carol Díaz", or "Someone" for a deleted author. */
function authorName(suggestion: ProposalSuggestion): string {
  return suggestion.author?.display_name ?? 'Someone'
}

/**
 * A section's pending suggestions (contract-phase5 §3.4 "The editor"): who
 * suggested it (an AI badge for agents), when, what it would change, and
 * Accept / Discard for the owner and admins. Nothing when there are none.
 */
export function SectionSuggestions({ section }: { section: ProposalSection }) {
  const { suggestions } = useProposalEditor()
  const list = suggestions.get(section.key) ?? []
  const headingId = useId()
  if (list.length === 0) return null
  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-2">
      <h3 id={headingId} className="flex items-center gap-1.5 text-sm font-medium text-secondary">
        <GitCompareArrows aria-hidden="true" className="size-4 text-muted" />
        {list.length === 1 ? '1 suggestion' : `${String(list.length)} suggestions`}
        <span className="sr-only"> for {section.title}</span>
      </h3>
      <ul className="flex flex-col gap-2">
        {list.map((suggestion) => (
          <li key={suggestion.id}>
            <SuggestionCard suggestion={suggestion} section={section} />
          </li>
        ))}
      </ul>
    </section>
  )
}

type View = 'changes' | 'preview'

function SuggestionCard({
  suggestion,
  section,
}: {
  suggestion: ProposalSuggestion
  section: ProposalSection
}) {
  const { store, ideaKey, suggestionPermissions, suggestions, me } = useProposalEditor()
  const queryClient = useQueryClient()
  const state = useSectionSave(store, section.key)
  const accept = useAcceptProposalSuggestion(ideaKey)
  const discard = useDiscardProposalSuggestion(ideaKey)
  const [theirs, setTheirs] = useState<ProposalSection | null>(null)
  const [confirming, setConfirming] = useState(false)
  const titleId = useId()

  // What the suggestion would replace: the text on screen, or what someone saved meanwhile.
  const current = theirs?.body_md ?? state?.draft ?? section.body_md
  const baseVersion = theirs?.version ?? state?.base ?? section.version
  const lines = useMemo(() => suggestionDiff(current, suggestion.body_md), [current, suggestion])
  const [view, setView] = useState<View>(hasContent(current) ? 'changes' : 'preview')
  const unsaved = Boolean(state && (state.draft !== state.saved || state.status === 'conflict'))
  const saving = state?.status === 'saving'
  const ai = suggestion.source === 'ai'
  const author = authorName(suggestion)
  const byMe = suggestion.author?.id === me.id

  /** After the card goes: the next suggestion of this section, else the section's text. */
  const focusAfter = () => {
    const siblings = suggestions.get(section.key) ?? []
    const index = siblings.findIndex((item) => item.id === suggestion.id)
    const next = siblings[index + 1] ?? siblings[index - 1]
    focusWhenRendered(
      () => {
        const card = next && document.getElementById(suggestionDomId(next.id))
        if (card) return card
        const element = document.getElementById(sectionDomId(section.key))
        return (
          element?.querySelector<HTMLElement>('textarea[data-section-text]') ??
          element?.querySelector<HTMLElement>('[data-section-heading]')
        )
      },
      { force: true },
    )
  }

  const run = () => {
    setConfirming(false)
    const before = state?.draft ?? section.body_md
    store.holdSave(section.key)
    accept.mutate(
      { suggestionId: suggestion.id, baseVersion },
      {
        onSuccess: ({ section: saved }) => {
          store.replace(saved)
          setTheirs(null)
          focusAfter()
          offerUndo(
            byMe ? 'Your suggestion is in' : `${author}’s suggestion accepted`,
            () => {
              store.edit(section.key, before)
              void store.saveNow(section.key)
            },
            { description: `${section.title} now has the suggested text.` },
          )
        },
        onError: (error) => {
          store.releaseSave(section.key)
          if (hasErrorCode(error, 'proposal_conflict')) {
            const now = (error.problem as { current?: ProposalSection | null } | undefined)?.current
            if (now) {
              setTheirs(now)
              setView('changes')
              return
            }
          }
          if (hasErrorCode(error, 'suggestion_not_pending')) {
            void queryClient.invalidateQueries({
              queryKey: queryKeys.proposals.suggestions(ideaKey),
            })
          }
          const { title, description } = describeError(error)
          toast.error('Couldn’t accept the suggestion', {
            description: [title, description].filter(Boolean).join('. '),
          })
        },
      },
    )
  }

  const onAccept = () => {
    if (unsaved && !theirs) setConfirming(true)
    else run()
  }

  const onDiscard = () => {
    focusAfter()
    discard(suggestion, byMe ? 'Your suggestion discarded' : `${author}’s suggestion discarded`)
  }

  const who =
    theirs?.updated_by?.id === me.id ? 'You' : (theirs?.updated_by?.display_name ?? 'Someone')

  return (
    <article
      id={suggestionDomId(suggestion.id)}
      tabIndex={-1}
      aria-labelledby={titleId}
      className="flex flex-col overflow-hidden rounded-lg border bg-surface outline-offset-2"
    >
      <header className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-subtle px-3 py-2">
        <div className="flex min-w-0 flex-1 items-center gap-2">
          <Avatar
            size="xs"
            name={author}
            src={suggestion.author?.avatar_url}
            isAgent={ai}
            decorative
          />
          <p id={titleId} className="min-w-0 truncate text-sm text-muted">
            <span className="font-medium text-primary">{byMe ? 'You' : author}</span>
            <span className="sr-only"> suggested new text</span>
            <span aria-hidden="true"> · </span>
            <RelativeTime date={suggestion.created_at} />
          </p>
          {ai ? (
            <Badge variant="accent">
              <Sparkles aria-hidden="true" />
              AI
              <span className="sr-only"> agent</span>
            </Badge>
          ) : suggestion.source === 'mcp' ? (
            <Badge variant="outline">via MCP</Badge>
          ) : null}
        </div>
        <SegmentedControl
          size="sm"
          aria-label="Show the changes or the suggested text"
          value={view}
          onValueChange={setView}
          options={[
            { value: 'changes', label: 'Changes' },
            { value: 'preview', label: 'Suggested text' },
          ]}
        />
      </header>

      {suggestion.section_changed && !theirs && (
        <p className="flex items-center gap-1.5 border-b border-subtle px-3 py-1.5 text-xs text-secondary">
          <History aria-hidden="true" className="size-3.5 text-warning" />
          The section has changed since this was suggested. The changes below compare with the text
          as it is now.
        </p>
      )}
      {theirs && (
        <Callout
          role="alert"
          tone="warning"
          icon={<GitCompareArrows />}
          className="m-3 mb-0"
          title={`${who} saved ${section.title} a moment ago`}
        >
          The changes below now compare with that version. Accepting replaces it.
        </Callout>
      )}

      <div className="max-h-80 overflow-y-auto">
        {view === 'preview' ? (
          <div className="px-3.5 py-3">
            <Markdown nested>{suggestion.body_md}</Markdown>
          </div>
        ) : lines.length === 0 ? (
          <p className="px-3.5 py-3 text-sm text-muted">
            Same as the text now: accepting changes nothing.
          </p>
        ) : (
          <DiffLines lines={lines} />
        )}
      </div>

      {suggestionPermissions.can_decide && (
        <footer className="flex flex-wrap items-center justify-end gap-2 border-t border-subtle px-3 py-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={onDiscard}
            disabled={accept.isPending}
            aria-label={`Discard ${byMe ? 'your' : `${author}’s`} suggestion for ${section.title}`}
          >
            <X />
            Discard
          </Button>
          <Button
            variant="secondary"
            size="sm"
            loading={accept.isPending}
            disabled={saving}
            onClick={onAccept}
            aria-label={`${theirs ? 'Accept anyway' : 'Accept'}: ${byMe ? 'your' : `${author}’s`} suggestion for ${section.title}`}
          >
            <Check />
            {theirs ? 'Accept anyway' : 'Accept'}
          </Button>
        </footer>
      )}

      <Dialog open={confirming} onOpenChange={setConfirming}>
        <DialogContent size="sm" role="alertdialog">
          <DialogHeader>
            <DialogTitle>Replace your unsaved changes?</DialogTitle>
            <DialogDescription>
              You’re editing {section.title}. Accepting replaces the whole section with the
              suggestion, including what you haven’t saved yet.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="pt-5">
            <Button variant="ghost" onClick={() => setConfirming(false)}>
              Keep editing
            </Button>
            <Button variant="primary" onClick={run}>
              Accept suggestion
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </article>
  )
}

/** The unified diff: removed and added lines marked by sign and words, not colour alone. */
function DiffLines({ lines }: { lines: SuggestionLine[] }) {
  return (
    <div className="py-1.5 text-sm leading-relaxed">
      {lines.map((line, index) =>
        line.kind === 'skip' ? (
          <p key={index} className="px-3 py-0.5 text-muted italic">
            {line.count === 1 ? '1 unchanged line' : `${String(line.count)} unchanged lines`}
          </p>
        ) : (
          <p
            key={index}
            className={cn(
              'flex gap-2 px-3 break-words whitespace-pre-wrap',
              line.kind === 'added' && 'bg-success-subtle/60 text-primary',
              line.kind === 'removed' && 'bg-danger-subtle/60 text-secondary',
              line.kind === 'same' && 'text-secondary',
            )}
          >
            <span aria-hidden="true" className="w-3 shrink-0 font-mono text-muted select-none">
              {line.kind === 'added' ? '+' : line.kind === 'removed' ? '−' : ' '}
            </span>
            {line.kind !== 'same' && (
              <span className="sr-only">{line.kind === 'added' ? 'Added: ' : 'Removed: '}</span>
            )}
            <span className="min-w-0 flex-1">{line.text || ' '}</span>
          </p>
        ),
      )}
    </div>
  )
}
