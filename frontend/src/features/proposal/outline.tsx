import { Circle, CircleCheck, GitCompareArrows } from 'lucide-react'
import { useSyncExternalStore } from 'react'

import type { ProposalSection } from '@/api/types'
import { CountBadge } from '@/components/ui/badge'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { cn } from '@/lib/utils'

import { openThreadCount, useProposalEditor } from './editor-context'
import {
  focusResearchAppendix,
  RESEARCH_APPENDIX_ID,
  useAnsweredResearch,
} from './research-appendix'
import type { ProposalSaveStore } from './save-store'
import { hasContent, sectionDomId } from './text'

/** Which sections have text, live from the editor (the outline's ticks). */
function useWritten(store: ProposalSaveStore, sections: readonly ProposalSection[]) {
  useSyncExternalStore(store.subscribe, store.getVersion)
  return new Map(
    sections.map((section) => [
      section.key,
      hasContent(store.get(section.key)?.draft ?? section.body_md),
    ]),
  )
}

function Tick({ written }: { written: boolean }) {
  return written ? (
    <CircleCheck aria-hidden="true" className="size-4 shrink-0 text-success" />
  ) : (
    <Circle aria-hidden="true" className="size-4 shrink-0 text-muted" />
  )
}

/**
 * The outline (wide screens): the eight sections as links that move focus to
 * the section, a tick for each one with text (shape, not just colour), the
 * open threads per section, and the section in view highlighted.
 */
export function Outline({
  sections,
  className,
}: {
  sections: readonly ProposalSection[]
  className?: string
}) {
  const { store, threads, suggestions, current, focusSection, ideaKey } = useProposalEditor()
  const written = useWritten(store, sections)
  const appendix = useAnsweredResearch(ideaKey)
  const done = [...written.values()].filter(Boolean).length
  return (
    <nav
      aria-labelledby="proposal-outline-heading"
      className={cn('sticky top-16 flex-col gap-2 self-start pt-8', className)}
    >
      <div className="flex items-baseline justify-between gap-2 px-2">
        <h2 id="proposal-outline-heading" className="text-xs font-medium text-muted">
          Outline
        </h2>
        <span className="text-xs text-muted tabular-nums">
          {done}/{sections.length}
          <span className="sr-only"> sections written</span>
        </span>
      </div>
      <ol className="flex flex-col gap-0.5">
        {sections.map((section) => {
          const count = openThreadCount(threads?.get(section.key))
          const suggested = suggestions.get(section.key)?.length ?? 0
          const isWritten = written.get(section.key) ?? false
          return (
            <li key={section.key}>
              <a
                href={`#${sectionDomId(section.key)}`}
                aria-current={current === section.key ? 'location' : undefined}
                onClick={(event) => {
                  event.preventDefault()
                  focusSection(section.key)
                }}
                className={cn(
                  'flex items-center gap-2 rounded-md px-2 py-1.5 text-sm text-secondary transition-colors',
                  'hover:bg-subtle hover:text-primary',
                  'aria-[current=location]:bg-subtle aria-[current=location]:font-medium aria-[current=location]:text-primary',
                )}
              >
                <Tick written={isWritten} />
                {/* One inline run, so the link's name reads "Risks, written, 1 open thread". */}
                <span className="min-w-0 flex-1 truncate">
                  {section.title}
                  <span className="sr-only">
                    {isWritten ? ', written' : ', not written yet'}
                    {count > 0 && `, ${String(count)} open ${count === 1 ? 'thread' : 'threads'}`}
                    {suggested > 0 &&
                      `, ${String(suggested)} ${suggested === 1 ? 'suggestion' : 'suggestions'}`}
                  </span>
                </span>
                {suggested > 0 && (
                  <span
                    aria-hidden="true"
                    title="Suggestions"
                    className="inline-flex items-center gap-0.5 text-xs font-medium text-accent tabular-nums"
                  >
                    <GitCompareArrows className="size-3.5" />
                    {suggested}
                  </span>
                )}
                {count > 0 && <CountBadge aria-hidden="true">{count}</CountBadge>}
              </a>
            </li>
          )
        })}
      </ol>
      {appendix && (
        // Phase 8: the research appendix the exports end with (not a section to write).
        <a
          href={`#${RESEARCH_APPENDIX_ID}`}
          onClick={(event) => {
            event.preventDefault()
            focusResearchAppendix()
          }}
          className="mt-1 flex items-center gap-2 rounded-md border-t border-subtle px-2 pt-2.5 pb-1.5 text-sm text-secondary transition-colors hover:bg-subtle hover:text-primary"
        >
          <span className="min-w-0 flex-1 truncate">Research and consultation</span>
        </a>
      )}
    </nav>
  )
}

/** Below `xl`: the outline as a jump list in the editor bar. */
export function SectionJump({
  sections,
  className,
}: {
  sections: readonly ProposalSection[]
  className?: string
}) {
  const { store, current, focusSection } = useProposalEditor()
  const written = useWritten(store, sections)
  return (
    <Select value={current} onValueChange={(value) => focusSection(value)}>
      <SelectTrigger aria-label="Jump to section" className={cn('w-36 xs:w-44 sm:w-52', className)}>
        <SelectValue>
          {(() => {
            const index = sections.findIndex((section) => section.key === current)
            return `${String(index + 1)}. ${sections[index]?.title ?? ''}`
          })()}
        </SelectValue>
      </SelectTrigger>
      <SelectContent align="end">
        {sections.map((section, index) => (
          <SelectItem key={section.key} value={section.key}>
            <Tick written={written.get(section.key) ?? false} />
            <span className="tabular-nums">{index + 1}.</span> {section.title}
            <span className="sr-only">
              {written.get(section.key) ? ', written' : ', not written yet'}
            </span>
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}
