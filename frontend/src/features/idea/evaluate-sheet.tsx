import { CircleAlert, CircleCheck, CloudOff, Lock } from 'lucide-react'
import { useEffect, useMemo, useRef, type KeyboardEvent } from 'react'

import { useMyEvaluation } from '@/api/evaluations'
import type { RubricCriterion } from '@/api/types'
import { Button } from '@/components/ui/button'
import { DueDateLabel } from '@/components/ui/due-date'
import { EmptyState } from '@/components/ui/empty-state'
import {
  Sheet,
  SheetBody,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import { Skeleton, SkeletonGroup } from '@/components/ui/skeleton'
import { useNow } from '@/components/ui/relative-time'
import { focusWithoutPreview } from '@/components/ui/segmented-control'
import { formatRelative } from '@/lib/dates'
import { SHORTCUTS } from '@/lib/shortcuts'
import { cn } from '@/lib/utils'

import { ariaKeys, ButtonShortcut } from '@/components/ui/kbd'
import { CriterionField, RecommendationField } from './criterion-field'
import {
  describeMissing,
  hasErrors,
  missingForSubmit,
  sameForm,
  scoredCount,
  type FormErrors,
} from './evaluation-form'
import { EvaluationReveal } from './evaluation-reveal'
import { useIdeaPage } from './idea-context'
import { LiveRegion, useLiveRegion } from './live-region'
import { useEvaluationSession, type SaveState } from './use-evaluation-session'

export interface EvaluateSheetProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

/** Focus the first criterion that still needs a score (or the recommendation). */
function focusFirstGap(root: HTMLElement | null, errors: FormErrors) {
  if (!root) return
  const first = errors.criteria[0]
  const group = first
    ? root.querySelector<HTMLElement>(`[data-criterion="${first}"]`)
    : errors.recommendation
      ? root.querySelector<HTMLElement>('[data-recommendation]')
      : null
  const radio =
    group?.querySelector<HTMLElement>('[role="radio"][data-state="checked"]') ??
    group?.querySelector<HTMLElement>('[role="radio"]')
  // Without previewing "1 · …" under it, which read as if 1 had been picked.
  if (radio) focusWithoutPreview(radio)
}

/**
 * The evaluate sheet (SPEC §5 screen 4, wireframe 04): a side sheet over the
 * idea (a full-height bottom sheet on phones) that opens at once with skeleton
 * rows while the rubric and your draft load. It stays mounted while you are an
 * evaluator on the page, so closing it never loses input.
 */
export function EvaluateSheet({ open, onOpenChange }: EvaluateSheetProps) {
  const { idea, ideaKey, project, me } = useIdeaPage()
  const mine = useMyEvaluation(ideaKey)
  const { message, announce } = useLiveRegion()
  const contentRef = useRef<HTMLDivElement>(null)
  const rubric = useMemo(
    () => (project ? [...project.rubric].sort((a, b) => a.position - b.position) : undefined),
    [project],
  )
  const session = useEvaluationSession({
    ideaKey,
    viewerId: me.id,
    rubric,
    mine: mine.data,
    announce,
    focusFirstGap: (errors) => focusFirstGap(contentRef.current, errors),
  })
  const { form, view, submitted, readOnly } = session

  const close = (next: boolean) => {
    if (!next) void session.flush()
    onOpenChange(next)
  }

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (view === 'form' && event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
      event.preventDefault()
      void session.submit()
    }
  }

  const ready = rubric !== undefined && form !== null

  // Where focus starts: the first criterion still to score (digits score it), Done
  // after submitting, Submit when all is scored; the sheet itself while loading.
  const focusStart = (root: HTMLElement) => {
    // Touch: no keyboard to score with, so don't put a focus ring on "1".
    if (!ready || window.matchMedia('(pointer: coarse)').matches) {
      root.focus()
      return
    }
    if (view === 'reveal') {
      root.querySelector<HTMLElement>('[data-sheet-done]')?.focus()
      return
    }
    const gaps = missingForSubmit(rubric, form)
    if (hasErrors(gaps)) focusFirstGap(root, gaps)
    else root.querySelector<HTMLElement>('[data-sheet-submit]')?.focus()
  }

  // Opened ("e" straight after the page loads) before the rubric or your draft
  // arrived: move in once they have, unless you have moved focus yourself.
  const wasReady = useRef(ready)
  useEffect(() => {
    const root = contentRef.current
    if (open && ready && !wasReady.current && root && document.activeElement === root) {
      focusStart(root)
    }
    wasReady.current = ready
  })

  return (
    <Sheet open={open} onOpenChange={close}>
      <SheetContent
        ref={contentRef}
        size="md"
        onKeyDown={onKeyDown}
        onOpenAutoFocus={(event) => {
          event.preventDefault()
          if (contentRef.current) focusStart(contentRef.current)
        }}
        onCloseAutoFocus={(event) => {
          event.preventDefault()
          // Back to the visible primary action (header or phone bar), else the page.
          const target =
            [...document.querySelectorAll<HTMLElement>('[data-primary-action]')].find(
              (element) => element.offsetParent !== null,
            ) ?? document.getElementById('main')
          target?.focus()
        }}
      >
        <LiveRegion message={message} />
        <SheetHeader className="gap-1.5">
          <SheetTitle>{view === 'reveal' ? 'Your evaluation' : 'Evaluate'}</SheetTitle>
          <SheetDescription className="truncate">
            <span className="tabular-nums">{idea.key}</span> · {idea.title}
          </SheetDescription>
          <div className="flex min-h-5 flex-wrap items-center gap-x-3 gap-y-1 text-sm">
            {view === 'form' && !submitted && (
              <DueDateLabel value={idea.evaluation_due_at} hideWhenNone />
            )}
            {ready && view === 'form' && !submitted && !readOnly && (
              <SaveStatus state={session.saveState} onRetry={() => void session.flush()} />
            )}
            {view === 'reveal' && mine.data?.submitted_at && (
              <span className="inline-flex items-center gap-1.5 text-secondary">
                <CircleCheck aria-hidden="true" className="size-3.5 text-success" />
                Submitted.{' '}
                {mine.data.editable
                  ? 'You can edit it until evaluation closes.'
                  : 'Evaluation is closed.'}
              </span>
            )}
            {submitted && view === 'form' && (
              <span className="text-secondary">
                Editing a submitted evaluation: others will see it marked as edited.
              </span>
            )}
          </div>
        </SheetHeader>

        {!ready ? (
          <SheetBody>
            {mine.isError ? (
              <EmptyState
                role="alert"
                size="compact"
                icon={<CloudOff />}
                title="We couldn’t load your evaluation"
                description="Your saved draft is safe. Check your connection and try again."
                action={
                  <Button size="sm" onClick={() => void mine.refetch()}>
                    Try again
                  </Button>
                }
              />
            ) : (
              <SkeletonGroup label="Loading the rubric" className="flex flex-col">
                {[0, 1, 2].map((i) => (
                  <div key={i} className="flex flex-col gap-2.5 border-b border-subtle py-5">
                    <Skeleton className="h-4 w-32" />
                    <Skeleton className="h-3.5 w-3/4" />
                    <Skeleton className="h-9 w-full" />
                  </div>
                ))}
              </SkeletonGroup>
            )}
          </SheetBody>
        ) : view === 'reveal' && session.baseline ? (
          <EvaluationReveal
            rubric={rubric}
            form={session.baseline}
            animate={session.justSubmitted}
          />
        ) : (
          <EvaluationFormBody rubric={rubric} session={session} />
        )}

        {ready && (
          <SheetFooter className="justify-between gap-3">
            {view === 'reveal' ? (
              <>
                {mine.data?.editable ? (
                  <Button variant="outline" onClick={session.editAgain} className="max-sm:h-11">
                    Edit my evaluation
                  </Button>
                ) : (
                  <span />
                )}
                <Button
                  variant="primary"
                  data-sheet-done=""
                  onClick={() => close(false)}
                  className="max-sm:h-11 max-sm:px-6"
                >
                  Done
                </Button>
              </>
            ) : readOnly ? (
              <>
                <span />
                <Button variant="outline" onClick={() => close(false)} className="max-sm:h-11">
                  Close
                </Button>
              </>
            ) : (
              <FormFooter rubric={rubric} session={session} />
            )}
          </SheetFooter>
        )}
      </SheetContent>
    </Sheet>
  )
}

type Session = ReturnType<typeof useEvaluationSession>

function EvaluationFormBody({ rubric, session }: { rubric: RubricCriterion[]; session: Session }) {
  const { form, errors, readOnly, submitted, closedMeanwhile, update } = session
  if (!form) return null
  const weightsDiffer = new Set(rubric.map((criterion) => criterion.weight)).size > 1
  return (
    <SheetBody className="pt-3">
      {readOnly && (
        <p
          role={closedMeanwhile ? 'alert' : undefined}
          className="mb-2 flex items-start gap-2 rounded-md bg-warning-subtle px-3 py-2 text-sm text-primary"
        >
          <Lock aria-hidden="true" className="mt-0.5 size-3.5 shrink-0 text-warning" />
          {closedMeanwhile
            ? 'Evaluation was closed, so your evaluation wasn’t submitted. Your draft is kept, and only you can see it.'
            : submitted
              ? 'Evaluation is closed, so your evaluation can’t be changed.'
              : 'Evaluation closed before you submitted, so your draft can’t be changed. Scores stay hidden from you.'}
        </p>
      )}
      {rubric.map((criterion, index) => (
        <CriterionField
          key={criterion.id}
          showHint={index === 0}
          criterion={criterion}
          entry={form.criteria[criterion.id] ?? { score: null, comment: '' }}
          onChange={(entry) =>
            update({ ...form, criteria: { ...form.criteria, [criterion.id]: entry } })
          }
          showWeight={weightsDiffer}
          missing={errors.criteria.includes(criterion.id)}
          readOnly={readOnly}
        />
      ))}
      <RecommendationField
        value={form.recommendation}
        onValueChange={(recommendation) => update({ ...form, recommendation })}
        comment={form.comment}
        onCommentChange={(comment) => update({ ...form, comment })}
        missing={errors.recommendation}
        readOnly={readOnly}
      />
    </SheetBody>
  )
}

function FormFooter({ rubric, session }: { rubric: RubricCriterion[]; session: Session }) {
  const { form, baseline, errors, submitted, submitting } = session
  if (!form) return null
  const scored = scoredCount(rubric, form)
  const unsavedEdit = submitted && baseline !== null && !sameForm(form, baseline)
  return (
    <>
      <p
        className={cn(
          'min-w-0 text-sm tabular-nums',
          hasErrors(errors) ? 'text-danger' : 'text-muted',
        )}
      >
        {hasErrors(errors) ? (
          <span className="inline-flex items-center gap-1.5">
            <CircleAlert aria-hidden="true" className="size-3.5 shrink-0" />
            {describeMissing(rubric, errors)}
          </span>
        ) : (
          <>
            {scored} of {rubric.length} scored
            {form.recommendation === null && scored === rubric.length
              ? ' · choose Go, Maybe or No'
              : ''}
          </>
        )}
      </p>
      <div className="flex shrink-0 items-center gap-2">
        {submitted && (
          <Button variant="ghost" onClick={session.cancelEdit} className="max-sm:h-11">
            Cancel
          </Button>
        )}
        <Button
          variant="primary"
          data-sheet-submit=""
          aria-keyshortcuts={ariaKeys(SHORTCUTS.submitForm.keys)}
          loading={submitting}
          disabled={submitted && !unsavedEdit}
          onClick={() => void session.submit()}
          className="max-sm:h-11 max-sm:px-6"
        >
          {submitted ? 'Save changes' : 'Submit'}
          <ButtonShortcut keys={SHORTCUTS.submitForm.keys} />
        </Button>
      </div>
    </>
  )
}

/**
 * "Saving draft…" / "Draft saved just now" / "Couldn't save — Retry". Only the
 * words are announced (politely), not the time ticking on.
 */
function SaveStatus({ state, onRetry }: { state: SaveState; onRetry: () => void }) {
  const now = useNow()
  return (
    <span className="inline-flex items-center gap-2">
      <span className={cn(state.kind === 'error' ? 'text-danger' : 'text-muted')}>
        <span role="status">
          {state.kind === 'saving'
            ? 'Saving draft…'
            : state.kind === 'saved'
              ? 'Draft saved'
              : state.kind === 'error'
                ? 'Couldn’t save your draft'
                : 'Your draft saves as you go'}
        </span>
        {state.kind === 'saved' && (
          <span aria-hidden="true">
            {' '}
            {new Date(state.at).getTime() > now - 45_000
              ? 'just now'
              : formatRelative(state.at, { now })}
          </span>
        )}
      </span>
      {state.kind === 'error' && (
        <Button variant="link" size="sm" onClick={onRetry}>
          Retry
        </Button>
      )}
    </span>
  )
}
