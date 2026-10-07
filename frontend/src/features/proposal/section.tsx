import { Bold, CircleAlert, Italic, Link2, List, MessageSquare } from 'lucide-react'
import { useId, useRef, type KeyboardEvent, type ReactNode, type RefObject } from 'react'

import type { ProposalSection } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Callout } from '@/components/ui/callout'
import { Markdown } from '@/components/ui/markdown'
import { SegmentedControl } from '@/components/ui/segmented-control'
import { Spinner } from '@/components/ui/spinner'
import { Textarea } from '@/components/ui/textarea'
import { WithTooltip } from '@/components/ui/tooltip'
import { describeError } from '@/api/errors'
import { DraftWithAiButton, SectionDraftProgress } from '@/features/ai/draft-with-ai'
import { SHORTCUTS } from '@/lib/shortcuts'
import { cn } from '@/lib/utils'

import { ConflictPrompt } from './conflict'
import { openThreadCount, useProposalEditor } from './editor-context'
import { applyFormat, type FormatKind } from './format'
import { useSectionSave, type SectionSaveState } from './save-store'
import { countWords, MARKDOWN_HINT_ID, SECTION_LIMIT, sectionDomId, wordLabel } from './text'
import { SectionSuggestions } from './suggestions'
import { SectionThreads } from './threads'

const isMod = (event: KeyboardEvent) => event.metaKey || event.ctrlKey

/**
 * One template section: its heading, word count and save state, the text
 * (Write / Preview for editors; rendered Markdown for readers) and, from `lg`
 * up, its margin threads beside it.
 */
export function SectionRow({ section, index }: { section: ProposalSection; index: number }) {
  const { store, permissions, modeOf, toggleSectionMode, threads, current, setCurrent, ideaKey } =
    useProposalEditor()
  const state = useSectionSave(store, section.key)
  const headingId = useId()
  const fieldRef = useRef<HTMLTextAreaElement>(null)
  const text = state?.draft ?? section.body_md
  const mode = permissions.can_edit ? modeOf(section.key) : 'preview'

  const toggleMode = () => toggleSectionMode(section.key)

  return (
    <section
      id={sectionDomId(section.key)}
      data-section-key={section.key}
      aria-labelledby={headingId}
      onFocus={() => setCurrent(section.key)}
      className="group/section grid scroll-mt-16 gap-x-8 gap-y-4 border-b border-subtle py-7 last:border-b-0 lg:grid-cols-[minmax(0,1fr)_17rem] lg:py-8"
    >
      <div className="flex min-w-0 flex-col gap-3" data-section-body="">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <h2
            id={headingId}
            data-section-heading=""
            tabIndex={-1}
            className="rounded-sm text-lg font-semibold text-primary"
          >
            <span className="text-muted tabular-nums">{index + 1}.</span> {section.title}
          </h2>
          <span className="text-xs text-muted tabular-nums">{wordLabel(countWords(text))}</span>
          {permissions.can_edit && state && <SectionSaveBadge state={state} />}
          <div className="ml-auto flex items-center gap-1.5">
            <DraftWithAiButton
              ideaKey={ideaKey}
              section={section}
              // One "Draft with AI" at a time, not eight: the current section's (in view or
              // focused), and any other's on hover or keyboard focus. Touch: the current one.
              className={
                current === section.key
                  ? undefined
                  : 'opacity-0 group-focus-within/section:opacity-100 group-hover/section:opacity-100 focus-visible:opacity-100 pointer-coarse:hidden'
              }
            />
            {permissions.can_edit && (
              <SegmentedControl
                size="sm"
                aria-label={`${section.title}: write or preview`}
                value={mode}
                onValueChange={(value) => {
                  if (value !== mode) toggleMode()
                }}
                options={[
                  { value: 'write', label: 'Write' },
                  { value: 'preview', label: 'Preview' },
                ]}
              />
            )}
            <MobileCommentsButton sectionKey={section.key} title={section.title} />
          </div>
        </div>

        <SectionDraftProgress ideaKey={ideaKey} section={section} />

        {state?.status === 'conflict' && state.conflict && (
          <ConflictPrompt sectionKey={section.key} theirs={state.conflict} yours={state.draft} />
        )}

        {permissions.can_edit && mode === 'write' ? (
          <SectionWriter
            section={section}
            value={text}
            fieldRef={fieldRef}
            onChange={(value) => store.edit(section.key, value)}
          />
        ) : (
          <div
            id={`${sectionDomId(section.key)}-preview`}
            tabIndex={permissions.can_edit ? -1 : undefined}
            role={permissions.can_edit ? 'region' : undefined}
            aria-label={permissions.can_edit ? `${section.title} (preview)` : undefined}
            className={cn(
              'rounded-lg',
              permissions.can_edit && 'min-h-24 border border-dashed border-subtle px-3.5 py-3',
            )}
          >
            {text.trim() ? (
              <Markdown nested>{text}</Markdown>
            ) : (
              <p className="text-base text-muted">
                {permissions.can_edit ? 'Nothing to preview yet.' : 'Not written yet.'}
              </p>
            )}
          </div>
        )}

        {state?.status === 'error' && (
          <Callout
            tone="danger"
            role="alert"
            title="Not saved"
            action={
              <Button size="sm" onClick={() => void store.saveNow(section.key)}>
                Retry
              </Button>
            }
          >
            {describeError(state.error).title}. Your text is still here.
          </Callout>
        )}

        <SectionSuggestions section={section} />
      </div>

      <aside aria-label={`Comments on ${section.title}`} className="hidden min-w-0 lg:block">
        <SectionThreads
          sectionKey={section.key}
          sectionTitle={section.title}
          threads={threads?.get(section.key)}
          variant="margin"
        />
      </aside>
    </section>
  )
}

function SectionSaveBadge({ state }: { state: SectionSaveState }) {
  if (state.status === 'saving' || state.status === 'dirty') {
    return (
      <span className="flex items-center gap-1 text-xs text-muted">
        {state.status === 'saving' && <Spinner className="size-3" />}
        {state.status === 'saving' ? 'Saving…' : 'Editing'}
      </span>
    )
  }
  if (state.status === 'error') {
    return (
      <span className="flex items-center gap-1 text-xs font-medium text-danger">
        <CircleAlert aria-hidden="true" className="size-3.5" />
        Not saved
      </span>
    )
  }
  // Saved: the editor bar says so (and when) for the whole proposal; once is enough.
  return null
}

/** Below `lg`: "Comments (2)" opens the section's comments in a sheet. */
function MobileCommentsButton({
  sectionKey,
  title,
}: {
  sectionKey: ProposalSection['key']
  title: string
}) {
  const { threads, setSheetFor, permissions, setCurrent } = useProposalEditor()
  const list = threads?.get(sectionKey)
  const open = openThreadCount(list)
  const total = list?.length ?? 0
  if (!permissions.can_comment && total === 0) return null
  return (
    <Button
      variant="ghost"
      size="sm"
      className="max-sm:h-9 lg:hidden"
      aria-label={
        total === 0
          ? `Comment on ${title}`
          : `Comments on ${title}: ${String(open)} open of ${String(total)}`
      }
      onClick={() => {
        setCurrent(sectionKey)
        setSheetFor(sectionKey)
      }}
    >
      <MessageSquare aria-hidden="true" />
      {total === 0 ? 'Comment' : open > 0 ? String(open) : 'Resolved'}
    </Button>
  )
}

const TOOLS: { kind: FormatKind; label: string; icon: ReactNode; keys?: string }[] = [
  { kind: 'bold', label: 'Bold', icon: <Bold />, keys: SHORTCUTS.proposalBold.keys },
  { kind: 'italic', label: 'Italic', icon: <Italic />, keys: SHORTCUTS.proposalItalic.keys },
  { kind: 'link', label: 'Link', icon: <Link2 /> },
  { kind: 'list', label: 'Bulleted list', icon: <List /> },
]

/**
 * The section's text: a native, auto-growing textarea (spellcheck, input
 * methods, screen readers all native) under a small Markdown toolbar.
 */
function SectionWriter({
  section,
  value,
  onChange,
  fieldRef,
}: {
  section: ProposalSection
  value: string
  onChange: (value: string) => void
  fieldRef: RefObject<HTMLTextAreaElement | null>
}) {
  const near = value.length > SECTION_LIMIT * 0.9
  const format = (kind: FormatKind) => {
    const field = fieldRef.current
    if (field) onChange(applyFormat(field, kind))
  }
  return (
    <div
      className={cn(
        'flex flex-col rounded-lg border border-input bg-surface transition-[border-color,box-shadow] duration-150',
        'has-[textarea:focus-visible]:border-focus has-[textarea:focus-visible]:ring-3 has-[textarea:focus-visible]:ring-focus/20',
      )}
    >
      <div
        role="toolbar"
        aria-label={`${section.title}: formatting`}
        aria-controls={`${sectionDomId(section.key)}-text`}
        className="flex items-center gap-0.5 border-b border-subtle px-1.5 py-1"
      >
        {TOOLS.map((tool) => (
          <WithTooltip key={tool.kind} content={tool.label} shortcut={tool.keys}>
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label={tool.label}
              // Keep the text selection: the button must not take focus on click.
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => format(tool.kind)}
            >
              {tool.icon}
            </Button>
          </WithTooltip>
        ))}
      </div>
      <Textarea
        id={`${sectionDomId(section.key)}-text`}
        ref={fieldRef}
        data-section-text=""
        value={value}
        aria-label={section.title}
        // "Markdown · saves as you type", once in the editor's bar.
        aria-describedby={MARKDOWN_HINT_ID}
        placeholder={section.prompt}
        spellCheck
        minRows={4}
        maxRows={400}
        maxLength={SECTION_LIMIT}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={(event) => {
          if (!isMod(event) || event.altKey || event.shiftKey) return
          const key = event.key.toLowerCase()
          if (key === 'b' || key === 'i') {
            event.preventDefault()
            format(key === 'b' ? 'bold' : 'italic')
          }
        }}
        className="rounded-t-none border-0 bg-transparent px-3.5 py-3 text-base leading-relaxed hover:border-0 focus-visible:ring-0"
      />
      {near && (
        <p className="border-t border-subtle px-3.5 py-1.5 text-right text-xs text-warning tabular-nums">
          {value.length.toLocaleString()} / {SECTION_LIMIT.toLocaleString()} characters
        </p>
      )}
    </div>
  )
}
