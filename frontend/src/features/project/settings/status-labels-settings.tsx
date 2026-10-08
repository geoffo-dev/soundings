import { CircleAlert, RotateCcw } from 'lucide-react'
import { useState } from 'react'

import { describeError, isApiError } from '@/api/errors'
import { useUpdateProject } from '@/api/projects'
import type { Project, StatusLabels } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { StatusBadge } from '@/components/ui/status-badge'
import { toast } from '@/components/ui/toaster'
import { WithTooltip } from '@/components/ui/tooltip'
import { useShortcut } from '@/lib/shortcuts'
import { CLOSED_RESOLUTIONS, type IdeaStatus } from '@/lib/status'

import { FormActions, SettingsSection } from './settings-layout'
import { DEFAULT_LABELS as DEFAULTS, labelChanges, type LabelKey } from './status-labels'

const MAX_LENGTH = 24

/**
 * Rename the stages and three resolutions (the stages themselves are fixed; Phase
 * 8: Research is listed only while the project's research step is on, at its
 * position). An empty field goes back to the default name.
 */
export function StatusLabelsSettings({ project, active }: { project: Project; active: boolean }) {
  const update = useUpdateProject(project.slug, { undo: false })
  const [saved, setSaved] = useState<StatusLabels>(project.status_labels)
  const [form, setForm] = useState<StatusLabels>(project.status_labels)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const body = labelChanges(form, saved)
  const dirty = Object.keys(body).length > 0

  // Saved elsewhere (another tab, a refetch): follow the server unless there are edits here.
  const [seen, setSeen] = useState(project.status_labels)
  if (project.status_labels !== seen) {
    setSeen(project.status_labels)
    if (!dirty) {
      setSaved(project.status_labels)
      setForm(project.status_labels)
    }
  }
  const shown = (key: LabelKey) => form[key].trim() || DEFAULTS[key]
  const stages = project.lifecycle

  const set = (key: LabelKey, value: string) => {
    setForm((current) => ({ ...current, [key]: value }))
    setNotice(null)
    setError(null)
  }

  const save = () => {
    if (update.isPending) return
    if (!dirty) {
      setNotice('No changes to save.')
      return
    }
    update.mutate(
      { status_labels: body },
      {
        onSuccess: (next) => {
          setSaved(next.status_labels)
          setForm(next.status_labels)
          toast.success('Status labels saved')
        },
        onError: (failure) => {
          const fields = isApiError(failure) ? Object.values(failure.fieldErrors) : []
          const { title, description } = describeError(failure)
          setError(fields[0] ?? (description ? `${title}. ${description}` : title))
        },
      },
    )
  }

  useShortcut('saveSettings', save, { enabled: active })

  const row = (key: LabelKey, tone: IdeaStatus | null) => {
    const isDefault = shown(key) === DEFAULTS[key]
    const id = `label-${key}`
    return (
      <li key={key} className="flex items-center gap-3 px-4 py-2.5">
        <label htmlFor={id} className="w-28 shrink-0 text-sm text-secondary">
          <StatusBadge
            variant="plain"
            status={tone ?? 'closed'}
            resolution={tone ? null : (key as (typeof CLOSED_RESOLUTIONS)[number])}
            label={DEFAULTS[key]}
            className="font-normal text-secondary"
          />
        </label>
        <Input
          id={id}
          value={form[key]}
          maxLength={MAX_LENGTH}
          placeholder={DEFAULTS[key]}
          autoComplete="off"
          className="max-w-64"
          onChange={(event) => set(key, event.target.value)}
        />
        <WithTooltip content={`Back to “${DEFAULTS[key]}”`}>
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label={`Reset ${DEFAULTS[key]} to its default name`}
            className={isDefault ? 'invisible' : undefined}
            disabled={isDefault}
            onClick={() => set(key, DEFAULTS[key])}
          >
            <RotateCcw />
          </Button>
        </WithTooltip>
      </li>
    )
  }

  return (
    <SettingsSection
      title="Status labels"
      description="Rename the stages to match how your team talks. The stages themselves are fixed."
      actions={
        <Button
          variant="ghost"
          size="sm"
          className="text-muted"
          onClick={() => {
            setForm(DEFAULTS)
            setNotice(null)
          }}
        >
          <RotateCcw /> Reset all to default
        </Button>
      }
    >
      <form
        noValidate
        className="flex max-w-2xl flex-col gap-5"
        onSubmit={(event) => {
          event.preventDefault()
          save()
        }}
      >
        {error && (
          <p
            role="alert"
            className="flex items-start gap-2 rounded-md bg-danger-subtle px-3 py-2 text-sm text-danger"
          >
            <CircleAlert aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
            {error}
          </p>
        )}
        <div className="flex flex-col gap-2">
          <h3 className="text-sm font-medium text-primary">Stages</h3>
          <ul className="divide-y divide-subtle rounded-lg border">
            {stages.map((status) => row(status, status))}
          </ul>
        </div>
        <div className="flex flex-col gap-2">
          <h3 className="text-sm font-medium text-primary">How closed ideas end</h3>
          <ul className="divide-y divide-subtle rounded-lg border">
            {CLOSED_RESOLUTIONS.map((resolution) => row(resolution, null))}
          </ul>
        </div>
        <div className="flex flex-col gap-2">
          <h3 className="text-sm font-medium text-primary">Preview</h3>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-lg bg-background px-4 py-3">
            {stages.map((status) => (
              <StatusBadge key={status} variant="plain" status={status} label={shown(status)} />
            ))}
            <span aria-hidden="true" className="text-muted">
              ·
            </span>
            {CLOSED_RESOLUTIONS.map((resolution) => (
              <StatusBadge
                key={resolution}
                variant="plain"
                status="closed"
                resolution={resolution}
                label={shown(resolution)}
              />
            ))}
          </div>
        </div>
        <FormActions
          form="the status labels"
          saveLabel="Save labels"
          dirty={dirty}
          saving={update.isPending}
          notice={notice}
          onDiscard={() => {
            setForm(saved)
            setError(null)
          }}
        />
      </form>
    </SettingsSection>
  )
}
