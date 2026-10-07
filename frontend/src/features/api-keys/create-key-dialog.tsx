import { useState } from 'react'

import type { useCreateApiKey } from '@/api/api-keys'
import { describeError, hasErrorCode, isApiError } from '@/api/errors'
import { useProjects } from '@/api/projects'
import type { ApiKeyScope } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Callout } from '@/components/ui/callout'
import { Checkbox } from '@/components/ui/checkbox'
import { DatePicker } from '@/components/ui/date-picker'
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { ariaKeys, ButtonShortcut } from '@/components/ui/kbd'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { SegmentedControl } from '@/components/ui/segmented-control'
import { Skeleton, SkeletonGroup } from '@/components/ui/skeleton'
import { formatDate } from '@/lib/dates'
import { SHORTCUTS, useShortcut } from '@/lib/shortcuts'
import { cn } from '@/lib/utils'

import {
  accessSummary,
  EXPIRY_CHOICES,
  expiresAt,
  expiryDateBounds,
  mcpWithoutTools,
  presetOf,
  readIsIncluded,
  SCOPE_COPY,
  SCOPE_PRESETS,
  SCOPES,
  toggleScope,
  type ExpiryChoice,
} from './key-rules'

const NAME_ID = 'create-key-name'
const NAME_MAX = 80
const SUMMARY_ID = 'create-key-summary'
const SCOPES_ERROR_ID = 'create-key-scopes-error'

export type CreateKeyMutation = ReturnType<typeof useCreateApiKey>

interface FormErrors {
  name?: string
  scopes?: string
  expiry?: string
  projects?: string
  form?: string
}

/**
 * "Create key" (contract-phase5 §3.10): a name, scopes (with presets; `read`
 * ticked and locked while `write` or `evaluate` is), an expiry and an optional
 * project restriction. Nothing can be changed afterwards. On success the page
 * shows the secret once (`SecretDialog`).
 */
export function CreateKeyDialog({
  open,
  onOpenChange,
  create,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  create: CreateKeyMutation
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        size="lg"
        mobile="fullscreen"
        onOpenAutoFocus={(event) => {
          event.preventDefault()
          document.getElementById(NAME_ID)?.focus()
        }}
      >
        {/* Mounted per opening: every key starts from a blank form. */}
        {open && <CreateKeyForm create={create} onCancel={() => onOpenChange(false)} />}
      </DialogContent>
    </Dialog>
  )
}

function CreateKeyForm({ create, onCancel }: { create: CreateKeyMutation; onCancel: () => void }) {
  const projects = useProjects()
  const [name, setName] = useState('')
  const [scopes, setScopes] = useState<ApiKeyScope[]>(['read'])
  // The presets say what a key is for; the scope checkboxes are for "Custom" only.
  const [custom, setCustom] = useState(false)
  const [expiry, setExpiry] = useState<ExpiryChoice>('90d')
  const [date, setDate] = useState('')
  const [restrict, setRestrict] = useState<'all' | 'some'>('all')
  const [projectIds, setProjectIds] = useState<string[]>([])
  const [errors, setErrors] = useState<FormErrors>({})
  const bounds = expiryDateBounds()
  const expiresValue = expiresAt(expiry, date)
  const preset = presetOf(scopes)
  const chosen = (projects.data ?? []).filter((project) => projectIds.includes(project.id))
  const summary = accessSummary(
    { scopes, restricted: restrict === 'some', projects: chosen, expires_at: expiresValue },
    { noProjects: 'only in the projects you choose' },
  )
  const clear = (field: keyof FormErrors) => {
    if (errors[field] || errors.form)
      setErrors((e) => ({ ...e, [field]: undefined, form: undefined }))
  }

  const submit = () => {
    if (create.isPending) return
    const found: FormErrors = {
      name: name.trim() ? undefined : 'Give the key a name, so you know what it’s for',
      scopes: scopes.length ? undefined : 'Choose at least one scope',
      expiry:
        expiresValue === undefined ? 'Choose a date from tomorrow to a year from now' : undefined,
      projects:
        restrict === 'some' && projectIds.length === 0
          ? 'Choose at least one project, or allow all projects'
          : undefined,
    }
    if (found.name ?? found.scopes ?? found.expiry ?? found.projects) {
      setErrors(found)
      if (found.name) document.getElementById(NAME_ID)?.focus()
      return
    }
    setErrors({})
    create.mutate(
      {
        name: name.trim(),
        scopes,
        expires_at: expiresValue ?? null,
        project_ids: restrict === 'some' ? projectIds : null,
      },
      {
        // The secret dialog takes over (the page shows it from the mutation's result).
        onSuccess: onCancel,
        onError: (error) => {
          if (hasErrorCode(error, 'api_key_name_taken')) {
            setErrors({ name: 'You already have a key with this name. Choose another one.' })
            document.getElementById(NAME_ID)?.focus()
          } else if (hasErrorCode(error, 'invalid_project')) {
            setErrors({ projects: 'Choose only projects you can open in Soundings.' })
          } else if (isApiError(error) && error.status === 422) {
            const fields = error.fieldErrors
            setErrors({
              name: fields.name,
              scopes: fields.scopes,
              expiry: fields.expires_at,
              projects: fields.project_ids,
              form:
                (fields.name ?? fields.scopes ?? fields.expires_at ?? fields.project_ids)
                  ? undefined
                  : describeError(error).title,
            })
          } else {
            const { title, description } = describeError(error)
            setErrors({ form: description ? `${title}. ${description}` : title })
          }
        },
      },
    )
  }

  useShortcut('submitForm', submit)

  return (
    <form
      noValidate
      className="flex min-h-0 flex-1 flex-col"
      onSubmit={(event) => {
        event.preventDefault()
        submit()
      }}
    >
      {/* A long form: lines keep the header and the buttons apart from what scrolls. */}
      <DialogHeader className="border-b border-subtle pb-4">
        <DialogTitle>Create API key</DialogTitle>
        <DialogDescription>
          The key acts as you, limited to what you choose here, and never does more than you can. It
          can’t be changed later: create another key instead.
        </DialogDescription>
      </DialogHeader>
      <DialogBody className="flex flex-col gap-6 py-5">
        {errors.form && <Callout role="alert" tone="danger" title={errors.form} />}

        <Field
          label="Name"
          required
          id={NAME_ID}
          error={errors.name}
          description="What it’s for, e.g. “Claude Desktop” or “Weekly report”."
        >
          <Input
            value={name}
            maxLength={NAME_MAX}
            autoComplete="off"
            spellCheck={false}
            onChange={(event) => {
              setName(event.target.value.replace(/[\r\n]+/g, ' '))
              clear('name')
            }}
          />
        </Field>

        <fieldset
          className="flex flex-col gap-3"
          aria-describedby={errors.scopes ? SCOPES_ERROR_ID : undefined}
        >
          <legend className="mb-1.5 text-sm font-medium text-primary">What it can do</legend>
          <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Presets">
            {SCOPE_PRESETS.map((option) => (
              <Button
                key={option.value}
                type="button"
                size="sm"
                variant="outline"
                aria-pressed={!custom && preset === option.value}
                className="aria-pressed:border-accent-control aria-pressed:bg-accent-subtle aria-pressed:font-semibold aria-pressed:text-accent"
                onClick={() => {
                  setCustom(false)
                  setScopes([...option.scopes])
                  clear('scopes')
                }}
              >
                {option.label}
              </Button>
            ))}
            <Button
              type="button"
              size="sm"
              variant="outline"
              aria-pressed={custom || preset === null}
              aria-controls="create-key-scopes"
              className="aria-pressed:border-accent-control aria-pressed:bg-accent-subtle aria-pressed:font-semibold aria-pressed:text-accent"
              onClick={() => setCustom(true)}
            >
              Custom
            </Button>
          </div>
          <p className="-mt-1 text-sm text-muted" aria-live="polite">
            {custom || preset === null
              ? 'Choose the scopes yourself.'
              : SCOPE_PRESETS.find((option) => option.value === preset)?.description}
          </p>
          <ul
            id="create-key-scopes"
            hidden={!custom && preset !== null}
            className="flex flex-col divide-y divide-subtle rounded-lg border"
          >
            {SCOPES.map((scope) => {
              const locked = scope === 'read' && readIsIncluded(scopes)
              return (
                <li key={scope} className="px-3 py-2.5">
                  <Field
                    inline
                    label={
                      <span className="inline-flex items-center gap-1.5">
                        <span className="font-medium">{SCOPE_COPY[scope].label}</span>
                        {locked && (
                          <Badge variant="neutral" aria-hidden="true">
                            Included
                          </Badge>
                        )}
                      </span>
                    }
                    description={
                      locked
                        ? `${SCOPE_COPY.read.description} Included with Write and Evaluate.`
                        : SCOPE_COPY[scope].description
                    }
                  >
                    <Checkbox
                      checked={scopes.includes(scope)}
                      disabled={locked}
                      onCheckedChange={(checked) => {
                        setScopes((current) => toggleScope(current, scope, checked === true))
                        clear('scopes')
                      }}
                    />
                  </Field>
                </li>
              )
            })}
          </ul>
          {mcpWithoutTools(scopes) && (
            <Callout tone="warning" role="status" title="This key can connect, but do nothing">
              An assistant acts through Read, Write or Evaluate. Add at least Read.
            </Callout>
          )}
          {errors.scopes && (
            <p id={SCOPES_ERROR_ID} role="alert" className="text-sm text-danger">
              {errors.scopes}
            </p>
          )}
        </fieldset>

        <Field
          label="Expires"
          error={errors.expiry}
          description={
            expiry === 'never'
              ? 'Never expires. Revoke it when you no longer need it.'
              : expiresValue
                ? `Stops working on ${formatDate(expiresValue)}.`
                : 'Choose the last day it works.'
          }
        >
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
            <SegmentedControl
              value={expiry}
              onValueChange={(value) => {
                setExpiry(value)
                clear('expiry')
              }}
              options={EXPIRY_CHOICES}
              className="self-start max-sm:w-full"
              fullWidth
            />
            {expiry === 'date' && (
              <DatePicker
                aria-label="Expiry date"
                value={date}
                min={bounds.min}
                max={bounds.max}
                onValueChange={(value) => {
                  setDate(value)
                  clear('expiry')
                }}
              />
            )}
          </div>
        </Field>

        <Field label="Projects" error={errors.projects}>
          <RadioGroup
            value={restrict}
            onValueChange={(value) => {
              setRestrict(value as 'all' | 'some')
              clear('projects')
            }}
            className="gap-2"
          >
            <RestrictOption
              value="all"
              label="All projects you can access"
              help="Including projects you join later."
            />
            <RestrictOption
              value="some"
              label="Only these projects"
              help="Everything else is invisible to the key, even where you have access."
            />
          </RadioGroup>
          {restrict === 'all' && scopes.includes('mcp') && (
            <p className="text-sm text-muted">
              An assistant reads whatever its key can reach: keep it to the projects it needs.
            </p>
          )}
          {restrict === 'some' && (
            <ProjectChoices
              loading={projects.isPending}
              failed={projects.isError}
              onRetry={() => void projects.refetch()}
              projects={projects.data ?? []}
              selected={projectIds}
              onChange={(next) => {
                setProjectIds(next)
                clear('projects')
              }}
            />
          )}
        </Field>
      </DialogBody>
      {/* What the choices above add up to, in plain words; updates as they change. */}
      <p id={SUMMARY_ID} className="border-t border-subtle px-5 pt-3 text-sm text-secondary">
        <span className="font-medium text-primary">This key can </span>
        {summary}.
      </p>
      <DialogFooter className="pt-3 in-data-[mobile=fullscreen]:max-sm:border-t-0">
        <Button type="button" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
        <Button
          type="submit"
          variant="primary"
          loading={create.isPending}
          aria-describedby={SUMMARY_ID}
          aria-keyshortcuts={ariaKeys(SHORTCUTS.submitForm.keys)}
        >
          Create key
          <ButtonShortcut keys={SHORTCUTS.submitForm.keys} />
        </Button>
      </DialogFooter>
    </form>
  )
}

function RestrictOption({ value, label, help }: { value: string; label: string; help: string }) {
  const id = `create-key-projects-${value}`
  return (
    <label
      htmlFor={id}
      className="flex cursor-pointer items-start gap-3 rounded-lg border px-3 py-2.5 transition-colors hover:bg-subtle has-[[data-state=checked]]:border-accent"
    >
      <RadioGroupItem id={id} value={value} className="mt-0.5" aria-describedby={`${id}-help`} />
      <span className="flex flex-col gap-0.5">
        <span className="text-sm font-medium text-primary">{label}</span>
        <span id={`${id}-help`} className="text-sm text-muted">
          {help}
        </span>
      </span>
    </label>
  )
}

function ProjectChoices({
  projects,
  selected,
  onChange,
  loading,
  failed,
  onRetry,
}: {
  projects: { id: string; name: string; key: string; my_role: string | null }[]
  selected: string[]
  onChange: (ids: string[]) => void
  loading: boolean
  failed: boolean
  onRetry: () => void
}) {
  if (loading) {
    return (
      <SkeletonGroup label="Loading projects" className="flex flex-col gap-2 rounded-lg border p-3">
        <Skeleton className="h-4 w-48" />
        <Skeleton className="h-4 w-40" />
      </SkeletonGroup>
    )
  }
  if (failed) {
    return (
      <Callout
        role="alert"
        tone="danger"
        title="Couldn’t load your projects"
        action={
          <Button size="sm" variant="secondary" onClick={onRetry}>
            Try again
          </Button>
        }
      />
    )
  }
  if (projects.length === 0) {
    return <p className="text-sm text-muted">You can’t open any projects yet.</p>
  }
  return (
    <ul
      aria-label="Projects the key may use"
      className="flex max-h-56 flex-col overflow-y-auto rounded-lg border py-1"
    >
      {projects.map((project) => (
        <li key={project.id} className={cn('px-3 py-1.5')}>
          <Field
            inline
            label={project.name}
            description={project.my_role ? undefined : 'You aren’t a member: read-only'}
          >
            <Checkbox
              checked={selected.includes(project.id)}
              onCheckedChange={(checked) =>
                onChange(
                  checked === true
                    ? [...selected, project.id]
                    : selected.filter((id) => id !== project.id),
                )
              }
            />
          </Field>
        </li>
      ))}
    </ul>
  )
}
