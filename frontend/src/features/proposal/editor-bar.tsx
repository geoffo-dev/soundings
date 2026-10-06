import {
  Check,
  ChevronDown,
  CircleAlert,
  CloudOff,
  FileDown,
  FileText,
  GitCompareArrows,
} from 'lucide-react'
import { useRef, useState, useSyncExternalStore } from 'react'

import { describeError, isApiError } from '@/api/errors'
import { useExportProposal, type ProposalExportFormat } from '@/api/proposals'
import type { Proposal } from '@/api/types'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { RelativeTime } from '@/components/ui/relative-time'
import { Spinner } from '@/components/ui/spinner'
import { toast } from '@/components/ui/toaster'
import { formatTime } from '@/lib/dates'

import { useProposalEditor } from './editor-context'
import { SectionJump } from './outline'
import { useEditorSaveSummary, type ProposalSaveStore } from './save-store'
import { suggestionDomId } from './suggestions'
import { hasContent, MARKDOWN_HINT_ID } from './text'

/**
 * The editor's bar, stuck to the top while scrolling: where saving is (or who
 * last edited, for readers), the section jump list below `xl`, and Export.
 */
export function EditorBar({ proposal }: { proposal: Proposal }) {
  const { permissions } = useProposalEditor()
  return (
    <div className="sticky top-0 z-10 -mx-4 flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-subtle bg-surface px-4 py-2.5 sm:-mx-6 sm:px-6 lg:mx-0 lg:px-0">
      <SaveState proposal={proposal} />
      {permissions.can_edit && (
        // Once for the whole editor (each section's text is described by it).
        <span id={MARKDOWN_HINT_ID} className="hidden text-xs text-muted md:inline">
          Markdown · saves as you type
        </span>
      )}
      <div className="ml-auto flex min-w-0 items-center gap-2">
        <SuggestionsJump />
        <SectionJump sections={proposal.sections} className="xl:hidden" />
        <ExportMenu />
      </div>
    </div>
  )
}

/**
 * "3 suggestions": jumps to the first one (the section's text stays where it
 * was). If they couldn't load, says so with a retry: the text is still editable.
 */
function SuggestionsJump() {
  const { suggestions, suggestionsError, retrySuggestions, setCurrent } = useProposalEditor()
  const all = [...suggestions.values()].flat()
  const first = all[0]
  if (suggestionsError) {
    return (
      <span role="alert" className="flex items-center gap-1 text-sm text-muted">
        <CloudOff aria-hidden="true" className="size-4" />
        <span className="max-sm:sr-only">Suggestions didn’t load.</span>
        <Button variant="ghost" size="sm" onClick={retrySuggestions}>
          Try again
          <span className="sr-only"> loading suggestions</span>
        </Button>
      </span>
    )
  }
  if (!first) return null
  return (
    <Button
      variant="ghost"
      size="sm"
      className="text-accent max-sm:px-2"
      aria-label={`${String(all.length)} ${all.length === 1 ? 'suggestion' : 'suggestions'}: go to the first`}
      onClick={() => {
        setCurrent(first.section_key)
        const card = document.getElementById(suggestionDomId(first.id))
        card?.scrollIntoView({ block: 'center', behavior: 'smooth' })
        card?.focus({ preventScroll: true })
      }}
    >
      <GitCompareArrows />
      {all.length}
      {/* Phones have less room: still a word, so "⇆ 3" doesn't have to be guessed. */}
      <span className="sm:hidden"> to review</span>
      <span className="hidden sm:inline">{all.length === 1 ? ' suggestion' : ' suggestions'}</span>
    </Button>
  )
}

function SaveState({ proposal }: { proposal: Proposal }) {
  const { store, permissions, focusSection, me } = useProposalEditor()
  const summary = useEditorSaveSummary(store, null)
  const lastEditor = proposal.sections
    .filter((section) => section.updated_by)
    .sort((a, b) => b.updated_at.localeCompare(a.updated_at))[0]

  let content
  if (!permissions.can_edit) {
    content = (
      <span className="text-muted">
        {lastEditor?.updated_by ? (
          <>
            Edited <RelativeTime date={lastEditor.updated_at} /> by{' '}
            {lastEditor.updated_by.display_name}
          </>
        ) : (
          <>
            Started <RelativeTime date={proposal.created_at} />
          </>
        )}
      </span>
    )
  } else if (summary.kind === 'saving') {
    content = (
      <span className="flex items-center gap-1.5 text-muted">
        <Spinner className="size-3.5" />
        Saving…
      </span>
    )
  } else if (summary.kind === 'conflict') {
    const first = store.all().find(([, state]) => state.status === 'conflict')?.[0]
    content = (
      <button
        type="button"
        onClick={() => first && focusSection(first)}
        className="flex items-center gap-1.5 rounded-sm font-medium text-warning hover:underline"
      >
        <GitCompareArrows aria-hidden="true" className="size-4" />
        {summary.count === 1
          ? 'A section changed while you were editing'
          : `${String(summary.count)} sections changed while you were editing`}
      </button>
    )
  } else if (summary.kind === 'unsaved') {
    const first = store.all().find(([, state]) => state.status === 'error')?.[0]
    content = (
      <button
        type="button"
        onClick={() => first && focusSection(first)}
        className="flex items-center gap-1.5 rounded-sm font-medium text-danger hover:underline"
      >
        <CircleAlert aria-hidden="true" className="size-4" />
        {summary.count === 1
          ? 'A section isn’t saved'
          : `${String(summary.count)} sections aren’t saved`}
      </button>
    )
  } else {
    content = (
      <span className="flex min-w-0 items-center gap-1.5 text-muted">
        <Check aria-hidden="true" className="size-4 shrink-0 text-success" />
        {summary.at ? (
          // Saved from this tab: when.
          <span>
            Saved<span className="hidden sm:inline"> {formatTime(summary.at)}</span>
          </span>
        ) : (
          <span className="min-w-0 truncate">
            Saved
            {lastEditor?.updated_by && (
              <span className="hidden sm:inline">
                {' '}
                · edited <RelativeTime date={lastEditor.updated_at} /> by{' '}
                {lastEditor.updated_by.id === me.id ? 'you' : lastEditor.updated_by.display_name}
              </span>
            )}
          </span>
        )}
      </span>
    )
  }
  return (
    <p role="status" aria-live="polite" className="min-w-0 text-sm">
      {content}
    </p>
  )
}

export const FORMAT_LABEL: Record<ProposalExportFormat, string> = {
  pdf: 'PDF',
  markdown: 'Markdown',
}

/**
 * Exporting (the menu and the ⌘K palette share it): pending saves go out
 * first, then the download; failures toast with Retry. One export at a time.
 */
export function useExportRunner(ideaKey: string, store: ProposalSaveStore) {
  const exporter = useExportProposal(ideaKey)
  const [format, setFormat] = useState<ProposalExportFormat | null>(null)
  const [announcement, setAnnouncement] = useState('')
  const busy = useRef(false)

  const run = (next: ProposalExportFormat) => {
    if (busy.current) return
    busy.current = true
    setFormat(next)
    setAnnouncement(`Preparing the ${FORMAT_LABEL[next]}…`)
    void store
      .flush()
      .then(() => exporter.mutateAsync(next))
      .then(() => setAnnouncement(`${FORMAT_LABEL[next]} downloaded.`))
      .catch((error: unknown) => {
        setAnnouncement('')
        const { title, description } = describeError(error)
        const wait =
          isApiError(error) && error.retryAfterSeconds
            ? ` Try again in ${String(error.retryAfterSeconds)} seconds.`
            : ''
        toast.error(`Couldn’t export the ${FORMAT_LABEL[next]}`, {
          description: `${[title, description].filter(Boolean).join('. ')}${wait}`,
          action: { label: 'Retry', onClick: () => run(next) },
        })
      })
      .finally(() => {
        busy.current = false
        setFormat(null)
      })
  }
  return { run, format, announcement }
}

/** Export (the view's primary action): PDF or Markdown. */
function ExportMenu() {
  const { permissions, exporting, store } = useProposalEditor()
  useSyncExternalStore(store.subscribe, store.getVersion)
  // Before exporting a half-written proposal: how much of it is still empty.
  const sections = store.all()
  const empty = sections.filter(([, state]) => !hasContent(state.draft)).length
  if (!permissions.can_export) return null
  const { run, format, announcement } = exporting
  const busy = format !== null
  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          {/* Busy, not disabled: focus comes back here when the menu closes. */}
          <Button variant="primary" aria-busy={busy || undefined} data-primary-action="">
            {busy && <Spinner />}
            {busy ? `Exporting ${FORMAT_LABEL[format]}…` : 'Export'}
            {!busy && <ChevronDown aria-hidden="true" />}
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="min-w-56">
          {empty > 0 && (
            <>
              <DropdownMenuLabel className="max-w-64 font-normal">
                {empty === sections.length
                  ? 'Nothing is written yet: every section exports empty.'
                  : `${String(empty)} of ${String(sections.length)} sections are still empty.`}
              </DropdownMenuLabel>
              <DropdownMenuSeparator />
            </>
          )}
          <DropdownMenuItem className="h-auto py-1.5 sm:h-auto" onSelect={() => run('pdf')}>
            <FileDown />
            <span className="flex flex-col">
              PDF
              <span className="text-xs text-muted">Branded, for sharing and print</span>
            </span>
          </DropdownMenuItem>
          <DropdownMenuItem className="h-auto py-1.5 sm:h-auto" onSelect={() => run('markdown')}>
            <FileText />
            <span className="flex flex-col">
              Markdown
              <span className="text-xs text-muted">Plain text, for editing elsewhere</span>
            </span>
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      <span aria-live="polite" className="sr-only">
        {announcement}
      </span>
    </>
  )
}
