import { useRouter } from '@tanstack/react-router'
import { Archive, ArchiveRestore, CircleAlert, Globe, Lock } from 'lucide-react'
import { useState } from 'react'

import { describeError, isApiError } from '@/api/errors'
import { useUpdateProject } from '@/api/projects'
import type { Project, ProjectUpdate, ProjectVisibility } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { toast } from '@/components/ui/toaster'
import { useShortcut } from '@/lib/shortcuts'

import { FormActions, SettingsSection } from './settings-layout'

interface GeneralForm {
  name: string
  description: string
  visibility: ProjectVisibility
  allow_volunteer_owners: boolean
  default_evaluation_days: string
}

type Errors = Partial<Record<keyof GeneralForm | 'form', string>>

const fromProject = (project: Project): GeneralForm => ({
  name: project.name,
  description: project.description,
  visibility: project.visibility,
  allow_volunteer_owners: project.allow_volunteer_owners,
  default_evaluation_days: String(project.default_evaluation_days),
})

const VISIBILITY = {
  private: { label: 'Private', icon: Lock, help: 'Only members can see the project.' },
  internal: {
    label: 'Internal',
    icon: Globe,
    help: 'Everyone who can sign in can see it; only members can take part.',
  },
} as const

function validate(form: GeneralForm): Errors {
  const errors: Errors = {}
  if (!form.name.trim()) errors.name = 'Give the project a name.'
  else if (form.name.trim().length > 80) errors.name = 'At most 80 characters.'
  if (form.description.length > 1000) errors.description = 'At most 1,000 characters.'
  const days = Number(form.default_evaluation_days)
  if (!/^\d+$/.test(form.default_evaluation_days.trim()) || days < 1 || days > 90) {
    errors.default_evaluation_days = 'Use a whole number of days from 1 to 90.'
  }
  return errors
}

/** Only the fields that changed, so a save never overwrites someone else's edit elsewhere. */
function changes(form: GeneralForm, saved: GeneralForm): ProjectUpdate {
  const body: ProjectUpdate = {}
  if (form.name.trim() !== saved.name) body.name = form.name.trim()
  if (form.description.trim() !== saved.description) body.description = form.description.trim()
  if (form.visibility !== saved.visibility) body.visibility = form.visibility
  if (form.allow_volunteer_owners !== saved.allow_volunteer_owners) {
    body.allow_volunteer_owners = form.allow_volunteer_owners
  }
  if (form.default_evaluation_days.trim() !== saved.default_evaluation_days) {
    body.default_evaluation_days = Number(form.default_evaluation_days)
  }
  return body
}

/** Name, description, visibility, volunteering and the evaluation window. */
export function GeneralSettings({ project, active }: { project: Project; active: boolean }) {
  const update = useUpdateProject(project.slug, { undo: false })
  const router = useRouter()
  // What was last saved: compared with the form for "dirty". A failed save keeps
  // the form as typed (the optimistic cache update is rolled back, not the form).
  const [saved, setSaved] = useState(() => fromProject(project))
  const [form, setForm] = useState(saved)
  const [errors, setErrors] = useState<Errors>({})
  const [notice, setNotice] = useState<string | null>(null)

  const body = changes(form, saved)
  const dirty = Object.keys(body).length > 0

  // Saved elsewhere (another tab, a refetch): follow the server unless there are edits here.
  const [seen, setSeen] = useState(project)
  if (project !== seen) {
    setSeen(project)
    if (!dirty) {
      const fresh = fromProject(project)
      setSaved(fresh)
      setForm(fresh)
    }
  }

  const set = (patch: Partial<GeneralForm>) => {
    setForm((current) => ({ ...current, ...patch }))
    setNotice(null)
    const keys = Object.keys(patch) as (keyof GeneralForm)[]
    if (keys.some((key) => errors[key]) || errors.form) {
      setErrors((current) => {
        const next = { ...current, form: undefined }
        for (const key of keys) next[key] = undefined
        return next
      })
    }
  }

  const save = () => {
    if (update.isPending) return
    if (!dirty) {
      setNotice('No changes to save.')
      return
    }
    const found = validate(form)
    if (Object.keys(found).length > 0) {
      setErrors(found)
      const first = (['name', 'description', 'default_evaluation_days'] as const).find(
        (key) => found[key],
      )
      if (first) document.getElementById(`project-${first}`)?.focus()
      return
    }
    update.mutate(body, {
      onSuccess: (next) => {
        const fresh = fromProject(next)
        setSaved(fresh)
        setForm(fresh)
        toast.success('Settings saved')
        // The breadcrumb and page title come from the route loader.
        if (body.name) void router.invalidate()
      },
      onError: (error) => {
        const fields = isApiError(error) ? error.fieldErrors : {}
        if (Object.keys(fields).length > 0) setErrors(fields)
        else {
          const { title, description } = describeError(error)
          setErrors({ form: description ? `${title}. ${description}` : title })
        }
      },
    })
  }

  useShortcut('saveSettings', save, { enabled: active })

  return (
    <SettingsSection
      title="General"
      description="What the project is called, who can see it, and how ideas get owners."
    >
      <form
        noValidate
        className="flex max-w-2xl flex-col gap-6"
        onSubmit={(event) => {
          event.preventDefault()
          save()
        }}
      >
        {errors.form && (
          <p
            role="alert"
            className="flex items-start gap-2 rounded-md bg-danger-subtle px-3 py-2 text-sm text-danger"
          >
            <CircleAlert aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
            {errors.form}
          </p>
        )}
        <Field label="Name" required error={errors.name} id="project-name">
          <Input
            value={form.name}
            maxLength={80}
            autoComplete="off"
            onChange={(event) => set({ name: event.target.value })}
          />
        </Field>
        <Field
          label="Description"
          description="One or two sentences shown under the project name."
          error={errors.description}
          id="project-description"
        >
          <Textarea
            value={form.description}
            maxLength={1000}
            minRows={2}
            maxRows={6}
            onChange={(event) => set({ description: event.target.value })}
          />
        </Field>
        <Field label="Visibility">
          <RadioGroup
            value={form.visibility}
            onValueChange={(value) => set({ visibility: value as ProjectVisibility })}
          >
            {(['private', 'internal'] as const).map((value) => {
              const option = VISIBILITY[value]
              const Icon = option.icon
              return (
                <label
                  key={value}
                  htmlFor={`visibility-${value}`}
                  className="flex cursor-pointer items-start gap-3 rounded-lg border px-3 py-2.5 transition-colors hover:bg-subtle has-[[data-state=checked]]:border-accent"
                >
                  <RadioGroupItem
                    id={`visibility-${value}`}
                    value={value}
                    className="mt-0.5"
                    aria-describedby={`visibility-${value}-help`}
                  />
                  <span className="flex flex-col gap-0.5">
                    <span className="flex items-center gap-1.5 text-sm font-medium text-primary">
                      <Icon aria-hidden="true" className="size-3.5 text-muted" />
                      {option.label}
                    </span>
                    <span id={`visibility-${value}-help`} className="text-sm text-muted">
                      {option.help}
                    </span>
                  </span>
                </label>
              )
            })}
          </RadioGroup>
        </Field>
        <Field
          inline
          label="Members can volunteer to own ideas"
          description="Adds “I’ll own this” to unowned ideas. Admins can always assign owners."
        >
          <Switch
            checked={form.allow_volunteer_owners}
            onCheckedChange={(checked) => set({ allow_volunteer_owners: checked })}
          />
        </Field>
        <Field
          label="Evaluation window"
          description="Evaluators have this many days from the first invite. Reminders go out 2 days before the due date and on the day."
          error={errors.default_evaluation_days}
          id="project-default_evaluation_days"
        >
          <div className="flex items-center gap-2">
            <Input
              value={form.default_evaluation_days}
              inputMode="numeric"
              autoComplete="off"
              className="w-20 text-right tabular-nums"
              onChange={(event) => set({ default_evaluation_days: event.target.value })}
            />
            <span className="text-sm text-muted">days</span>
          </div>
        </Field>
        <FormActions
          form="the general settings"
          dirty={dirty}
          saving={update.isPending}
          notice={notice}
          onDiscard={() => {
            setForm(saved)
            setErrors({})
            setNotice(null)
          }}
        />
      </form>
      <ArchiveProject project={project} />
    </SettingsSection>
  )
}

/**
 * Archive or restore, applied at once with an Undo toast (wireframe 07:
 * destructive-ish actions undo rather than confirm).
 */
function ArchiveProject({ project }: { project: Project }) {
  const update = useUpdateProject(project.slug)
  const archived = Boolean(project.archived_at)
  return (
    <div className="flex max-w-2xl flex-col gap-3 rounded-lg border px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex flex-col gap-0.5">
        <h3 className="text-sm font-medium text-primary">
          {archived ? 'This project is archived' : 'Archive this project'}
        </h3>
        <p className="text-sm text-muted">
          {archived
            ? 'Its ideas are read-only and it is hidden from the sidebar, search and My work. Restore it to work on it again.'
            : 'Makes its ideas read-only and hides it from the sidebar, search and My work. Nothing is deleted; you can restore it at any time.'}
        </p>
      </div>
      <Button
        variant="outline"
        className="shrink-0"
        loading={update.isPending}
        onClick={() => update.mutate({ archived: !archived })}
      >
        {archived ? <ArchiveRestore /> : <Archive />}
        {archived ? 'Restore project' : 'Archive project'}
      </Button>
    </div>
  )
}

/** What non-admins see: the same settings, read-only. */
export function GeneralSummary({ project }: { project: Project }) {
  const visibility = VISIBILITY[project.visibility]
  const rows: [string, string][] = [
    ['Name', project.name],
    ['Description', project.description || '—'],
    ['Visibility', `${visibility.label}: ${visibility.help}`],
    [
      'Owners',
      project.allow_volunteer_owners
        ? 'Members can volunteer to own ideas.'
        : 'Admins assign owners.',
    ],
    ['Evaluation window', `${project.default_evaluation_days} days from the first invite`],
  ]
  return (
    <SettingsSection title="General" description="The project’s name, visibility and defaults.">
      <dl className="flex max-w-2xl flex-col divide-y divide-subtle rounded-lg border">
        {rows.map(([label, value]) => (
          <div
            key={label}
            className="grid gap-1 px-4 py-3 sm:grid-cols-[10rem_minmax(0,1fr)] sm:gap-4"
          >
            <dt className="text-sm text-muted">{label}</dt>
            <dd className="text-sm text-primary">{value}</dd>
          </div>
        ))}
      </dl>
    </SettingsSection>
  )
}
