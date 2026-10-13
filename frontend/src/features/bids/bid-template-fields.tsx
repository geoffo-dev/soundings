import { CircleCheck, Plus, TriangleAlert } from 'lucide-react'

import type { BidQuestionType, MustHaveKind } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import {
  focusNeighbour,
  moveKeysFor,
  RowControls,
  SortableRow,
  SortableRows,
} from '@/features/project/settings/sortable-rows'
import { cn } from '@/lib/utils'

import {
  emptyMustHave,
  emptyQuestion,
  emptySection,
  moveRow,
  MUST_HAVE_KIND_LABELS,
  priceQuestionCount,
  QUESTION_TYPE_HELP,
  QUESTION_TYPE_LABELS,
  TEMPLATE_LIMITS,
  weightTotal,
  type MustHaveDraft,
  type QuestionDraft,
  type SectionDraft,
  type TemplateDraft,
} from './bid-template'

export const fieldId = (rowId: string, field: string) => `bid-template-${rowId}-${field}`

/**
 * The bid evaluation template's fields (contract-phase10 §4): weighted sections of
 * questions, the must-haves and the 0-5 scale, reordered as the other settings editors
 * do (drag, Alt+↑/↓, Move menu). Controlled: the caller keeps the draft, validates and
 * saves (Project settings → Bids, or a call's own copy).
 */
export function BidTemplateFields({
  draft,
  onChange,
  error,
  onBlurField,
}: {
  draft: TemplateDraft
  onChange: (next: TemplateDraft) => void
  /** The message shown for a field (`<row id>:<field>`), or undefined. */
  error: (key: string) => string | undefined
  onBlurField?: (key: string) => void
}) {
  const total = weightTotal(draft)
  const prices = priceQuestionCount(draft)
  const setSections = (sections: SectionDraft[]) => onChange({ ...draft, sections })
  const updateSection = (id: string, patch: Partial<SectionDraft>) =>
    setSections(draft.sections.map((s) => (s.id === id ? { ...s, ...patch } : s)))
  const updateQuestion = (sectionId: string, questionId: string, patch: Partial<QuestionDraft>) =>
    setSections(
      draft.sections.map((s) =>
        s.id === sectionId
          ? {
              ...s,
              questions: s.questions.map((q) => (q.id === questionId ? { ...q, ...patch } : q)),
            }
          : s,
      ),
    )
  const setMustHaves = (mustHaves: MustHaveDraft[]) => onChange({ ...draft, mustHaves })
  const blur = (key: string) => () => onBlurField?.(key)
  const focus = (id: string) =>
    window.requestAnimationFrame(() => document.getElementById(id)?.focus())

  return (
    <div className="flex flex-col gap-8">
      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h3 className="text-lg font-semibold text-primary">Sections</h3>
          <p
            role="status"
            className={cn(
              'flex items-center gap-1.5 text-sm',
              total === 100 ? 'text-muted' : 'text-warning',
            )}
          >
            {total === 100 ? (
              <CircleCheck aria-hidden="true" className="size-4" />
            ) : (
              <TriangleAlert aria-hidden="true" className="size-4" />
            )}
            Section weights add up to {total}%{total === 100 ? '' : ': they need to make 100%'}
          </p>
        </div>
        <SortableRows
          items={draft.sections}
          idOf={(s) => s.id}
          nameOf={(s) => s.title.trim() || 'Untitled section'}
          label="Sections"
          onMove={(from, to) => setSections(moveRow(draft.sections, from, to))}
        >
          {(section, index) => {
            const label = section.title.trim() || `Section ${index + 1}`
            const keys = moveKeysFor(index, (to) => setSections(moveRow(draft.sections, index, to)))
            const controls = (className: string) => (
              <RowControls
                label={label}
                index={index}
                count={draft.sections.length}
                onMove={(to) => setSections(moveRow(draft.sections, index, to))}
                onRemove={() => {
                  const ids = draft.sections.map((s) => s.id)
                  setSections(draft.sections.filter((s) => s.id !== section.id))
                  focusNeighbour(ids, section.id, (id) => fieldId(id, 'title'))
                }}
                removeDisabledReason={
                  draft.sections.length <= 1 ? 'A template needs at least one section' : undefined
                }
                className={className}
              />
            )
            return (
              <SortableRow key={section.id} id={section.id} label={label}>
                <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_7rem_auto] sm:items-start">
                  <div className="flex min-w-0 items-start gap-1">
                    <Field
                      label="Section title"
                      hideLabel
                      error={error(`${section.id}:title`)}
                      id={fieldId(section.id, 'title')}
                      className="min-w-0 flex-1"
                    >
                      <Input
                        value={section.title}
                        maxLength={TEMPLATE_LIMITS.sectionTitle + 10}
                        placeholder="Title, e.g. Technical"
                        autoComplete="off"
                        className="font-medium"
                        onChange={(e) => updateSection(section.id, { title: e.target.value })}
                        onBlur={blur(`${section.id}:title`)}
                        {...keys}
                      />
                    </Field>
                    {controls('pt-1 sm:hidden')}
                  </div>
                  <Field
                    label={`Weight of ${label} (%)`}
                    hideLabel
                    error={error(`${section.id}:weight`)}
                    id={fieldId(section.id, 'weight')}
                  >
                    <div className="flex items-center gap-1.5">
                      <Input
                        value={section.weight}
                        inputMode="numeric"
                        placeholder="40"
                        autoComplete="off"
                        className="tabular-nums"
                        onChange={(e) => updateSection(section.id, { weight: e.target.value })}
                        onBlur={blur(`${section.id}:weight`)}
                        {...keys}
                      />
                      <span aria-hidden="true" className="text-sm text-muted">
                        %
                      </span>
                    </div>
                  </Field>
                  {controls('pt-1 max-sm:hidden')}
                </div>
                <Field
                  label={`Guidance for ${label}`}
                  hideLabel
                  error={error(`${section.id}:guidance`)}
                  id={fieldId(section.id, 'guidance')}
                >
                  <Textarea
                    minRows={1}
                    maxRows={4}
                    value={section.guidance}
                    maxLength={TEMPLATE_LIMITS.sectionGuidance + 10}
                    placeholder="What this section is about (shown to its assessors)"
                    onChange={(e) => updateSection(section.id, { guidance: e.target.value })}
                    onBlur={blur(`${section.id}:guidance`)}
                  />
                </Field>
                <QuestionList
                  section={section}
                  sectionLabel={label}
                  pricesElsewhere={
                    prices - section.questions.filter((q) => q.type === 'price').length
                  }
                  error={error}
                  blur={blur}
                  onChange={(questions) => updateSection(section.id, { questions })}
                  onUpdate={(qid, patch) => updateQuestion(section.id, qid, patch)}
                />
              </SortableRow>
            )
          }}
        </SortableRows>
        <div className="flex flex-wrap items-center gap-3">
          <Button
            variant="outline"
            size="sm"
            disabled={draft.sections.length >= TEMPLATE_LIMITS.sections}
            onClick={() => {
              const added = emptySection()
              setSections([...draft.sections, added])
              focus(fieldId(added.id, 'title'))
            }}
          >
            <Plus /> Add section
          </Button>
          {draft.sections.length >= TEMPLATE_LIMITS.sections && (
            <span className="text-sm text-muted">That’s the maximum of 8 sections.</span>
          )}
        </div>
      </div>

      <div className="flex flex-col gap-3">
        <div className="flex max-w-2xl flex-col gap-1">
          <h3 className="text-lg font-semibold text-primary">Must-haves</h3>
          <p className="text-sm text-muted">
            What every bid must include. A required document missing from a bid is flagged at once;
            confirmations are checked by a person (and pre-checked by the AI assessor). A pricing
            document is opened only by call managers and the assessors of the section with the
            price.
          </p>
        </div>
        {draft.mustHaves.length > 0 && (
          <SortableRows
            items={draft.mustHaves}
            idOf={(m) => m.id}
            nameOf={(m) => m.text.trim() || 'Untitled must-have'}
            label="Must-haves"
            onMove={(from, to) => setMustHaves(moveRow(draft.mustHaves, from, to))}
          >
            {(mustHave, index) => {
              const label = mustHave.text.trim() || `Must-have ${index + 1}`
              const keys = moveKeysFor(index, (to) =>
                setMustHaves(moveRow(draft.mustHaves, index, to)),
              )
              const update = (patch: Partial<MustHaveDraft>) =>
                setMustHaves(
                  draft.mustHaves.map((m) => (m.id === mustHave.id ? { ...m, ...patch } : m)),
                )
              return (
                <SortableRow key={mustHave.id} id={mustHave.id} label={label}>
                  <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_12rem_auto] sm:items-start">
                    <Field
                      label="Must-have"
                      hideLabel
                      error={error(`${mustHave.id}:text`)}
                      id={fieldId(mustHave.id, 'text')}
                    >
                      <Input
                        value={mustHave.text}
                        maxLength={TEMPLATE_LIMITS.mustHaveText + 10}
                        placeholder="e.g. Insurance certificate"
                        autoComplete="off"
                        onChange={(e) => update({ text: e.target.value })}
                        onBlur={blur(`${mustHave.id}:text`)}
                        {...keys}
                      />
                    </Field>
                    <Field label={`Kind of ${label}`} hideLabel id={fieldId(mustHave.id, 'kind')}>
                      <Select
                        value={mustHave.kind}
                        onValueChange={(kind) =>
                          update({
                            kind: kind as MustHaveKind,
                            pricing: kind === 'document' && mustHave.pricing,
                          })
                        }
                      >
                        <SelectTrigger>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {(Object.keys(MUST_HAVE_KIND_LABELS) as MustHaveKind[]).map((kind) => (
                            <SelectItem key={kind} value={kind}>
                              {MUST_HAVE_KIND_LABELS[kind]}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </Field>
                    <RowControls
                      label={label}
                      index={index}
                      count={draft.mustHaves.length}
                      onMove={(to) => setMustHaves(moveRow(draft.mustHaves, index, to))}
                      onRemove={() => {
                        const ids = draft.mustHaves.map((m) => m.id)
                        setMustHaves(draft.mustHaves.filter((m) => m.id !== mustHave.id))
                        focusNeighbour(ids, mustHave.id, (id) => fieldId(id, 'text'))
                      }}
                      className="pt-1"
                    />
                  </div>
                  {mustHave.kind === 'document' && (
                    <Field
                      inline
                      label="A pricing document"
                      description="Only call managers and the price section’s assessors open it; the AI never reads it."
                      id={fieldId(mustHave.id, 'pricing')}
                    >
                      <Checkbox
                        checked={mustHave.pricing}
                        onCheckedChange={(checked) => update({ pricing: checked === true })}
                      />
                    </Field>
                  )}
                </SortableRow>
              )
            }}
          </SortableRows>
        )}
        <div className="flex flex-wrap items-center gap-3">
          <Button
            variant="outline"
            size="sm"
            disabled={draft.mustHaves.length >= TEMPLATE_LIMITS.mustHaves}
            onClick={() => {
              const added = emptyMustHave()
              setMustHaves([...draft.mustHaves, added])
              focus(fieldId(added.id, 'text'))
            }}
          >
            <Plus /> Add must-have
          </Button>
          {draft.mustHaves.length === 0 && (
            <span className="text-sm text-muted">No must-haves: every bid qualifies.</span>
          )}
        </div>
      </div>

      <div className="flex flex-col gap-3">
        <div className="flex max-w-2xl flex-col gap-1">
          <h3 className="text-lg font-semibold text-primary">Scale</h3>
          <p className="text-sm text-muted">
            What each score from 0 to 5 means. Assessors see these words as they score.
          </p>
        </div>
        <ol className="grid max-w-3xl gap-2">
          {draft.scale.map((label, score) => (
            <li key={score} className="grid grid-cols-[2rem_minmax(0,1fr)] items-start gap-2">
              <span
                aria-hidden="true"
                className="pt-1.5 text-center text-base font-semibold text-primary tabular-nums"
              >
                {score}
              </span>
              <Field
                label={`What a ${score} means`}
                hideLabel
                error={error(`scale-${score}:label`)}
                id={fieldId(`scale-${score}`, 'label')}
              >
                <Input
                  value={label}
                  maxLength={TEMPLATE_LIMITS.scaleLabel + 10}
                  autoComplete="off"
                  onChange={(e) =>
                    onChange({
                      ...draft,
                      scale: draft.scale.map((value, i) => (i === score ? e.target.value : value)),
                    })
                  }
                  onBlur={blur(`scale-${score}:label`)}
                />
              </Field>
            </li>
          ))}
        </ol>
      </div>
    </div>
  )
}

function QuestionList({
  section,
  sectionLabel,
  pricesElsewhere,
  error,
  blur,
  onChange,
  onUpdate,
}: {
  section: SectionDraft
  sectionLabel: string
  /** Price questions in the other sections (a template takes one). */
  pricesElsewhere: number
  error: (key: string) => string | undefined
  blur: (key: string) => () => void
  onChange: (questions: QuestionDraft[]) => void
  onUpdate: (id: string, patch: Partial<QuestionDraft>) => void
}) {
  const questions = section.questions
  const sectionError = error(`${section.id}:questions`)
  return (
    <div className="flex flex-col gap-2 border-t border-subtle pt-3">
      <h4 className="text-sm font-medium text-secondary">Questions in {sectionLabel}</h4>
      {sectionError && (
        <p role="alert" className="text-sm text-danger">
          {sectionError}
        </p>
      )}
      <SortableRows
        items={questions}
        idOf={(q) => q.id}
        nameOf={(q) => q.text.trim() || 'Untitled question'}
        label={`Questions in ${sectionLabel}`}
        onMove={(from, to) => onChange(moveRow(questions, from, to))}
      >
        {(question, index) => {
          const label = question.text.trim() || `Question ${index + 1}`
          const keys = moveKeysFor(index, (to) => onChange(moveRow(questions, index, to)))
          const types: BidQuestionType[] =
            pricesElsewhere > 0 && question.type !== 'price'
              ? ['score', 'comment']
              : ['score', 'price', 'comment']
          return (
            <SortableRow key={question.id} id={question.id} label={label}>
              <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_9rem_5.5rem_auto] sm:items-start">
                <Field
                  label="Question"
                  hideLabel
                  error={error(`${question.id}:text`)}
                  id={fieldId(question.id, 'text')}
                >
                  <Input
                    value={question.text}
                    maxLength={TEMPLATE_LIMITS.questionText + 10}
                    placeholder="The question assessors answer"
                    autoComplete="off"
                    onChange={(e) => onUpdate(question.id, { text: e.target.value })}
                    onBlur={blur(`${question.id}:text`)}
                    {...keys}
                  />
                </Field>
                <Field label={`Type of ${label}`} hideLabel id={fieldId(question.id, 'type')}>
                  <Select
                    value={question.type}
                    onValueChange={(type) =>
                      onUpdate(question.id, {
                        type: type as BidQuestionType,
                        weight:
                          type === 'comment'
                            ? '0'
                            : question.weight === '0'
                              ? '1'
                              : question.weight,
                      })
                    }
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {types.map((type) => (
                        <SelectItem key={type} value={type}>
                          {QUESTION_TYPE_LABELS[type]}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </Field>
                {question.type === 'comment' ? (
                  <span className="pt-1.5 text-sm text-muted max-sm:hidden">Not scored</span>
                ) : (
                  <Field
                    label={`Weight of ${label} in the section`}
                    hideLabel
                    error={error(`${question.id}:weight`)}
                    id={fieldId(question.id, 'weight')}
                  >
                    <Input
                      value={question.weight}
                      inputMode="numeric"
                      autoComplete="off"
                      className="tabular-nums"
                      onChange={(e) => onUpdate(question.id, { weight: e.target.value })}
                      onBlur={blur(`${question.id}:weight`)}
                      {...keys}
                    />
                  </Field>
                )}
                <RowControls
                  label={label}
                  index={index}
                  count={questions.length}
                  onMove={(to) => onChange(moveRow(questions, index, to))}
                  onRemove={() => {
                    const ids = questions.map((q) => q.id)
                    onChange(questions.filter((q) => q.id !== question.id))
                    focusNeighbour(ids, question.id, (id) => fieldId(id, 'text'))
                  }}
                  removeDisabledReason={
                    questions.length <= 1 ? 'A section needs at least one question' : undefined
                  }
                  className="pt-1"
                />
              </div>
              <p className="text-xs text-muted">{QUESTION_TYPE_HELP[question.type]}</p>
              <Field
                label={`Guidance for ${label}`}
                hideLabel
                error={error(`${question.id}:guidance`)}
                id={fieldId(question.id, 'guidance')}
              >
                <Textarea
                  minRows={1}
                  maxRows={5}
                  value={question.guidance}
                  maxLength={TEMPLATE_LIMITS.questionGuidance + 10}
                  placeholder="What a good answer shows (shown to assessors)"
                  onChange={(e) => onUpdate(question.id, { guidance: e.target.value })}
                  onBlur={blur(`${question.id}:guidance`)}
                />
              </Field>
            </SortableRow>
          )
        }}
      </SortableRows>
      <div>
        <Button
          variant="ghost"
          size="sm"
          disabled={questions.length >= TEMPLATE_LIMITS.questions}
          onClick={() => {
            const added = emptyQuestion()
            onChange([...questions, added])
            window.requestAnimationFrame(() =>
              document.getElementById(fieldId(added.id, 'text'))?.focus(),
            )
          }}
        >
          <Plus /> Add question
        </Button>
      </div>
    </div>
  )
}

/** Read-only: the sections, their questions and the must-haves (members and viewers). */
export function BidTemplateSummary({ draft }: { draft: TemplateDraft }) {
  return (
    <div className="flex max-w-3xl flex-col gap-6">
      <ol className="flex flex-col divide-y divide-subtle rounded-lg border">
        {draft.sections.map((section) => (
          <li key={section.id} className="flex flex-col gap-2 px-4 py-3">
            <div className="flex items-baseline justify-between gap-3">
              <span className="text-sm font-medium text-primary">{section.title}</span>
              <span className="text-sm text-muted tabular-nums">{section.weight}%</span>
            </div>
            {section.guidance && <p className="text-sm text-muted">{section.guidance}</p>}
            <ul className="flex flex-col gap-1">
              {section.questions.map((q) => (
                <li key={q.id} className="flex items-baseline justify-between gap-3 text-sm">
                  <span className="text-secondary">{q.text}</span>
                  <span className="shrink-0 text-xs text-muted">
                    {QUESTION_TYPE_LABELS[q.type]}
                    {q.type !== 'comment' && ` · weight ${q.weight}`}
                  </span>
                </li>
              ))}
            </ul>
          </li>
        ))}
      </ol>
      {draft.mustHaves.length > 0 && (
        <div className="flex flex-col gap-2">
          <h3 className="text-sm font-medium text-primary">Must-haves</h3>
          <ul className="flex flex-col divide-y divide-subtle rounded-lg border">
            {draft.mustHaves.map((m) => (
              <li
                key={m.id}
                className="flex items-baseline justify-between gap-3 px-4 py-2.5 text-sm"
              >
                <span className="text-secondary">{m.text}</span>
                <span className="shrink-0 text-xs text-muted">
                  {MUST_HAVE_KIND_LABELS[m.kind]}
                  {m.pricing && ' · pricing'}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
