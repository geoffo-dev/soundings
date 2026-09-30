import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useLayoutEffect, useRef, useState } from 'react'

import { describeError, hasErrorCode } from '@/api/errors'
import { useSaveMyEvaluation } from '@/api/evaluations'
import { patchIdeaDetail } from '@/api/cache'
import { queryKeys } from '@/api/keys'
import type { MyEvaluation, RubricCriterion } from '@/api/types'
import { toast } from '@/components/ui/toaster'

import {
  describeMissing,
  formFromEvaluation,
  formToBody,
  hasErrors,
  incompleteErrors,
  missingForSubmit,
  NO_ERRORS,
  remainingErrors,
  sameForm,
  type EvaluationForm,
  type FormErrors,
} from './evaluation-form'

/** Debounce for draft autosave. */
export const AUTOSAVE_MS = 800

export type SaveState =
  { kind: 'idle' } | { kind: 'saving' } | { kind: 'saved'; at: string } | { kind: 'error' }

export interface EvaluationSession {
  /** Null until the rubric and your evaluation have loaded. */
  form: EvaluationForm | null
  /** What the server has (the reveal shows it). */
  baseline: EvaluationForm | null
  errors: FormErrors
  saveState: SaveState
  view: 'form' | 'reveal'
  /** The reveal follows a first submission: fade the others' scores in. */
  justSubmitted: boolean
  submitting: boolean
  submitted: boolean
  readOnly: boolean
  /** A save hit 409 `evaluation_closed`. */
  closedMeanwhile: boolean
  update: (next: EvaluationForm) => void
  submit: () => Promise<void>
  /** Save the draft now (closing the sheet, Retry). */
  flush: () => Promise<void>
  editAgain: () => void
  cancelEdit: () => void
}

/**
 * The evaluate sheet's state and saving rules, kept while the page is open so
 * closing the sheet never loses input:
 *
 * - drafts autosave (debounced, `submit: false`), one request at a time, and
 *   again on close or when the tab is hidden;
 * - Submit checks every criterion and the recommendation first (focus goes to
 *   the first gap), waits for a draft save in flight, then `submit: true`;
 * - a submitted evaluation is edited explicitly ("Save changes"), never
 *   autosaved (it would mark it edited on every keystroke);
 * - 409 `evaluation_closed` turns the form read-only with a note.
 */
export function useEvaluationSession({
  ideaKey,
  viewerId,
  rubric,
  mine,
  announce,
  focusFirstGap,
}: {
  ideaKey: string
  /** Your user id (to mark your own evaluator row as a draft). */
  viewerId: string
  rubric: RubricCriterion[] | undefined
  /** `undefined` while loading; `null` when you aren't an evaluator. */
  mine: MyEvaluation | null | undefined
  announce: (message: string) => void
  focusFirstGap: (errors: FormErrors) => void
}): EvaluationSession {
  const queryClient = useQueryClient()
  const { mutateAsync } = useSaveMyEvaluation(ideaKey)

  const [form, setForm] = useState<EvaluationForm | null>(null)
  const [baseline, setBaseline] = useState<EvaluationForm | null>(null)
  const [errors, setErrors] = useState<FormErrors>(NO_ERRORS)
  const [saveState, setSaveState] = useState<SaveState>({ kind: 'idle' })
  const [view, setView] = useState<'form' | 'reveal'>('form')
  const [justSubmitted, setJustSubmitted] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [closedMeanwhile, setClosedMeanwhile] = useState(false)

  // Start from what the server has, once it's known (adjusting state while
  // rendering, as React recommends, so the first paint already has the form).
  if (form === null && rubric && mine !== undefined) {
    const initial = formFromEvaluation(rubric, mine)
    setForm(initial)
    setBaseline(initial)
    if (mine?.state === 'submitted') setView('reveal')
    if (mine?.state === 'draft' && mine.updated_at) {
      setSaveState({ kind: 'saved', at: mine.updated_at })
    }
  }

  // The async save logic reads these; rendering reads the state above.
  const latest = useRef<EvaluationForm | null>(null)
  const saved = useRef<EvaluationForm | null>(null)
  const timer = useRef<number | undefined>(undefined)
  const inflight = useRef<Promise<unknown> | null>(null)
  const again = useRef(false)
  const hasDraft = useRef(mine?.state === 'draft')
  useLayoutEffect(() => {
    if (form && latest.current === null) {
      latest.current = form
      saved.current = form
    }
  }, [form])

  const submitted = mine?.state === 'submitted'
  const readOnly = !mine?.editable || closedMeanwhile
  const autosave = useRef(false)
  useLayoutEffect(() => {
    autosave.current = !submitted && !readOnly
  })

  const onClosedMeanwhile = () => {
    setClosedMeanwhile(true)
    void queryClient.invalidateQueries({ queryKey: queryKeys.ideas.detail(ideaKey) })
    void queryClient.invalidateQueries({ queryKey: queryKeys.evaluations.mine(ideaKey) })
  }

  const flush = async (): Promise<void> => {
    window.clearTimeout(timer.current)
    timer.current = undefined
    const current = latest.current
    if (!autosave.current || !rubric || !current || !saved.current) return
    if (sameForm(current, saved.current)) return
    if (inflight.current) {
      again.current = true
      return
    }
    setSaveState({ kind: 'saving' })
    const request = mutateAsync(formToBody(rubric, current, false))
    inflight.current = request
    try {
      const result = await request
      saved.current = current
      setBaseline(current)
      setSaveState({ kind: 'saved', at: result.updated_at ?? new Date().toISOString() })
      if (!hasDraft.current) {
        // First draft: your own row says "draft" and My work shows "Draft saved".
        hasDraft.current = true
        patchIdeaDetail(queryClient, ideaKey, (idea) => ({
          evaluators: idea.evaluators.map((evaluator) =>
            evaluator.user.id === viewerId && evaluator.state === 'invited'
              ? { ...evaluator, state: 'draft' as const }
              : evaluator,
          ),
        }))
        void queryClient.invalidateQueries({ queryKey: queryKeys.work.all })
      }
    } catch (error) {
      if (hasErrorCode(error, 'evaluation_closed')) onClosedMeanwhile()
      // Submitted in another tab: there is no draft to save any more.
      else if (!hasErrorCode(error, 'evaluation_already_submitted')) {
        setSaveState({ kind: 'error' })
      }
    } finally {
      inflight.current = null
      if (again.current) {
        again.current = false
        void flushRef.current()
      }
    }
  }
  const flushRef = useRef(flush)
  useLayoutEffect(() => {
    flushRef.current = flush
  })

  // Save when the tab is hidden, and when the page goes away.
  useEffect(() => {
    const onHide = () => {
      if (document.visibilityState === 'hidden') void flushRef.current()
    }
    document.addEventListener('visibilitychange', onHide)
    return () => {
      document.removeEventListener('visibilitychange', onHide)
      void flushRef.current()
    }
  }, [])

  const update = (next: EvaluationForm) => {
    if (!rubric) return
    latest.current = next
    setForm(next)
    if (hasErrors(errors)) setErrors(remainingErrors(errors, rubric, next))
    if (!autosave.current) return
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => void flushRef.current(), AUTOSAVE_MS)
  }

  const submit = async (): Promise<void> => {
    const current = latest.current
    if (!rubric || !current || readOnly || submitting) return
    window.clearTimeout(timer.current)
    const missing = missingForSubmit(rubric, current)
    if (hasErrors(missing)) {
      setErrors(missing)
      focusFirstGap(missing)
      announce(describeMissing(rubric, missing))
      // Not submittable yet, but what's there is still a draft worth keeping.
      void flushRef.current()
      return
    }
    setSubmitting(true)
    // Let a draft save that is already on its way land first.
    await inflight.current?.catch(() => undefined)
    try {
      await mutateAsync(formToBody(rubric, current, true))
      saved.current = current
      setBaseline(current)
      setErrors(NO_ERRORS)
      setSaveState({ kind: 'idle' })
      setJustSubmitted(!submitted)
      setView('reveal')
      announce(
        submitted
          ? 'Your changes are saved.'
          : 'Evaluation submitted. The other evaluators’ scores are now visible.',
      )
    } catch (error) {
      const gaps = incompleteErrors(error, rubric)
      if (gaps && hasErrors(gaps)) {
        setErrors(gaps)
        focusFirstGap(gaps)
        announce(describeMissing(rubric, gaps))
      } else if (hasErrorCode(error, 'evaluation_closed')) {
        onClosedMeanwhile()
      } else {
        const { title, description } = describeError(error)
        toast.error(submitted ? 'Couldn’t save your changes' : 'Couldn’t submit your evaluation', {
          description: description ? `${title}. ${description}` : title,
          action: { label: 'Retry', onClick: () => void submit() },
        })
      }
    } finally {
      setSubmitting(false)
    }
  }

  const editAgain = () => {
    setJustSubmitted(false)
    setView('form')
  }

  const cancelEdit = () => {
    const restored = saved.current
    if (restored) {
      latest.current = restored
      setForm(restored)
    }
    setErrors(NO_ERRORS)
    setView('reveal')
  }

  return {
    form,
    baseline,
    errors,
    saveState,
    view,
    justSubmitted,
    submitting,
    submitted,
    readOnly,
    closedMeanwhile,
    update,
    submit,
    flush,
    editAgain,
    cancelEdit,
  }
}
