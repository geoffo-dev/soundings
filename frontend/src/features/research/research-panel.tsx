import { useQueryClient } from '@tanstack/react-query'
import {
  ChevronRight,
  Circle,
  CircleAlert,
  CircleCheck,
  CloudOff,
  FileSearch,
  Sparkles,
} from 'lucide-react'
import { useEffect, useId, useRef, useState } from 'react'

import { describeError } from '@/api/errors'
import { queryKeys } from '@/api/keys'
import { useAnswerResearchItem, useClearResearchItem, useIdeaResearch } from '@/api/research'
import type { IdeaResearch, IdeaResearchItem } from '@/api/types'
import { deferUntilToastCloses } from '@/api/undo'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { RelativeTime } from '@/components/ui/relative-time'
import { Skeleton, SkeletonGroup } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { KIND_COPY } from '@/features/ai/ai-copy'
import { researchNoteDomId } from '@/features/ai/dom-ids'
import { showRun, useAskAi, useIdeaAi } from '@/features/ai/idea-ai'
import { useIdeaPage } from '@/features/idea/idea-context'
import { readDraft, writeDraft } from '@/lib/drafts'
import { focusWhenRendered } from '@/lib/focus'
import { gatedStatuses } from '@/lib/status'
import { cn } from '@/lib/utils'

import { RESEARCH_HEADING_TOGGLE_ID, ResearcherLine } from './research-assignment'
import { progressWords } from './research-copy'
import { takeResearchFocus, useResearchFocusRequest } from './research-focus'
import { SimilarIdeas } from './similar-ideas'

export const ANSWER_MAX_LENGTH = 2000

/** The DOM id of an item's answer field (focus moves there). */
export const answerFieldId = (itemId: string) => `research-answer-${itemId}`

/**
 * The idea page's Research panel (contract-phase8 §3.13), on the Overview tab while
 * the project's research step is on: the checklist with free-text answers (the owner
 * and admins write, edit and clear them; everyone who can open the idea reads them,
 * pending evaluators too), the progress, "Similar ideas" and "Ask AI to research".
 * It starts open while the idea is in Research, and in the status before it for the
 * people who answer (the owner and admins); folded otherwise (UX review m2).
 */
export function ResearchPanel() {
  const { ideaKey, idea, guest, researchStep: step, statusLabel } = useIdeaPage()
  const research = useIdeaResearch(ideaKey, { enabled: step !== 'off' })
  const [open, setOpen] = useState(
    () =>
      idea.status === 'research' ||
      (idea.research !== null && idea.permissions.can_answer_research),
  )
  const headingRef = useRef<HTMLButtonElement>(null)
  const bodyId = useId()

  // "Open research" (the gate's dialog, "Finish research"): open, scroll and focus.
  const focusRequest = useResearchFocusRequest()
  const data = research.data
  useEffect(() => {
    if (!data || !takeResearchFocus(ideaKey)) return
    // Open the panel, then (once it has rendered open) scroll to and focus the first
    // required item that is still open, or the heading's button for readers.
    window.requestAnimationFrame(() => {
      setOpen(true)
      window.requestAnimationFrame(() => {
        const firstOpen = data.items.find((item) => item.required && !item.answer)
        const field = firstOpen && document.getElementById(answerFieldId(firstOpen.item_id))
        const target = field ?? headingRef.current
        target?.scrollIntoView({ block: 'center' })
        target?.focus({ preventScroll: true })
      })
    })
  }, [focusRequest, data, ideaKey])

  if (step === 'off') return null

  // Phase 8b: the label comes with the panel (a guest researcher can't read the project).
  const gateLabel =
    data?.gate_status_label ?? (data?.gate_status ? statusLabel(data.gate_status) : null)
  return (
    <section
      id="research"
      aria-labelledby="research-heading"
      className="flex scroll-mt-6 flex-col gap-3 rounded-lg border bg-surface"
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 pt-3 pb-1">
        <h2 id="research-heading" className="text-base font-semibold text-primary">
          <button
            ref={headingRef}
            id={RESEARCH_HEADING_TOGGLE_ID}
            type="button"
            aria-expanded={open}
            aria-controls={bodyId}
            onClick={() => setOpen((value) => !value)}
            className="-ml-1 flex min-w-0 items-center gap-1.5 rounded-md px-1 py-0.5 text-left hover:bg-subtle"
          >
            <ChevronRight
              aria-hidden="true"
              className={cn(
                'size-4 shrink-0 text-muted transition-transform duration-150',
                open && 'rotate-90',
              )}
            />
            Research
          </button>
        </h2>
        {data && (
          <ProgressLine
            research={data}
            gateLabel={gateLabel}
            inResearch={idea.status === 'research'}
          />
        )}
      </div>
      <div id={bodyId} hidden={!open} className="flex flex-col gap-5 px-4 pb-4">
        {research.isPending ? (
          <ResearchSkeleton />
        ) : research.isError ? (
          <div role="alert" className="flex flex-wrap items-center gap-3 text-sm text-secondary">
            <CloudOff aria-hidden="true" className="size-4 text-muted" />
            We couldn’t load the research checklist.
            <Button size="sm" variant="outline" onClick={() => void research.refetch()}>
              Try again
            </Button>
          </div>
        ) : (
          <>
            <ResearcherLine />
            {data && data.items.length > 0 ? (
              <ol className="flex flex-col divide-y divide-subtle" aria-label="Research checklist">
                {data.items.map((item) => (
                  <ResearchItemRow
                    key={item.item_id}
                    item={item}
                    canAnswer={data.permissions.can_answer}
                    // Past Research a required answer is kept: edit it, never clear it
                    // (code review M1: answers that let the idea through stay on record).
                    keepAnswer={item.required && gatedStatuses(step).includes(idea.status)}
                  />
                ))}
              </ol>
            ) : (
              <p className="text-sm text-muted">This project’s checklist has no items yet.</p>
            )}
            <SimilarIdeas ideaKey={ideaKey} />
            {/* No AI panel for a guest researcher (role matrix column R). */}
            {!guest && <AiResearch />}
          </>
        )}
      </div>
    </section>
  )
}

/**
 * "1 of 3 answered · 2 required items left before Evaluating": in the warning colour
 * only once the idea is in Research (before that the checklist is a heads-up, not a
 * hold-up: UX review m2).
 */
function ProgressLine({
  research,
  gateLabel,
  inResearch,
}: {
  research: IdeaResearch
  gateLabel: string | null
  inResearch: boolean
}) {
  const { progress, blocking } = research
  if (progress.total === 0) return null
  const open = progress.required_open
  return (
    <p className="text-sm text-muted tabular-nums" aria-live="polite">
      {progressWords(progress)}
      {blocking && gateLabel ? (
        <>
          {' · '}
          <span className={inResearch ? 'text-warning' : undefined}>
            {open} required {open === 1 ? 'item' : 'items'} left before {gateLabel}
          </span>
        </>
      ) : open === 0 ? (
        <>
          {' · '}
          <span className="text-success">Research complete</span>
        </>
      ) : null}
    </p>
  )
}

function ResearchSkeleton() {
  return (
    <SkeletonGroup label="Loading the research checklist" className="flex flex-col gap-4">
      {[0, 1, 2].map((i) => (
        <div key={i} className="flex flex-col gap-2">
          <Skeleton className="h-4 w-56" />
          <Skeleton className="h-16 w-full" />
        </div>
      ))}
    </SkeletonGroup>
  )
}

/** "Answered by Bob Chen · 3 days ago" (and who changed it since). */
function AnswerMeta({ item }: { item: IdeaResearchItem }) {
  const answer = item.answer
  if (!answer) return null
  const edited =
    answer.updated_at !== answer.answered_at &&
    (answer.updated_by?.id !== answer.answered_by?.id ||
      Date.parse(answer.updated_at) - Date.parse(answer.answered_at) > 60_000)
  return (
    <p className="text-xs text-muted">
      Answered by {answer.answered_by?.display_name ?? 'someone'} ·{' '}
      <RelativeTime date={answer.answered_at} />
      {edited && (
        <>
          {' · edited by '}
          {answer.updated_by?.display_name ?? 'someone'} · <RelativeTime date={answer.updated_at} />
        </>
      )}
    </p>
  )
}

/** The name of an unsent answer in lib/drafts (per user, cleared when the session ends). */
export const answerDraftName = (ideaKey: string, itemId: string) => `research:${ideaKey}:${itemId}`

function ResearchItemRow({
  item,
  canAnswer,
  keepAnswer,
}: {
  item: IdeaResearchItem
  canAnswer: boolean
  /** Past Research, a required item: its answer can change but not be cleared. */
  keepAnswer: boolean
}) {
  const { ideaKey, me } = useIdeaPage()
  const queryClient = useQueryClient()
  const answer = useAnswerResearchItem(ideaKey)
  const clear = useClearResearchItem(ideaKey)
  const saved = item.answer?.answer ?? ''
  const draftName = answerDraftName(ideaKey, item.item_id)
  // An answer typed and not saved survives leaving the page (UX review M1): it comes
  // back from lib/drafts with "Unsaved draft restored" and the usual Discard.
  const [draft, setDraft] = useState(() => {
    if (!canAnswer) return saved
    const kept = readDraft(me.id, draftName)
    if (!kept?.trim() || kept.trim() === saved.trim()) return saved
    return kept
  })
  const [restored, setRestored] = useState(() => draft !== saved)
  const [baseline, setBaseline] = useState(saved)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState('')
  const fieldRef = useRef<HTMLTextAreaElement>(null)
  const errorId = useId()
  const hintId = useId()
  // The server's answer changed (someone else, a refetch): follow it unless you are typing.
  if (saved !== baseline) {
    setBaseline(saved)
    if (draft === baseline) setDraft(saved)
  }
  const dirty = draft.trim() !== saved.trim()
  const answered = item.answer !== null
  const length = draft.trim().length
  const tooLong = length > ANSWER_MAX_LENGTH

  /** Keeps what you typed (forgotten once empty or back to the saved answer). */
  const keep = (value: string) => {
    setDraft(value)
    const unsaved = value.trim() !== '' && value.trim() !== saved.trim()
    writeDraft(me.id, draftName, unsaved ? value : null)
  }
  const forget = () => {
    writeDraft(me.id, draftName, null)
    setRestored(false)
  }

  const save = () => {
    if (answer.isPending) return
    const text = draft.trim()
    if (!text) {
      setError(
        keepAnswer
          ? 'This idea is past Research: change the answer, but keep one.'
          : 'Write an answer first, or use Clear to remove it.',
      )
      fieldRef.current?.focus()
      return
    }
    if (tooLong) {
      setError(`Keep it to ${ANSWER_MAX_LENGTH.toLocaleString()} characters.`)
      fieldRef.current?.focus()
      return
    }
    setError(null)
    answer.mutate(
      { itemId: item.item_id, answer: text },
      {
        onSuccess: () => {
          forget()
          setNotice(answered ? 'Answer updated' : 'Answer saved')
          // The Save button goes away once saved: focus stays with the field.
          fieldRef.current?.focus()
        },
        onError: (failure) => {
          const { title, description } = describeError(failure)
          setError(description ? `${title}. ${description}` : title)
        },
      },
    )
  }

  const discard = () => {
    setDraft(saved)
    forget()
    setError(null)
    fieldRef.current?.focus()
  }

  /** Deferred (Undo in the toast): the answer goes when the toast closes. */
  const clearAnswer = () => {
    const key = queryKeys.research.checklist(ideaKey)
    const before = queryClient.getQueryData<IdeaResearch>(key)
    if (!before) return
    deferUntilToastCloses({
      title: `Answer to “${item.title}” cleared`,
      hide: () => {
        queryClient.setQueryData<IdeaResearch>(key, (current) =>
          current
            ? {
                ...current,
                items: current.items.map((row) =>
                  row.item_id === item.item_id ? { ...row, answer: null } : row,
                ),
                progress: {
                  ...current.progress,
                  answered: current.progress.answered - 1,
                  required_open: current.progress.required_open + (item.required ? 1 : 0),
                },
              }
            : current,
        )
        setDraft('')
        forget()
        fieldRef.current?.focus()
      },
      restore: () => {
        queryClient.setQueryData(key, before)
        setDraft(saved)
      },
      commit: () => clear.mutateAsync({ itemId: item.item_id }),
      errorTitle: 'Couldn’t clear the answer',
    })
  }

  const fieldId = answerFieldId(item.item_id)
  // The hint says what to write: shown under the title (not as a placeholder that goes
  // once you type) and read with the field (UX review m3). Readers see it until answered.
  const showHint = Boolean(item.hint) && (canAnswer || !item.answer)
  const described = [showHint ? hintId : null, error ? errorId : null].filter(Boolean).join(' ')
  return (
    <li className="flex flex-col gap-2 py-3 first:pt-0 last:pb-0">
      <div className="flex items-start gap-2">
        {answered ? (
          <CircleCheck aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-success" />
        ) : (
          <Circle aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-muted" />
        )}
        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-x-2 gap-y-1">
          {canAnswer ? (
            <label htmlFor={fieldId} className="text-sm font-medium text-primary">
              {item.title}
            </label>
          ) : (
            <h3 className="text-sm font-medium text-primary">{item.title}</h3>
          )}
          {item.required ? (
            <Badge variant="outline">Required</Badge>
          ) : (
            <span className="text-xs text-muted">Optional</span>
          )}
        </div>
      </div>
      <div className="flex flex-col gap-1.5 pl-6">
        {showHint && (
          <p id={hintId} className="text-sm text-muted">
            {item.hint}
          </p>
        )}
        {canAnswer ? (
          <>
            <Textarea
              id={fieldId}
              ref={fieldRef}
              value={draft}
              minRows={2}
              maxRows={10}
              placeholder={item.hint ? undefined : 'Write what you found'}
              aria-invalid={error ? true : undefined}
              aria-describedby={described || undefined}
              aria-keyshortcuts="Control+Enter Meta+Enter"
              onChange={(event) => {
                keep(event.target.value)
                setNotice('')
                if (error) setError(null)
              }}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
                  event.preventDefault()
                  save()
                } else if (event.key === 'Escape') {
                  // Escape only leaves the field: what you typed stays (and is kept), so
                  // nothing is thrown away by a key press (UX review m5). Discard does that.
                  event.preventDefault()
                  event.stopPropagation()
                  event.currentTarget.blur()
                }
              }}
            />
            {error && (
              <p id={errorId} role="alert" className="flex items-start gap-1.5 text-sm text-danger">
                <CircleAlert aria-hidden="true" className="mt-0.5 size-3.5 shrink-0" />
                {error}
              </p>
            )}
            {(dirty || answered) && (
              <div className="flex min-h-7 flex-wrap items-center gap-x-3 gap-y-1">
                <div className="mr-auto">
                  {dirty ? (
                    <p
                      className={cn('text-xs tabular-nums', tooLong ? 'text-danger' : 'text-muted')}
                    >
                      {restored && (
                        <span className="text-secondary">Unsaved draft restored · </span>
                      )}
                      {length.toLocaleString()} / {ANSWER_MAX_LENGTH.toLocaleString()}
                    </p>
                  ) : (
                    <AnswerMeta item={item} />
                  )}
                </div>
                {dirty ? (
                  <>
                    <Button size="sm" variant="ghost" onClick={discard} disabled={answer.isPending}>
                      Discard
                    </Button>
                    <Button size="sm" variant="primary" loading={answer.isPending} onClick={save}>
                      {answered ? 'Save changes' : 'Save answer'}
                    </Button>
                  </>
                ) : keepAnswer ? null : (
                  <Button
                    size="sm"
                    variant="ghost"
                    aria-label={`Clear the answer to ${item.title}`}
                    onClick={clearAnswer}
                  >
                    Clear
                  </Button>
                )}
              </div>
            )}
            <span aria-live="polite" className="sr-only">
              {notice}
            </span>
          </>
        ) : item.answer ? (
          <>
            <p className="text-sm break-words whitespace-pre-wrap text-secondary">
              {item.answer.answer}
            </p>
            <AnswerMeta item={item} />
          </>
        ) : (
          <p className="text-sm text-muted italic">Not answered yet</p>
        )}
      </div>
    </li>
  )
}

/**
 * "Ask AI to research" (the Phase 6 research run, the same words as the AI menu) and,
 * once a run has saved one, a line pointing at its note in the feed (UX review m7).
 */
function AiResearch() {
  const { ideaKey } = useIdeaPage()
  const ai = useIdeaAi(ideaKey)
  const note = ai.runs
    .filter((run) => run.kind === 'research' && run.status === 'succeeded' && run.result.note_id)
    .sort(
      (a, b) =>
        Date.parse(b.finished_at ?? b.created_at) - Date.parse(a.finished_at ?? a.created_at),
    )[0]
  const ask = ai.aiEnabled && ai.allowed('research')
  if (!note && !ask) return null
  return (
    <div className="flex flex-col gap-3 border-t border-subtle pt-4">
      {note?.result.note_id && (
        <p className="flex flex-wrap items-center gap-x-1.5 text-sm text-secondary">
          <Sparkles aria-hidden="true" className="size-3.5 text-muted" />
          Note from {note.agent.display_name} ·{' '}
          <RelativeTime date={note.finished_at ?? note.created_at} className="text-muted" /> ·
          <button
            type="button"
            className="font-medium text-accent underline-offset-4 hover:underline"
            onClick={() => {
              const id = note.result.note_id
              if (id) {
                focusWhenRendered(() => document.getElementById(researchNoteDomId(id)), {
                  force: true,
                  frames: 60,
                })
              }
            }}
          >
            Read it
          </button>
        </p>
      )}
      {ask && <AskAiToResearch />}
    </div>
  )
}

/** "Ask AI to research" (the Phase 6 research run; its note lands in the feed). */
function AskAiToResearch() {
  const { ideaKey, setTab } = useIdeaPage()
  const ai = useIdeaAi(ideaKey)
  const { ask, pending } = useAskAi(ideaKey, setTab)
  const active = ai.activeRun('research')
  const agents = ai.agentsFor('research')
  const describedBy = 'research-ai-hint'
  const label = KIND_COPY.research.action
  if (active) {
    return (
      <div className="flex flex-wrap items-center gap-3">
        <Button size="sm" variant="outline" onClick={() => showRun(active.id, setTab)}>
          <Sparkles /> Researching… view progress
        </Button>
      </div>
    )
  }
  const first = agents[0]
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
      {agents.length > 1 ? (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button size="sm" variant="outline" aria-describedby={describedBy}>
              <FileSearch /> {label}
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start">
            <DropdownMenuLabel>Which agent?</DropdownMenuLabel>
            {agents.map((agent) => (
              <DropdownMenuItem key={agent.id} onSelect={() => ask('research', agent)}>
                {agent.display_name}
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
      ) : (
        first && (
          <Button
            size="sm"
            variant="outline"
            aria-describedby={describedBy}
            loading={pending}
            onClick={() => ask('research', first)}
          >
            <FileSearch /> {label}
          </Button>
        )
      )}
      <p id={describedBy} className="text-sm text-muted">
        An AI agent looks for similar work and writes a note in the feed. Check it before you rely
        on it.
      </p>
    </div>
  )
}
