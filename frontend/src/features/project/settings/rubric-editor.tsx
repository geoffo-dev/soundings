import {
  closestCenter,
  DndContext,
  KeyboardSensor,
  MouseSensor,
  TouchSensor,
  useSensor,
  useSensors,
  type Announcements,
  type DragEndEvent,
} from '@dnd-kit/core'
import {
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import {
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  ChevronRight,
  CircleAlert,
  GripVertical,
  Info,
  Plus,
  Trash2,
} from 'lucide-react'
import { useState, type KeyboardEvent } from 'react'

import { describeError, isApiError } from '@/api/errors'
import { useReplaceRubric } from '@/api/projects'
import type { Project, RubricCriterion } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { toast } from '@/components/ui/toaster'
import { WithTooltip } from '@/components/ui/tooltip'
import { useShortcut } from '@/lib/shortcuts'
import { cn } from '@/lib/utils'

import {
  emptyCriterion,
  GUIDANCE_SCORES,
  hasErrors,
  isRubricDirty,
  keepRowKeys,
  LIMITS,
  MAX_CRITERIA,
  MIN_CRITERIA,
  moveItem,
  serverRubricErrors,
  weightShares,
  toDrafts,
  toRubricUpdate,
  validateRubric,
  type CriterionDraft,
  type CriterionField,
  type RubricErrors,
} from './rubric'
import { FormActions, SettingsSection } from './settings-layout'
import { focusNeighbour } from './sortable-rows'

/** The criteria as rows, keeping the React keys the form has (see keepRowKeys). */
function keepKeys(drafts: CriterionDraft[], criteria: RubricCriterion[]): CriterionDraft[] {
  return keepRowKeys(
    drafts,
    toDrafts(criteria),
    (draft) => draft.id,
    (row, before) => ({ ...row, key: before.key }),
  )
}

const GUIDANCE_PLACEHOLDER: Record<(typeof GUIDANCE_SCORES)[number], string> = {
  '1': 'What does a 1 look like?',
  '3': 'What does a 3 look like?',
  '5': 'What does a 5 look like?',
}

/**
 * Rubric editor (wireframe 07): 3–6 criteria with name, one-line description,
 * weight, inverted, and hover guidance for 1/3/5. Rows reorder by dragging
 * the handle, with Alt+↑/↓ or from the row's Move menu. Saving replaces the
 * whole rubric.
 */
export function RubricEditor({ project, active }: { project: Project; active: boolean }) {
  const replace = useReplaceRubric(project.slug)
  const [baseline, setBaseline] = useState<RubricCriterion[]>(project.rubric)
  const [drafts, setDrafts] = useState(() => toDrafts(project.rubric))
  // Errors show for fields you changed and then left (or everything after Save), so
  // tabbing through an untouched new row doesn't shout at you or shift the layout.
  const [changed, setChanged] = useState<ReadonlySet<string>>(new Set())
  const [touched, setTouched] = useState<ReadonlySet<string>>(new Set())
  const [submitted, setSubmitted] = useState(false)
  const [server, setServer] = useState<RubricErrors | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  // Someone else saved (or our save came back): follow the server unless we have edits.
  if (project.rubric !== baseline) {
    setBaseline(project.rubric)
    if (!isRubricDirty(drafts, baseline)) setDrafts(keepKeys(drafts, project.rubric))
  }

  const dirty = isRubricDirty(drafts, baseline)
  const local = validateRubric(drafts)
  const shown = (key: string, field: CriterionField) =>
    server?.rows[key]?.[field] ??
    (submitted || touched.has(`${key}:${field}`) ? local.rows[key]?.[field] : undefined)

  const update = (key: string, patch: Partial<CriterionDraft>) => {
    setNotice(null)
    setServer(null)
    setDrafts((current) => current.map((d) => (d.key === key ? { ...d, ...patch } : d)))
    const fields = Object.keys(patch).flatMap((field) =>
      field === 'guidance' ? GUIDANCE_SCORES.map((score) => `guidance.${score}`) : [field],
    )
    setChanged((current) => new Set([...current, ...fields.map((field) => `${key}:${field}`)]))
  }
  const touch = (key: string, field: CriterionField) => {
    if (changed.has(`${key}:${field}`)) {
      setTouched((current) => new Set(current).add(`${key}:${field}`))
    }
  }
  const move = (from: number, to: number) => setDrafts((current) => moveItem(current, from, to))

  const discard = () => {
    setDrafts(toDrafts(baseline))
    setChanged(new Set())
    setTouched(new Set())
    setSubmitted(false)
    setServer(null)
    setNotice(null)
  }

  const save = () => {
    if (replace.isPending) return
    if (!dirty) {
      setNotice('No changes to save.')
      return
    }
    setSubmitted(true)
    if (hasErrors(local)) {
      const first = drafts.find((d) => local.rows[d.key])
      if (first) document.getElementById(`criterion-${first.key}-name`)?.focus()
      return
    }
    const sent = drafts
    replace.mutate(toRubricUpdate(sent), {
      onSuccess: (rubric) => {
        setBaseline(rubric.criteria)
        // New rows keep their React keys: the field you saved from stays focused.
        setDrafts(keepKeys(sent, rubric.criteria))
        setChanged(new Set())
        setTouched(new Set())
        setSubmitted(false)
        toast.success('Rubric saved', {
          description: 'Scores are recalculated for every idea in this project.',
        })
      },
      onError: (error) => {
        const details = isApiError(error) ? (error.problem?.errors ?? []) : []
        if (details.length > 0) setServer(serverRubricErrors(drafts, details))
        else {
          const { title, description } = describeError(error)
          setServer({ rows: {}, form: description ? `${title}. ${description}` : title })
        }
      },
    })
  }

  useShortcut('saveSettings', save, { enabled: active })

  const sensors = useSensors(
    useSensor(MouseSensor, { activationConstraint: { distance: 4 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 200, tolerance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  )
  const nameOf = (id: string | number) => {
    const name = drafts.find((d) => d.key === id)?.name.trim() ?? ''
    return name.length > 0 ? name : 'Untitled criterion'
  }
  const positionOf = (id: string | number) => drafts.findIndex((d) => d.key === id) + 1
  const announcements: Announcements = {
    onDragStart: ({ active: item }) =>
      `Picked up ${nameOf(item.id)}, position ${positionOf(item.id)} of ${drafts.length}.`,
    onDragOver: ({ active: item, over }) =>
      over ? `${nameOf(item.id)} is over position ${positionOf(over.id)}.` : undefined,
    onDragEnd: ({ active: item, over }) =>
      over
        ? `${nameOf(item.id)} dropped at position ${positionOf(over.id)} of ${drafts.length}.`
        : `${nameOf(item.id)} dropped.`,
    onDragCancel: ({ active: item }) => `Reordering cancelled. ${nameOf(item.id)} is back.`,
  }
  const onDragEnd = ({ active: item, over }: DragEndEvent) => {
    if (!over || item.id === over.id) return
    move(positionOf(item.id) - 1, positionOf(over.id) - 1)
  }

  const formError = server?.form ?? (submitted ? local.form : undefined)
  const shares = weightShares(drafts)

  return (
    <SettingsSection
      title="Rubric"
      description="3 to 6 criteria, each scored 1–5. Weights are relative: 2 counts twice as much as 1. Inverted means a high score is bad, like Effort or Risk."
    >
      <form
        noValidate
        className="flex flex-col gap-4"
        onSubmit={(event) => {
          event.preventDefault()
          save()
        }}
      >
        {formError && (
          <p
            role="alert"
            className="flex items-start gap-2 rounded-md bg-danger-subtle px-3 py-2 text-sm text-danger"
          >
            <CircleAlert aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
            {formError}
          </p>
        )}

        <DndContext
          sensors={sensors}
          collisionDetection={closestCenter}
          onDragEnd={onDragEnd}
          accessibility={{
            announcements,
            screenReaderInstructions: {
              draggable:
                'To reorder, press Space, use the up and down arrow keys, then press Space again to drop, or Escape to cancel. You can also press Alt with the up or down arrow in any field of a criterion.',
            },
          }}
        >
          <SortableContext items={drafts.map((d) => d.key)} strategy={verticalListSortingStrategy}>
            <ol className="flex flex-col gap-3" aria-label="Criteria">
              {drafts.map((draft, index) => (
                <CriterionRow
                  key={draft.key}
                  draft={draft}
                  index={index}
                  count={drafts.length}
                  share={shares.get(draft.key) ?? null}
                  error={(field) => shown(draft.key, field)}
                  onChange={(patch) => update(draft.key, patch)}
                  onBlur={(field) => touch(draft.key, field)}
                  onMove={(to) => move(index, to)}
                  onRemove={() => {
                    const keys = drafts.map((d) => d.key)
                    setDrafts((current) => current.filter((d) => d.key !== draft.key))
                    setNotice(null)
                    focusNeighbour(keys, draft.key, (key) => `criterion-${key}-name`)
                  }}
                />
              ))}
            </ol>
          </SortableContext>
        </DndContext>

        <div className="flex flex-wrap items-center gap-3">
          <Button
            variant="outline"
            size="sm"
            disabled={drafts.length >= MAX_CRITERIA}
            onClick={() => {
              const added = emptyCriterion()
              setDrafts((current) => [...current, added])
              window.requestAnimationFrame(() =>
                document.getElementById(`criterion-${added.key}-name`)?.focus(),
              )
            }}
          >
            <Plus /> Add criterion
          </Button>
          {drafts.length >= MAX_CRITERIA && (
            <span className="text-sm text-muted">
              That’s the maximum: a short rubric keeps scoring quick.
            </span>
          )}
        </div>

        <div className="flex gap-3 rounded-lg border bg-subtle px-4 py-3 text-sm text-secondary">
          <Info aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-muted" />
          <div className="flex flex-col gap-1">
            <p className="font-medium text-primary">What happens to existing evaluations</p>
            <ul className="flex list-disc flex-col gap-0.5 pl-4">
              <li>Saving recalculates the score of every idea in this project.</li>
              <li>Renaming, rewording, reordering or re-weighting keeps every score.</li>
              <li>Removing a criterion takes its scores out of the aggregate.</li>
              <li>
                A new criterion starts unscored: submitted evaluations stay submitted, and
                evaluators score it the next time they edit.
              </li>
            </ul>
          </div>
        </div>

        <FormActions
          form="the rubric"
          dirty={dirty}
          saving={replace.isPending}
          notice={notice}
          onDiscard={discard}
          saveLabel="Save rubric"
        />
      </form>
    </SettingsSection>
  )
}

function CriterionRow({
  draft,
  index,
  count,
  share,
  error,
  onChange,
  onBlur,
  onMove,
  onRemove,
}: {
  draft: CriterionDraft
  index: number
  count: number
  /** This criterion's share of the aggregate, e.g. 25 (%), or null while a weight is invalid. */
  share: number | null
  error: (field: CriterionField) => string | undefined
  onChange: (patch: Partial<CriterionDraft>) => void
  onBlur: (field: CriterionField) => void
  onMove: (to: number) => void
  onRemove: () => void
}) {
  const {
    attributes,
    listeners,
    setNodeRef,
    setActivatorNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: draft.key })
  const hints = GUIDANCE_SCORES.filter((score) => draft.guidance[score]?.trim()).length
  const [guidanceOpen, setGuidanceOpen] = useState(false)
  const label = draft.name.trim() || `Criterion ${index + 1}`
  const idBase = `criterion-${draft.key}`

  // Alt+↑/↓ from any field of the row moves it (wireframe 07).
  const moveKeys = {
    onKeyDown: (event: KeyboardEvent) => {
      if (!event.altKey || (event.key !== 'ArrowUp' && event.key !== 'ArrowDown')) return
      event.preventDefault()
      onMove(index + (event.key === 'ArrowUp' ? -1 : 1))
    },
  }

  // Next to the name on phones, at the end of the controls on wider screens: Move (a
  // menu, so reordering never needs a drag or a key combination; WCAG 2.5.7) and Remove.
  const remove = (className: string) => (
    <div className={cn('flex items-center gap-0.5', className)}>
      <DropdownMenu>
        <WithTooltip content={`Move ${label}`}>
          <DropdownMenuTrigger asChild>
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label={`Move ${label}`}
              disabled={count < 2}
              {...moveKeys}
            >
              <ArrowUpDown />
            </Button>
          </DropdownMenuTrigger>
        </WithTooltip>
        <DropdownMenuContent align="end">
          <DropdownMenuItem disabled={index === 0} onSelect={() => onMove(index - 1)}>
            <ArrowUp /> Move up
          </DropdownMenuItem>
          <DropdownMenuItem disabled={index === count - 1} onSelect={() => onMove(index + 1)}>
            <ArrowDown /> Move down
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      <WithTooltip
        content={
          count <= MIN_CRITERIA
            ? `A rubric needs at least ${MIN_CRITERIA} criteria`
            : `Remove ${label}`
        }
      >
        <span>
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label={`Remove ${label}`}
            disabled={count <= MIN_CRITERIA}
            onClick={onRemove}
            {...moveKeys}
          >
            <Trash2 />
          </Button>
        </span>
      </WithTooltip>
    </div>
  )

  return (
    <li
      ref={setNodeRef}
      style={{ transform: CSS.Translate.toString(transform), transition }}
      aria-label={label}
      className={cn(
        'relative flex gap-2 rounded-lg border bg-surface p-3 pl-1.5',
        isDragging && 'z-10 border-strong shadow-raised',
      )}
    >
      <button
        type="button"
        ref={setActivatorNodeRef}
        {...attributes}
        {...listeners}
        aria-label={`Reorder ${label}`}
        className="flex h-8 w-6 shrink-0 cursor-grab touch-none items-center justify-center rounded-md text-muted transition-colors hover:bg-subtle hover:text-primary active:cursor-grabbing"
      >
        <GripVertical aria-hidden="true" className="size-4" />
      </button>

      <div className="flex min-w-0 flex-1 flex-col gap-3">
        <div className="grid gap-3 sm:grid-cols-[minmax(0,12rem)_minmax(0,1fr)]">
          <div className="flex min-w-0 items-start gap-1">
            <Field
              label="Name"
              hideLabel
              error={error('name')}
              id={`${idBase}-name`}
              className="min-w-0 flex-1"
            >
              <Input
                value={draft.name}
                maxLength={LIMITS.name + 10}
                placeholder="Name, e.g. Value"
                autoComplete="off"
                className="font-medium"
                onChange={(event) => onChange({ name: event.target.value })}
                onBlur={() => onBlur('name')}
                {...moveKeys}
              />
            </Field>
            {remove('pt-1 sm:hidden')}
          </div>
          <Field
            label="Description"
            hideLabel
            error={error('description')}
            id={`${idBase}-description`}
          >
            <Input
              value={draft.description}
              maxLength={LIMITS.description + 10}
              placeholder="One line: what evaluators should consider"
              autoComplete="off"
              onChange={(event) => onChange({ description: event.target.value })}
              onBlur={() => onBlur('description')}
              {...moveKeys}
            />
          </Field>
        </div>

        <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
          <div className="flex items-center gap-2">
            <label htmlFor={`${idBase}-weight`} className="text-sm text-secondary">
              Weight
            </label>
            <Input
              id={`${idBase}-weight`}
              value={draft.weight}
              inputMode="decimal"
              autoComplete="off"
              aria-invalid={error('weight') ? true : undefined}
              aria-describedby={error('weight') ? `${idBase}-weight-error` : undefined}
              className="w-16 text-right tabular-nums"
              onChange={(event) => onChange({ weight: event.target.value })}
              onBlur={() => onBlur('weight')}
              {...moveKeys}
            />
            {share !== null && (
              <span className="text-xs text-muted tabular-nums">{share}% of the score</span>
            )}
          </div>
          <div className="flex items-center gap-2">
            <Switch
              id={`${idBase}-inverted`}
              checked={draft.inverted}
              onCheckedChange={(inverted) => onChange({ inverted })}
              {...moveKeys}
            />
            <label htmlFor={`${idBase}-inverted`} className="text-sm text-secondary">
              Inverted
            </label>
          </div>
          <Button
            variant="ghost"
            size="sm"
            className="-ml-2 text-secondary"
            aria-expanded={guidanceOpen}
            aria-controls={`${idBase}-guidance`}
            onClick={() => setGuidanceOpen((open) => !open)}
            {...moveKeys}
          >
            <ChevronRight
              aria-hidden="true"
              className={cn('transition-transform duration-150', guidanceOpen && 'rotate-90')}
            />
            Guidance
            {hints > 0 && !guidanceOpen && (
              <span className="font-normal text-muted">
                · {hints} {hints === 1 ? 'hint' : 'hints'}
              </span>
            )}
          </Button>
          {remove('ml-auto max-sm:hidden')}
        </div>
        {error('weight') && (
          <p id={`${idBase}-weight-error`} className="-mt-1 text-sm text-danger">
            {error('weight')}
          </p>
        )}

        {guidanceOpen && (
          <div id={`${idBase}-guidance`} className="grid gap-2 border-t border-subtle pt-3">
            <p className="text-sm text-muted">
              Shown to evaluators when they hover or tap a score.
            </p>
            {GUIDANCE_SCORES.map((score) => (
              <div key={score} className="grid grid-cols-[1.5rem_minmax(0,1fr)] items-start gap-2">
                <label
                  htmlFor={`${idBase}-guidance-${score}`}
                  className="flex h-8 items-center justify-center rounded-md bg-subtle text-sm font-semibold text-secondary tabular-nums"
                >
                  <span className="sr-only">Guidance for a score of </span>
                  {score}
                </label>
                <Field error={error(`guidance.${score}`)} id={`${idBase}-guidance-${score}`}>
                  <Input
                    value={draft.guidance[score] ?? ''}
                    maxLength={LIMITS.guidance + 10}
                    placeholder={GUIDANCE_PLACEHOLDER[score]}
                    autoComplete="off"
                    onChange={(event) =>
                      onChange({ guidance: { ...draft.guidance, [score]: event.target.value } })
                    }
                    onBlur={() => onBlur(`guidance.${score}`)}
                    {...moveKeys}
                  />
                </Field>
              </div>
            ))}
          </div>
        )}
      </div>
    </li>
  )
}

/** What non-admins see: the rubric evaluators score against. */
export function RubricSummary({ project }: { project: Project }) {
  const total = project.rubric.reduce((sum, criterion) => sum + criterion.weight, 0)
  return (
    <SettingsSection title="Rubric" description="Every idea is scored 1–5 on these criteria.">
      <ol className="flex max-w-3xl flex-col divide-y divide-subtle rounded-lg border">
        {[...project.rubric]
          .sort((a, b) => a.position - b.position)
          .map((criterion) => (
            <li key={criterion.id} className="flex items-start gap-4 px-4 py-3">
              <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                <span className="flex items-center gap-2 text-sm font-medium text-primary">
                  {criterion.name}
                  {criterion.inverted && (
                    <Badge variant="outline" title="A high score is bad">
                      Inverted
                    </Badge>
                  )}
                </span>
                {criterion.description && (
                  <span className="text-sm text-muted">{criterion.description}</span>
                )}
              </div>
              <span className="shrink-0 text-sm text-secondary tabular-nums">
                {Math.round((criterion.weight / total) * 100)}%
                <span className="sr-only"> of the score</span>
              </span>
            </li>
          ))}
      </ol>
    </SettingsSection>
  )
}
