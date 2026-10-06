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
import { WithTooltip } from '@/components/ui/tooltip'
import { focusWhenRendered } from '@/lib/focus'
import { cn } from '@/lib/utils'

import { useProposalEditor } from './editor-context'
import { useSectionSave } from './save-store'
import {
  hasContent,
  sectionDomId,
  suggestionDiff,
  type DiffPart,
  type SuggestionLine,
} from './text'

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
  const { store, ideaKey, idea, suggestionPermissions, suggestions, me } = useProposalEditor()
  const queryClient = useQueryClient()
  const state = useSectionSave(store, section.key)
  const accept = useAcceptProposalSuggestion(ideaKey)
  const discard = useDiscardProposalSuggestion(ideaKey)
  const [theirs, setTheirs] = useState<ProposalSection | null>(null)
  const [confirming, setConfirming] = useState(false)
  // Accept waits for the section's own autosave first (then nothing is unsaved to ask about).
  const [settling, setSettling] = useState(false)
  const titleId = useId()

  // What the suggestion would replace: the text on screen, or what someone saved meanwhile.
  const current = theirs?.body_md ?? state?.draft ?? section.body_md
  const lines = useMemo(() => suggestionDiff(current, suggestion.body_md), [current, suggestion])
  const decides = suggestionPermissions.can_decide
  // Deciders compare; everyone else reads what is proposed (a raw-Markdown diff helps no reader).
  const [view, setView] = useState<View>(decides && hasContent(current) ? 'changes' : 'preview')
  const saving = state?.status === 'saving'
  const ai = suggestion.source === 'ai'
  const author = authorName(suggestion)
  const byMe = suggestion.author?.id === me.id
  const whose = byMe ? 'Your' : `${author}’s`

  /**
   * After the card goes, like working through a queue: the next pending
   * suggestion in template order (this section's first, then the following
   * sections', then from the top), else the section's text.
   */
  const focusAfter = () => {
    const queue = [...suggestions.values()].flat()
    const index = queue.findIndex((item) => item.id === suggestion.id)
    const next = queue[index + 1] ?? queue.find((item) => item.id !== suggestion.id)
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
    // Read now, not at render: an autosave may have finished since.
    const latest = store.get(section.key)
    const before = latest?.draft ?? section.body_md
    const baseVersion = theirs?.version ?? latest?.base ?? section.version
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

  const onAccept = async () => {
    if (theirs) {
      run()
      return
    }
    // Typing still waiting for its autosave: send it first. Accept has Undo, so a
    // question is needed only when the text really couldn't be saved.
    setSettling(true)
    try {
      await store.settle(section.key)
    } finally {
      setSettling(false)
    }
    const latest = store.get(section.key)
    const unsaved = Boolean(latest && (latest.draft !== latest.saved || latest.status !== 'saved'))
    if (unsaved) setConfirming(true)
    else run()
  }

  const onDiscard = () => {
    focusAfter()
    discard(
      suggestion,
      byMe ? 'Your suggestion discarded' : `${author}’s suggestion discarded`,
      // Undo brings the card back: focus goes back to it.
      () =>
        focusWhenRendered(() => document.getElementById(suggestionDomId(suggestion.id)), {
          force: true,
        }),
    )
  }

  /** Who may accept it, for everyone who can't. */
  const decider =
    idea.status !== 'shortlisted' && idea.status !== 'proposal'
      ? 'It can be accepted while the idea is Shortlisted or in Proposal.'
      : idea.owner && idea.owner.id !== me.id
        ? `${idea.owner.display_name} decides whether to use it.`
        : 'The idea’s owner or an admin decides whether to use it.'

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
        {/* On phones the view toggle goes below, so the author's name keeps its room. */}
        <div className="flex min-w-0 flex-1 items-center gap-2 max-sm:basis-full">
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
            <WithTooltip
              content={`Sent from an AI assistant (an MCP client) with ${byMe ? 'your' : `${author}’s`} key`}
            >
              <Badge variant="outline">
                via assistant
                <span className="sr-only">, sent from an AI assistant with their key</span>
              </Badge>
            </WithTooltip>
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

      {/* Long suggestions scroll here; focusable so the keyboard can scroll it too. */}
      <div
        role="region"
        aria-label={
          view === 'preview'
            ? `${whose} suggested text for ${section.title}`
            : `${whose} suggested changes to ${section.title}`
        }
        // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
        tabIndex={0}
        className="max-h-80 overflow-y-auto focus-visible:-outline-offset-2"
      >
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

      {decides ? (
        <footer className="flex flex-wrap items-center justify-end gap-2 border-t border-subtle px-3 py-2">
          {ai && (
            <p className="mr-auto text-xs text-muted">Written by an AI agent: check the facts.</p>
          )}
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
            loading={accept.isPending || settling}
            disabled={saving && !settling}
            onClick={() => void onAccept()}
            aria-label={`${theirs ? 'Accept anyway' : 'Accept'}: ${byMe ? 'your' : `${author}’s`} suggestion for ${section.title}`}
          >
            <Check />
            {theirs ? 'Accept anyway' : 'Accept'}
          </Button>
        </footer>
      ) : (
        <footer className="border-t border-subtle px-3 py-2 text-xs text-muted">{decider}</footer>
      )}

      <Dialog open={confirming} onOpenChange={setConfirming}>
        <DialogContent size="sm" role="alertdialog">
          <DialogHeader>
            <DialogTitle>Replace your unsaved changes?</DialogTitle>
            <DialogDescription>
              Your latest changes to {section.title} couldn’t be saved. Accepting replaces the whole
              section with the suggestion, including what isn’t saved.
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

/**
 * The unified diff: removed and added lines marked by sign and words, not colour
 * alone. A blank line is a paragraph break: a short gap in its band's colour, with
 * no sign or words of its own.
 */
function DiffLines({ lines }: { lines: SuggestionLine[] }) {
  return (
    <div className="py-1.5 text-sm leading-relaxed">
      {lines.map((line, index) =>
        line.kind === 'skip' ? (
          <p key={index} className="px-3 py-0.5 text-muted italic">
            {line.count === 1 ? '1 unchanged line' : `${String(line.count)} unchanged lines`}
          </p>
        ) : line.text.trim() === '' ? (
          <div
            key={index}
            aria-hidden="true"
            className={cn(
              'h-2',
              line.kind === 'added' && 'bg-success-subtle/60',
              line.kind === 'removed' && 'bg-danger-subtle/60',
            )}
          />
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
            <span className="min-w-0 flex-1">
              {line.parts ? <WordParts parts={line.parts} kind={line.kind} /> : line.text}
            </span>
          </p>
        ),
      )}
    </div>
  )
}

/**
 * An edited line, word by word: what the other side doesn't have is marked
 * (deleted or inserted, read as such by assistive tech that supports it) in a
 * stronger tone than its line.
 */
function WordParts({ parts, kind }: { parts: DiffPart[]; kind: SuggestionLine['kind'] }) {
  return parts.map((part, index) =>
    !part.changed ? (
      <span key={index}>{part.text}</span>
    ) : kind === 'removed' ? (
      <del
        key={index}
        className="rounded-xs bg-danger/20 text-primary no-underline dark:bg-danger/40"
      >
        {part.text}
      </del>
    ) : (
      <ins
        key={index}
        className="rounded-xs bg-success/25 text-primary no-underline dark:bg-success/40"
      >
        {part.text}
      </ins>
    ),
  )
}
