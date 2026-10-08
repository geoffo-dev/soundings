import { Link } from '@tanstack/react-router'
import { ArrowRight, CircleAlert, Info, Plus, RotateCcw } from 'lucide-react'
import { useId, useRef, useState } from 'react'

import { describeError, hasErrorCode, isApiError } from '@/api/errors'
import { useReplaceResearchSettings, useResearchSettings } from '@/api/research'
import type { IdeasInResearchProblem, Project, ResearchSettings, ResearchStep } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Callout } from '@/components/ui/callout'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { Skeleton, SkeletonGroup } from '@/components/ui/skeleton'
import { StatusBadge } from '@/components/ui/status-badge'
import { Switch } from '@/components/ui/switch'
import { toast } from '@/components/ui/toaster'
import { STEP_EXPLANATIONS } from '@/features/research/research-copy'
import { formatShortDate } from '@/lib/dates'
import { useShortcut } from '@/lib/shortcuts'
import { lifecycle, RESEARCH_STEP_LABELS } from '@/lib/status'

import { LoadError } from './proposal-template-editor'
import {
  defaultItemDrafts,
  emptyItem,
  hasChecklistErrors,
  isResearchDirty,
  ITEM_LIMITS,
  MAX_ITEMS,
  MIN_ITEMS,
  moveChecklistItem,
  removedItemNote,
  restoredItem,
  serverChecklistErrors,
  toItemDrafts,
  toResearchUpdate,
  validateChecklist,
  type ChecklistErrors,
  type ItemDraft,
  type ItemField,
} from './research-settings'
import { FormActions, SettingsSection } from './settings-layout'
import { moveKeysFor, RowControls, SortableRow, SortableRows } from './sortable-rows'

const STEPS: ResearchStep[] = ['off', 'before_evaluation', 'before_proposal']
const DESCRIPTION =
  'Before the team invests in an idea, its owner checks it isn’t already being done somewhere else and that the right departments or teams were consulted.'

/**
 * Project settings → Research (contract-phase8 §3.13): where the optional Research
 * stage goes (Off / Before evaluation / Before proposal) and its checklist, edited
 * like the rubric. Turning the step on with no checklist fills in the default three.
 * The step can't change while ideas are in Research (the 409 says how many).
 */
export function ResearchSettingsEditor({ project, active }: { project: Project; active: boolean }) {
  const settings = useResearchSettings(project.slug)
  if (settings.isPending) return <ResearchSkeleton />
  if (settings.isError) {
    return <LoadError what="the research settings" onRetry={() => void settings.refetch()} />
  }
  return <ResearchForm project={project} settings={settings.data} active={active} />
}

function ResearchForm({
  project,
  settings,
  active,
}: {
  project: Project
  settings: ResearchSettings
  active: boolean
}) {
  const replace = useReplaceResearchSettings(project.slug)
  const [baseline, setBaseline] = useState(settings)
  const [step, setStep] = useState<ResearchStep>(settings.step)
  const [drafts, setDrafts] = useState(() => toItemDrafts(settings.items))
  const [filledDefaults, setFilledDefaults] = useState(false)
  const [submitted, setSubmitted] = useState(false)
  const [touched, setTouched] = useState<ReadonlySet<string>>(new Set())
  // Errors show for fields you changed and then left (or everything after Save): leaving
  // a new, still empty row alone (say, to press "Add" again) shows nothing yet.
  const changed = useRef(new Set<string>())
  const touch = (field: string) => {
    if (changed.current.has(field)) setTouched((current) => new Set(current).add(field))
  }
  const [server, setServer] = useState<ChecklistErrors | null>(null)
  const [blocked, setBlocked] = useState<number | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const stepLabelId = useId()

  // Saved elsewhere (another admin, our own save): follow the server unless we have edits.
  if (settings !== baseline) {
    if (!isResearchDirty(step, drafts, baseline)) {
      setStep(settings.step)
      setDrafts(toItemDrafts(settings.items))
      setFilledDefaults(false)
    }
    setBaseline(settings)
  }

  const dirty = isResearchDirty(step, drafts, settings)
  const local = validateChecklist(step, drafts)
  const shown = (key: string, field: ItemField) =>
    server?.rows[key]?.[field] ??
    (submitted || touched.has(`${key}:${field}`) ? local.rows[key]?.[field] : undefined)
  const inResearch = settings.ideas_in_research
  const locked = inResearch > 0
  const inForm = new Set(drafts.flatMap((draft) => (draft.id ? [draft.id] : [])))
  const removed = settings.removed_items.filter((item) => !inForm.has(item.id))

  const chooseStep = (next: ResearchStep) => {
    setStep(next)
    setNotice(null)
    setServer(null)
    setBlocked(null)
    // Turned on with no checklist yet: start from the default three (saved only on Save).
    if (next !== 'off' && drafts.length === 0) {
      setDrafts(defaultItemDrafts(settings.default_items))
      setFilledDefaults(true)
    }
  }
  const update = (key: string, patch: Partial<ItemDraft>) => {
    setNotice(null)
    setServer(null)
    for (const field of Object.keys(patch)) changed.current.add(`${key}:${field}`)
    setDrafts((current) => current.map((d) => (d.key === key ? { ...d, ...patch } : d)))
  }
  const move = (from: number, to: number) =>
    setDrafts((current) => moveChecklistItem(current, from, to))
  const focusTitle = (key: string) =>
    window.requestAnimationFrame(() => document.getElementById(`item-${key}-title`)?.focus())

  const discard = () => {
    setStep(settings.step)
    setDrafts(toItemDrafts(settings.items))
    setFilledDefaults(false)
    setSubmitted(false)
    setTouched(new Set())
    changed.current.clear()
    setServer(null)
    setBlocked(null)
    setNotice(null)
  }

  const save = () => {
    if (replace.isPending) return
    if (!dirty) {
      setNotice('No changes to save.')
      return
    }
    setSubmitted(true)
    if (hasChecklistErrors(local)) {
      const first = drafts.find((d) => local.rows[d.key])
      if (first) document.getElementById(`item-${first.key}-title`)?.focus()
      return
    }
    replace.mutate(toResearchUpdate(step, drafts), {
      onSuccess: (next) => {
        setStep(next.step)
        setDrafts(toItemDrafts(next.items))
        setFilledDefaults(false)
        setSubmitted(false)
        setTouched(new Set())
        changed.current.clear()
        toast.success(
          next.step === 'off'
            ? 'Research step turned off'
            : `Research step saved: ${RESEARCH_STEP_LABELS[next.step].toLowerCase()}`,
          {
            description:
              next.step === 'off'
                ? 'The checklist and every answer are kept, hidden.'
                : 'The board shows a Research column now.',
          },
        )
      },
      onError: (error) => {
        if (hasErrorCode(error, 'ideas_in_research')) {
          const count = (error.problem as IdeasInResearchProblem | undefined)?.idea_count
          setBlocked(count ?? inResearch)
          return
        }
        const details = isApiError(error) ? (error.problem?.errors ?? []) : []
        if (details.length > 0) setServer(serverChecklistErrors(drafts, details))
        else {
          const { title, description } = describeError(error)
          setServer({ rows: {}, form: description ? `${title}. ${description}` : title })
        }
      },
    })
  }

  useShortcut('saveSettings', save, { enabled: active })

  const formError = server?.form ?? (submitted ? local.form : undefined)
  const nameOf = (draft: ItemDraft) => draft.title.trim() || 'Untitled item'
  const researchLink = (
    <Link
      to="/p/$slug"
      params={{ slug: project.slug }}
      search={{ view: 'list', status: ['research'] }}
      className="inline-flex items-center gap-1 font-medium text-accent underline-offset-4 hover:underline"
    >
      Show them <ArrowRight aria-hidden="true" className="size-3.5" />
    </Link>
  )
  const lockedCount = blocked ?? inResearch

  return (
    <SettingsSection title="Research step" description={DESCRIPTION}>
      <form
        noValidate
        className="flex flex-col gap-6"
        onSubmit={(event) => {
          event.preventDefault()
          save()
        }}
      >
        {(locked || blocked !== null) && (
          <Callout
            tone="warning"
            role={blocked !== null ? 'alert' : 'status'}
            title={`Move the ${lockedCount} ${lockedCount === 1 ? 'idea' : 'ideas'} in Research to another status first`}
            action={researchLink}
          >
            The research step can’t be moved or turned off while ideas are in Research. The
            checklist can still be changed.
          </Callout>
        )}
        <div className="flex max-w-3xl flex-col gap-2">
          <h3 id={stepLabelId} className="text-sm font-medium text-primary">
            Where Research goes
          </h3>
          <RadioGroup
            aria-labelledby={stepLabelId}
            value={step}
            disabled={locked}
            onValueChange={(value) => chooseStep(value as ResearchStep)}
          >
            {STEPS.map((option) => (
              <label
                key={option}
                htmlFor={`research-step-${option}`}
                className="flex cursor-pointer items-start gap-3 rounded-lg border px-3 py-2.5 transition-colors hover:bg-subtle has-[:disabled]:cursor-not-allowed has-[:disabled]:opacity-70 has-[[data-state=checked]]:border-accent-control"
              >
                <RadioGroupItem
                  id={`research-step-${option}`}
                  value={option}
                  className="mt-0.5"
                  aria-labelledby={`research-step-${option}-label`}
                  aria-describedby={`research-step-${option}-detail`}
                />
                <span className="flex min-w-0 flex-col gap-1">
                  <span
                    id={`research-step-${option}-label`}
                    className="text-sm font-medium text-primary"
                  >
                    {RESEARCH_STEP_LABELS[option]}
                  </span>
                  <span id={`research-step-${option}-detail`} className="text-sm text-muted">
                    {STEP_EXPLANATIONS[option]}
                  </span>
                  <LifecyclePreview project={project} step={option} />
                </span>
              </label>
            ))}
          </RadioGroup>
        </div>

        {step !== 'off' && (
          <div className="flex flex-col gap-4">
            <div className="flex max-w-3xl flex-col gap-1">
              <h3 className="text-sm font-medium text-primary">Checklist</h3>
              <p className="text-sm text-muted">
                1 to 10 items the owner answers in a few lines. Required items must be answered
                before an idea moves past Research; project admins can move it anyway.
              </p>
            </div>
            {filledDefaults && (
              <Callout tone="info" role="status" title="We filled in the default checklist">
                Change it as you like; nothing is saved until you press Save.
              </Callout>
            )}
            {formError && (
              <p
                role="alert"
                className="flex items-start gap-2 rounded-md bg-danger-subtle px-3 py-2 text-sm text-danger"
              >
                <CircleAlert aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
                {formError}
              </p>
            )}
            <SortableRows
              items={drafts}
              idOf={(draft) => draft.key}
              nameOf={nameOf}
              label="Checklist items"
              onMove={move}
            >
              {(draft, index) => {
                const label = draft.title.trim() || `Item ${index + 1}`
                const keys = moveKeysFor(index, (to) => move(index, to))
                const controls = (className: string) => (
                  <RowControls
                    label={label}
                    index={index}
                    count={drafts.length}
                    onMove={(to) => move(index, to)}
                    onRemove={() => {
                      setNotice(null)
                      setDrafts((current) => current.filter((d) => d.key !== draft.key))
                    }}
                    removeDisabledReason={
                      drafts.length <= MIN_ITEMS
                        ? 'The checklist needs at least one item'
                        : undefined
                    }
                    className={className}
                  />
                )
                return (
                  <SortableRow key={draft.key} id={draft.key} label={label}>
                    <div className="grid gap-3 sm:grid-cols-[minmax(0,16rem)_minmax(0,1fr)] sm:items-start">
                      <div className="flex min-w-0 items-start gap-1">
                        <Field
                          label="Title"
                          hideLabel
                          error={shown(draft.key, 'title')}
                          id={`item-${draft.key}-title`}
                          className="min-w-0 flex-1"
                        >
                          <Input
                            value={draft.title}
                            maxLength={ITEM_LIMITS.title + 10}
                            placeholder="What to check, e.g. Legal consulted"
                            autoComplete="off"
                            className="font-medium"
                            onChange={(event) => update(draft.key, { title: event.target.value })}
                            onBlur={() => touch(`${draft.key}:title`)}
                            {...keys}
                          />
                        </Field>
                        {controls('pt-1 sm:hidden')}
                      </div>
                      <Field
                        label="Hint"
                        hideLabel
                        error={shown(draft.key, 'hint')}
                        id={`item-${draft.key}-hint`}
                      >
                        <Input
                          value={draft.hint}
                          maxLength={ITEM_LIMITS.hint + 10}
                          placeholder="One line: what to write"
                          autoComplete="off"
                          onChange={(event) => update(draft.key, { hint: event.target.value })}
                          onBlur={() => touch(`${draft.key}:hint`)}
                          {...keys}
                        />
                      </Field>
                    </div>
                    <div className="flex items-center gap-2">
                      <Switch
                        id={`item-${draft.key}-required`}
                        checked={draft.required}
                        onCheckedChange={(required) => update(draft.key, { required })}
                        {...keys}
                      />
                      <label
                        htmlFor={`item-${draft.key}-required`}
                        className="text-sm text-secondary"
                      >
                        Required
                      </label>
                      {controls('ml-auto max-sm:hidden')}
                    </div>
                  </SortableRow>
                )
              }}
            </SortableRows>
            <div className="flex flex-wrap items-center gap-3">
              <Button
                variant="outline"
                size="sm"
                disabled={drafts.length >= MAX_ITEMS}
                onClick={() => {
                  const added = emptyItem()
                  setDrafts((current) => [...current, added])
                  focusTitle(added.key)
                }}
              >
                <Plus /> Add item
              </Button>
              {drafts.length >= MAX_ITEMS && (
                <span className="text-sm text-muted">
                  That’s the maximum: a short checklist gets answered.
                </span>
              )}
            </div>
            {removed.length > 0 && (
              <div className="flex flex-col gap-2">
                <h3 className="text-sm font-medium text-primary">Removed items</h3>
                <p className="text-sm text-muted">
                  Their answers are kept, hidden. Restore an item to bring them back.
                </p>
                <ul className="divide-y divide-subtle rounded-lg border">
                  {removed.map((item) => (
                    <li
                      key={item.id}
                      className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-2.5"
                    >
                      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                        <span className="flex items-center gap-2 text-sm font-medium text-primary">
                          <span className="truncate">{item.title}</span>
                          {item.required && <Badge variant="outline">Required</Badge>}
                        </span>
                        <span className="text-xs text-muted">
                          {removedItemNote(item)} · removed {formatShortDate(item.removed_at)}
                        </span>
                      </div>
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={drafts.length >= MAX_ITEMS}
                        aria-label={`Restore ${item.title}`}
                        onClick={() => {
                          const restored = restoredItem(item)
                          setDrafts((current) => [...current, restored])
                          setNotice(null)
                          focusTitle(restored.key)
                        }}
                      >
                        <RotateCcw /> Restore
                      </Button>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}

        <div className="flex max-w-3xl gap-3 rounded-lg border bg-subtle px-4 py-3 text-sm text-secondary">
          <Info aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-muted" />
          <div className="flex flex-col gap-1">
            <p className="font-medium text-primary">What happens to existing ideas</p>
            <ul className="flex list-disc flex-col gap-0.5 pl-4">
              <li>
                Turning the step on moves no idea: ideas already past Research stay where they are.
              </li>
              <li>
                Changing the checklist moves no idea either; the next move past Research checks the
                required items.
              </li>
              <li>
                Turning the step off hides the Research column, the checklist and every answer; turn
                it on again to bring them back.
              </li>
            </ul>
          </div>
        </div>

        <FormActions
          form="the research step"
          dirty={dirty}
          saving={replace.isPending}
          notice={notice}
          onDiscard={discard}
          saveLabel="Save research step"
        />
      </form>
    </SettingsSection>
  )
}

/** The stages with this step, as small status chips ("New → Research → Evaluating …"). */
function LifecyclePreview({ project, step }: { project: Project; step: ResearchStep }) {
  const statuses = lifecycle(step)
  return (
    <span
      aria-hidden="true"
      className="flex flex-wrap items-center gap-x-1.5 gap-y-1 pt-0.5 text-xs text-muted"
    >
      {statuses.map((status, index) => (
        // Each stage keeps the arrow after it, so a wrapped line never starts with "→".
        <span key={status} className="inline-flex items-center gap-x-1.5">
          <StatusBadge
            variant="plain"
            status={status}
            label={project.status_labels[status]}
            className={
              status === 'research'
                ? 'h-5 text-xs text-primary'
                : 'h-5 text-xs font-normal text-muted'
            }
          />
          {index < statuses.length - 1 && <span>→</span>}
        </span>
      ))}
    </span>
  )
}

/** What members and viewers see: the step and the checklist. */
export function ResearchSettingsSummary({ project }: { project: Project }) {
  const settings = useResearchSettings(project.slug)
  return (
    <SettingsSection
      title="Research step"
      description="Only project admins can change the research step and its checklist."
    >
      {settings.isPending ? (
        <ResearchSkeleton />
      ) : settings.isError ? (
        <LoadError what="the research settings" onRetry={() => void settings.refetch()} />
      ) : (
        <div className="flex max-w-3xl flex-col gap-4">
          <p className="text-sm text-secondary">
            <span className="font-medium text-primary">
              {RESEARCH_STEP_LABELS[settings.data.step]}.
            </span>{' '}
            {STEP_EXPLANATIONS[settings.data.step]}
          </p>
          {settings.data.step !== 'off' && (
            <ol className="flex flex-col divide-y divide-subtle rounded-lg border">
              {settings.data.items.map((item) => (
                <li key={item.id} className="flex items-start gap-3 px-4 py-3">
                  <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                    <span className="text-sm font-medium text-primary">{item.title}</span>
                    {item.hint && <span className="text-sm text-muted">{item.hint}</span>}
                  </div>
                  {item.required ? (
                    <Badge variant="outline">Required</Badge>
                  ) : (
                    <span className="text-xs text-muted">Optional</span>
                  )}
                </li>
              ))}
            </ol>
          )}
        </div>
      )}
    </SettingsSection>
  )
}

function ResearchSkeleton() {
  return (
    <SkeletonGroup label="Loading the research settings" className="flex max-w-3xl flex-col gap-3">
      {[0, 1, 2].map((i) => (
        <Skeleton key={i} className="h-16 w-full rounded-lg" />
      ))}
    </SkeletonGroup>
  )
}
