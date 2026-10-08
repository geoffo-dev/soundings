import { CircleAlert, CloudOff, Info, Plus, RotateCcw } from 'lucide-react'
import { useRef, useState } from 'react'

import { describeError, isApiError } from '@/api/errors'
import { useProposalTemplate, useReplaceProposalTemplate } from '@/api/research'
import type { Project, ProposalTemplate } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Skeleton, SkeletonGroup } from '@/components/ui/skeleton'
import { toast } from '@/components/ui/toaster'
import { ConfirmDialog } from '@/features/admin/confirm-dialog'
import { formatShortDate } from '@/lib/dates'
import { useShortcut } from '@/lib/shortcuts'

import {
  emptySection,
  hasTemplateErrors,
  isTemplateDirty,
  MAX_SECTIONS,
  MIN_SECTIONS,
  moveSection,
  removedSectionNote,
  restoredSection,
  SECTION_LIMITS,
  serverTemplateErrors,
  toSectionDrafts,
  toTemplateUpdate,
  validateTemplate,
  type SectionDraft,
  type SectionField,
  type TemplateErrors,
} from './proposal-template'
import { FormActions, SettingsSection } from './settings-layout'
import { moveKeysFor, RowControls, SortableRow, SortableRows } from './sortable-rows'

const TITLE = 'Proposal template'
const DESCRIPTION =
  'The sections every proposal in this project has, in order, each with a one-line hint shown in the editor. 1 to 12 sections.'

/**
 * Project settings → Proposal (contract-phase8 §2.7): the project's proposal
 * sections, edited like the rubric. Rename, reorder (drag, Alt+↑/↓ or Move), add
 * (up to 12) and remove (at least one stays); a removed section's text is kept and
 * comes back with **Restore** under "Removed sections". Saving replaces the template,
 * and every proposal follows it at once.
 */
export function ProposalTemplateEditor({ project, active }: { project: Project; active: boolean }) {
  const template = useProposalTemplate(project.slug)
  if (template.isPending) return <TemplateSkeleton />
  if (template.isError) {
    return <LoadError what="the proposal template" onRetry={() => void template.refetch()} />
  }
  return <TemplateForm slug={project.slug} template={template.data} active={active} />
}

function TemplateForm({
  slug,
  template,
  active,
}: {
  slug: string
  template: ProposalTemplate
  active: boolean
}) {
  const replace = useReplaceProposalTemplate(slug)
  const [baseline, setBaseline] = useState(template)
  const [drafts, setDrafts] = useState(() => toSectionDrafts(template.sections))
  const [submitted, setSubmitted] = useState(false)
  const [touched, setTouched] = useState<ReadonlySet<string>>(new Set())
  // Errors show for fields you changed and then left (or everything after Save): leaving
  // a new, still empty row alone (say, to press "Add" again) shows nothing yet.
  const changed = useRef(new Set<string>())
  const touch = (field: string) => {
    if (changed.current.has(field)) setTouched((current) => new Set(current).add(field))
  }
  const [server, setServer] = useState<TemplateErrors | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [confirmRemove, setConfirmRemove] = useState<SectionDraft | null>(null)

  // Saved elsewhere (another admin, our own save): follow the server unless we have edits.
  if (template !== baseline) {
    if (!isTemplateDirty(drafts, baseline)) setDrafts(toSectionDrafts(template.sections))
    setBaseline(template)
  }

  const dirty = isTemplateDirty(drafts, template)
  const local = validateTemplate(drafts)
  const shown = (id: string, field: SectionField) =>
    server?.rows[id]?.[field] ??
    (submitted || touched.has(`${id}:${field}`) ? local.rows[id]?.[field] : undefined)
  const inForm = new Set(drafts.flatMap((draft) => (draft.key ? [draft.key] : [])))
  const removed = template.removed_sections.filter((section) => !inForm.has(section.key))

  const update = (id: string, patch: Partial<SectionDraft>) => {
    setNotice(null)
    setServer(null)
    for (const field of Object.keys(patch)) changed.current.add(`${id}:${field}`)
    setDrafts((current) => current.map((d) => (d.id === id ? { ...d, ...patch } : d)))
  }
  const move = (from: number, to: number) => setDrafts((current) => moveSection(current, from, to))
  const remove = (draft: SectionDraft) => {
    setNotice(null)
    setDrafts((current) => current.filter((d) => d.id !== draft.id))
  }
  const focusTitle = (id: string) =>
    window.requestAnimationFrame(() => document.getElementById(`section-${id}-title`)?.focus())

  const discard = () => {
    setDrafts(toSectionDrafts(template.sections))
    setSubmitted(false)
    setTouched(new Set())
    changed.current.clear()
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
    if (hasTemplateErrors(local)) {
      const first = drafts.find((d) => local.rows[d.id])
      if (first) document.getElementById(`section-${first.id}-title`)?.focus()
      return
    }
    replace.mutate(toTemplateUpdate(drafts), {
      onSuccess: (next) => {
        setDrafts(toSectionDrafts(next.sections))
        setSubmitted(false)
        setTouched(new Set())
        changed.current.clear()
        toast.success('Proposal template saved', {
          description: 'Every proposal in this project follows it now.',
        })
      },
      onError: (error) => {
        const details = isApiError(error) ? (error.problem?.errors ?? []) : []
        if (details.length > 0) setServer(serverTemplateErrors(drafts, details))
        else {
          const { title, description } = describeError(error)
          setServer({ rows: {}, form: description ? `${title}. ${description}` : title })
        }
      },
    })
  }

  useShortcut('saveSettings', save, { enabled: active })

  const formError = server?.form ?? (submitted ? local.form : undefined)
  const nameOf = (draft: SectionDraft) => draft.title.trim() || 'Untitled section'

  return (
    <SettingsSection title={TITLE} description={DESCRIPTION}>
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

        <SortableRows
          items={drafts}
          idOf={(draft) => draft.id}
          nameOf={nameOf}
          label="Sections"
          onMove={move}
        >
          {(draft, index) => {
            const label = draft.title.trim() || `Section ${index + 1}`
            const keys = moveKeysFor(index, (to) => move(index, to))
            const controls = (className: string) => (
              <RowControls
                label={label}
                index={index}
                count={drafts.length}
                onMove={(to) => move(index, to)}
                onRemove={() => (draft.proposalCount > 0 ? setConfirmRemove(draft) : remove(draft))}
                removeDisabledReason={
                  drafts.length <= MIN_SECTIONS
                    ? 'A proposal needs at least one section'
                    : undefined
                }
                className={className}
              />
            )
            return (
              <SortableRow key={draft.id} id={draft.id} label={label}>
                <div className="grid gap-3 sm:grid-cols-[minmax(0,14rem)_minmax(0,1fr)_auto] sm:items-start">
                  <div className="flex min-w-0 items-start gap-1">
                    <Field
                      label="Title"
                      hideLabel
                      error={shown(draft.id, 'title')}
                      id={`section-${draft.id}-title`}
                      className="min-w-0 flex-1"
                    >
                      <Input
                        value={draft.title}
                        maxLength={SECTION_LIMITS.title + 10}
                        placeholder="Title, e.g. Problem"
                        autoComplete="off"
                        className="font-medium"
                        onChange={(event) => update(draft.id, { title: event.target.value })}
                        onBlur={() => touch(`${draft.id}:title`)}
                        {...keys}
                      />
                    </Field>
                    {controls('pt-1 sm:hidden')}
                  </div>
                  <Field
                    label="Hint"
                    hideLabel
                    error={shown(draft.id, 'hint')}
                    id={`section-${draft.id}-hint`}
                  >
                    <Input
                      value={draft.hint}
                      maxLength={SECTION_LIMITS.hint + 10}
                      placeholder="One line: what to write here"
                      autoComplete="off"
                      onChange={(event) => update(draft.id, { hint: event.target.value })}
                      onBlur={() => touch(`${draft.id}:hint`)}
                      {...keys}
                    />
                  </Field>
                  {controls('pt-1 max-sm:hidden')}
                </div>
              </SortableRow>
            )
          }}
        </SortableRows>

        <div className="flex flex-wrap items-center gap-3">
          <Button
            variant="outline"
            size="sm"
            disabled={drafts.length >= MAX_SECTIONS}
            onClick={() => {
              const added = emptySection()
              setDrafts((current) => [...current, added])
              focusTitle(added.id)
            }}
          >
            <Plus /> Add section
          </Button>
          {drafts.length >= MAX_SECTIONS && (
            <span className="text-sm text-muted">
              That’s the maximum: a short proposal is read to the end.
            </span>
          )}
        </div>

        {removed.length > 0 && (
          <div className="flex flex-col gap-2">
            <h3 className="text-sm font-medium text-primary">Removed sections</h3>
            <p className="text-sm text-muted">
              Hidden from the editor and the exports. Restore one to bring its text back.
            </p>
            <ul className="divide-y divide-subtle rounded-lg border">
              {removed.map((section) => (
                <li
                  key={section.key}
                  className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-2.5"
                >
                  <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                    <span className="truncate text-sm font-medium text-primary">
                      {section.title}
                    </span>
                    <span className="text-xs text-muted">
                      {removedSectionNote(section)} · removed {formatShortDate(section.removed_at)}
                    </span>
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={drafts.length >= MAX_SECTIONS}
                    aria-label={`Restore ${section.title}`}
                    onClick={() => {
                      const restored = restoredSection(section)
                      setDrafts((current) => [...current, restored])
                      setNotice(null)
                      focusTitle(restored.id)
                    }}
                  >
                    <RotateCcw /> Restore
                  </Button>
                </li>
              ))}
            </ul>
          </div>
        )}

        <div className="flex gap-3 rounded-lg border bg-subtle px-4 py-3 text-sm text-secondary">
          <Info aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-muted" />
          <div className="flex flex-col gap-1">
            <p className="font-medium text-primary">What happens to existing proposals</p>
            <ul className="flex list-disc flex-col gap-0.5 pl-4">
              <li>Every proposal in this project follows the template as soon as you save.</li>
              <li>Renaming, rewording or reordering a section keeps its text.</li>
              <li>
                Removing a section hides its text from the editor and the exports; restore it to
                bring the text back.
              </li>
              <li>A new section starts empty in every proposal.</li>
            </ul>
          </div>
        </div>

        <FormActions
          form="the proposal template"
          dirty={dirty}
          saving={replace.isPending}
          notice={notice}
          onDiscard={discard}
          saveLabel="Save template"
        />
      </form>
      <ConfirmDialog
        open={confirmRemove !== null}
        onOpenChange={(open) => !open && setConfirmRemove(null)}
        title={`Remove “${confirmRemove ? nameOf(confirmRemove) : ''}”?`}
        description={
          confirmRemove
            ? `Its text in ${confirmRemove.proposalCount} ${confirmRemove.proposalCount === 1 ? 'proposal is' : 'proposals is'} kept and comes back if you restore it.`
            : ''
        }
        confirmLabel="Remove section"
        onConfirm={() => {
          if (confirmRemove) remove(confirmRemove)
          setConfirmRemove(null)
        }}
      />
    </SettingsSection>
  )
}

/** What members and viewers see: the sections, in order. */
export function ProposalTemplateSummary({ project }: { project: Project }) {
  const template = useProposalTemplate(project.slug)
  return (
    <SettingsSection
      title={TITLE}
      description="Every proposal in this project has these sections. Only project admins can change them."
    >
      {template.isPending ? (
        <TemplateSkeleton />
      ) : template.isError ? (
        <LoadError what="the proposal template" onRetry={() => void template.refetch()} />
      ) : (
        <ol className="flex max-w-3xl flex-col divide-y divide-subtle rounded-lg border">
          {template.data.sections.map((section, index) => (
            <li key={section.key} className="flex items-start gap-3 px-4 py-3">
              <span className="w-5 shrink-0 text-sm text-muted tabular-nums">{index + 1}.</span>
              <div className="flex min-w-0 flex-col gap-0.5">
                <span className="text-sm font-medium text-primary">{section.title}</span>
                {section.hint && <span className="text-sm text-muted">{section.hint}</span>}
              </div>
            </li>
          ))}
        </ol>
      )}
    </SettingsSection>
  )
}

function TemplateSkeleton() {
  return (
    <SkeletonGroup label="Loading the proposal template" className="flex max-w-3xl flex-col gap-3">
      {[0, 1, 2, 3].map((i) => (
        <Skeleton key={i} className="h-14 w-full rounded-lg" />
      ))}
    </SkeletonGroup>
  )
}

export function LoadError({ what, onRetry }: { what: string; onRetry: () => void }) {
  return (
    <div
      role="alert"
      className="flex max-w-3xl flex-wrap items-center gap-3 rounded-lg border px-4 py-3 text-sm text-secondary"
    >
      <CloudOff aria-hidden="true" className="size-4 text-muted" />
      We couldn’t load {what}.
      <Button size="sm" variant="outline" onClick={onRetry}>
        Try again
      </Button>
    </div>
  )
}
