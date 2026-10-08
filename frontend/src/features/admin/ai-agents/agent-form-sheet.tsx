import { CloudOff, Info } from 'lucide-react'
import { useState } from 'react'

import { useRegisterAiAgent, useUpdateAiAgent } from '@/api/ai-agents'
import { describeError, hasErrorCode, isApiError } from '@/api/errors'
import { useProjects } from '@/api/projects'
import type {
  AiAgent,
  AiAgentProtocol,
  AiAgentUpdate,
  AiRunKind,
  AiSettingsInEffect,
  CreatedAiAgent,
} from '@/api/types'
import { Button } from '@/components/ui/button'
import { Callout } from '@/components/ui/callout'
import { Checkbox } from '@/components/ui/checkbox'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { ariaKeys, ButtonShortcut } from '@/components/ui/kbd'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
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
import { Textarea } from '@/components/ui/textarea'
import { KIND_COPY, PROTOCOL_COPY, PURPOSE_ORDER } from '@/features/ai/ai-copy'
import { SHORTCUTS, useShortcut } from '@/lib/shortcuts'

import {
  a2aUrlParts,
  DESCRIPTION_MAX,
  DISPLAY_NAME_MAX,
  labelError,
  narrowing,
  typingLabelError,
  validateAgent,
  type AgentDraft,
  type AgentErrors,
} from './agent-rules'

const PURPOSE_HELP: Record<AiRunKind, string> = {
  evaluate: '“Ask AI to evaluate”: scores the rubric with a rationale and sources per criterion.',
  research: '“Ask AI to research”: writes a cited research note in the idea’s activity.',
  draft_section: '“Draft with AI”: suggests text for one proposal section.',
}

/**
 * Register an agent, or change one (contract-phase6 §3.1, §3.15): its display
 * name (its service account's too), what it does, which projects it serves, and
 * where kagent runs it (namespace and name, fixed once registered). Soundings
 * builds the agent's A2A URL from the controller URL in effect: no URL is typed.
 */
export function AgentFormSheet({
  open,
  onOpenChange,
  agent,
  settings,
  onRegistered,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Editing this agent; registering a new one when absent. */
  agent?: AiAgent
  settings: AiSettingsInEffect
  onRegistered: (created: CreatedAiAgent) => void
}) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent size="md" aria-describedby={undefined}>
        {/* Mounted per opening: every registration starts from a blank form. */}
        {open && (
          <AgentForm
            agent={agent}
            settings={settings}
            onDone={() => onOpenChange(false)}
            onRegistered={onRegistered}
          />
        )}
      </SheetContent>
    </Sheet>
  )
}

function initialDraft(agent: AiAgent | undefined, settings: AiSettingsInEffect): AgentDraft {
  return agent
    ? {
        display_name: agent.display_name,
        description: agent.description,
        namespace: agent.namespace,
        name: agent.name,
        protocol: agent.protocol,
        purposes: [...agent.purposes],
        project_ids: agent.projects.map((project) => project.id),
      }
    : {
        display_name: '',
        description: '',
        namespace:
          settings.agent_namespaces.length === 1 ? (settings.agent_namespaces[0] ?? '') : '',
        name: '',
        protocol: settings.default_protocol,
        purposes: [],
        project_ids: [],
      }
}

function AgentForm({
  agent,
  settings,
  onDone,
  onRegistered,
}: {
  agent?: AiAgent
  settings: AiSettingsInEffect
  onDone: () => void
  onRegistered: (created: CreatedAiAgent) => void
}) {
  const editing = Boolean(agent)
  const register = useRegisterAiAgent()
  const update = useUpdateAiAgent()
  const projects = useProjects()
  const [draft, setDraft] = useState<AgentDraft>(() => initialDraft(agent, settings))
  const [errors, setErrors] = useState<AgentErrors>({})
  const pending = register.isPending || update.isPending

  const set = <K extends keyof AgentDraft>(key: K, value: AgentDraft[K]) => {
    setDraft((previous) => ({ ...previous, [key]: value }))
    if (errors[key]) setErrors((previous) => ({ ...previous, [key]: undefined }))
  }
  const toggle = <T extends string>(list: T[], value: T, on: boolean): T[] =>
    on ? (list.includes(value) ? list : [...list, value]) : list.filter((item) => item !== value)

  const focusFirstError = (found: AgentErrors) => {
    const first = (
      ['display_name', 'description', 'namespace', 'name', 'purposes', 'project_ids'] as const
    ).find((key) => found[key])
    if (first) document.getElementById(`agent-${first}`)?.focus()
  }

  const submit = () => {
    if (pending) return
    const found = validateAgent(draft, {
      allowedNamespaces: settings.agent_namespaces,
      editing,
    })
    if (Object.keys(found).length > 0) {
      setErrors(found)
      focusFirstError(found)
      return
    }
    setErrors({})
    const onError = (error: unknown) => {
      const next: AgentErrors = {}
      if (hasErrorCode(error, 'agent_taken')) {
        next.name = 'An agent with this namespace and name is already registered.'
      } else if (hasErrorCode(error, 'namespace_not_allowed')) {
        next.namespace = `Agents can run in ${settings.agent_namespaces.join(', ')}.`
      } else if (hasErrorCode(error, 'invalid_project')) {
        next.project_ids = 'One of these projects no longer exists. Reload and choose again.'
      } else if (isApiError(error) && error.status === 422) {
        const fields = error.fieldErrors
        Object.assign(next, {
          display_name: fields.display_name,
          description: fields.description,
          namespace: fields.namespace,
          name: fields.name,
          purposes: fields.purposes,
          project_ids: fields.project_ids,
        })
        if (!Object.values(next).some(Boolean)) next.form = describeError(error).title
      } else {
        const { title, description } = describeError(error)
        next.form = description ? `${title}. ${description}` : title
      }
      setErrors(next)
      focusFirstError(next)
    }
    if (!agent) {
      register.mutate(
        {
          display_name: draft.display_name.trim(),
          description: draft.description.trim(),
          namespace: draft.namespace,
          name: draft.name,
          protocol: draft.protocol,
          purposes: draft.purposes,
          project_ids: draft.project_ids,
        },
        {
          onSuccess: (created) => {
            onDone()
            onRegistered(created)
            // The key dialog holds it now: not the mutation cache too (contract-phase6 §3.1).
            register.reset()
          },
          onError,
        },
      )
      return
    }
    const body: AiAgentUpdate = {}
    if (draft.display_name.trim() !== agent.display_name)
      body.display_name = draft.display_name.trim()
    if (draft.description.trim() !== agent.description) body.description = draft.description.trim()
    if (draft.protocol !== agent.protocol) body.protocol = draft.protocol
    if (draft.purposes.join() !== agent.purposes.join()) body.purposes = draft.purposes
    const before = agent.projects
      .map((project) => project.id)
      .sort()
      .join()
    if ([...draft.project_ids].sort().join() !== before) body.project_ids = draft.project_ids
    if (Object.keys(body).length === 0) {
      onDone()
      return
    }
    update.mutate({ agentId: agent.id, body }, { onSuccess: onDone, onError })
  }
  useShortcut('submitForm', submit)

  const dropped = agent ? narrowing(agent, draft) : { purposes: [], projects: [] }
  const allowed = settings.agent_namespaces
  // Namespace and name: what can never be valid shows while typing, the rest on leaving.
  const labelFieldError = (key: 'namespace' | 'name') =>
    errors[key] ?? (editing ? undefined : typingLabelError(draft[key]))
  const checkLabel = (key: 'namespace' | 'name') => {
    if (editing || !draft[key]) return
    const found = labelError(draft[key], key)
    if (found) setErrors((previous) => ({ ...previous, [key]: found }))
  }

  return (
    <form
      noValidate
      className="flex min-h-0 flex-1 flex-col"
      onSubmit={(event) => {
        event.preventDefault()
        submit()
      }}
    >
      <SheetHeader>
        <SheetTitle>{agent ? `Change ${agent.display_name}` : 'Register agent'}</SheetTitle>
        <SheetDescription>
          {agent
            ? 'Its key keeps working: its scopes and projects follow these settings.'
            : 'A kagent agent people can ask to evaluate, research or draft. It gets its own service account and an API key, shown once.'}
        </SheetDescription>
      </SheetHeader>
      <SheetBody className="flex flex-col gap-5">
        {errors.form && <Callout role="alert" tone="danger" title={errors.form} />}
        <Field
          label="Display name"
          required
          error={errors.display_name}
          id="agent-display_name"
          description="What people see next to its work, e.g. “Idea evaluator”."
        >
          <Input
            value={draft.display_name}
            maxLength={DISPLAY_NAME_MAX}
            autoComplete="off"
            onChange={(event) => set('display_name', event.target.value)}
          />
        </Field>
        <Field label="Description" error={errors.description} id="agent-description">
          <Textarea
            value={draft.description}
            maxLength={DESCRIPTION_MAX}
            minRows={2}
            maxRows={6}
            placeholder="What it is for, and who looks after it."
            onChange={(event) => set('description', event.target.value)}
          />
        </Field>

        <fieldset className="flex flex-col gap-3">
          <legend className="mb-1 text-sm font-medium text-primary">Where kagent runs it</legend>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field
              label="Namespace"
              required
              error={labelFieldError('namespace')}
              id="agent-namespace"
              description={
                editing
                  ? 'Can’t change: register another agent.'
                  : allowed.length > 0
                    ? `Allowed: ${allowed.join(', ')}`
                    : 'Any namespace. Lower-case letters, digits and hyphens.'
              }
            >
              <Input
                value={draft.namespace}
                maxLength={63}
                disabled={editing}
                autoComplete="off"
                autoCapitalize="none"
                spellCheck={false}
                // Not monospace: Chromium clips a mono font's underscore inside an input at
                // 1x (DejaVu Sans Mono), so "ops_helper" read as "ops helper".
                placeholder="soundings"
                onChange={(event) => set('namespace', event.target.value)}
                onBlur={() => checkLabel('namespace')}
              />
            </Field>
            <Field
              label="Agent name"
              required
              error={labelFieldError('name')}
              id="agent-name"
              description={
                editing
                  ? 'Can’t change.'
                  : 'The kagent Agent’s metadata.name. Lower-case letters, digits and hyphens.'
              }
            >
              <Input
                value={draft.name}
                maxLength={63}
                disabled={editing}
                autoComplete="off"
                autoCapitalize="none"
                spellCheck={false}
                placeholder="idea-evaluator"
                onChange={(event) => set('name', event.target.value)}
                onBlur={() => checkLabel('name')}
              />
            </Field>
          </div>
          <Field label="Protocol" id="agent-protocol">
            <RadioGroup
              value={draft.protocol}
              onValueChange={(value) => set('protocol', value as AiAgentProtocol)}
            >
              {(Object.keys(PROTOCOL_COPY) as AiAgentProtocol[]).map((protocol) => (
                <label
                  key={protocol}
                  htmlFor={`agent-protocol-${protocol}`}
                  className="flex cursor-pointer items-start gap-3 rounded-lg border px-3 py-2.5 transition-colors hover:bg-subtle has-[[data-state=checked]]:border-accent-control"
                >
                  <RadioGroupItem
                    id={`agent-protocol-${protocol}`}
                    value={protocol}
                    className="mt-0.5"
                    aria-labelledby={`agent-protocol-${protocol}-label`}
                    aria-describedby={`agent-protocol-${protocol}-detail`}
                  />
                  <span className="flex flex-col gap-0.5">
                    <span
                      id={`agent-protocol-${protocol}-label`}
                      className="text-sm font-medium text-primary"
                    >
                      {PROTOCOL_COPY[protocol].label}
                      {protocol === settings.default_protocol && (
                        <span className="font-normal text-muted"> (default)</span>
                      )}
                    </span>
                    <code
                      id={`agent-protocol-${protocol}-detail`}
                      className="font-mono text-xs text-muted"
                    >
                      {PROTOCOL_COPY[protocol].detail}
                    </code>
                  </span>
                </label>
              ))}
            </RadioGroup>
          </Field>
          <p className="flex items-start gap-2 rounded-md bg-background px-3 py-2 text-sm text-secondary">
            <Info aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-muted" />
            <span className="min-w-0">
              Soundings will call{' '}
              <code className="font-mono text-xs break-all text-primary">
                {a2aUrlParts(settings.kagent_url, draft.protocol, draft.namespace, draft.name).map(
                  (part, index) =>
                    part.placeholder ? (
                      // Not filled in yet (or not valid): a placeholder, not part of the URL.
                      <span key={index} className="text-muted italic">
                        {part.text}
                      </span>
                    ) : (
                      part.text
                    ),
                )}
              </code>
              : the controller URL in effect, never one typed here.
            </span>
          </p>
        </fieldset>

        <fieldset
          className="flex flex-col gap-2"
          aria-describedby={errors.purposes ? 'agent-purposes-error' : undefined}
        >
          <legend className="mb-1 text-sm font-medium text-primary">What it does</legend>
          <div
            id="agent-purposes"
            tabIndex={-1}
            className="flex flex-col gap-2.5 rounded-sm outline-offset-2"
          >
            {PURPOSE_ORDER.map((kind) => (
              <Field
                key={kind}
                inline
                label={KIND_COPY[kind].purpose}
                description={PURPOSE_HELP[kind]}
              >
                <Checkbox
                  checked={draft.purposes.includes(kind)}
                  onCheckedChange={(checked) =>
                    set(
                      'purposes',
                      PURPOSE_ORDER.filter((k) =>
                        toggle(draft.purposes, kind, checked === true).includes(k),
                      ),
                    )
                  }
                />
              </Field>
            ))}
          </div>
          {errors.purposes && (
            <p id="agent-purposes-error" role="alert" className="text-sm text-danger">
              {errors.purposes}
            </p>
          )}
        </fieldset>

        <fieldset
          className="flex flex-col gap-2"
          aria-describedby={errors.project_ids ? 'agent-projects-error' : undefined}
        >
          <legend className="mb-1 text-sm font-medium text-primary">Projects it serves</legend>
          <p className="text-sm text-muted">
            It joins each as a member; project admins can remove it there. Its key is limited to
            these projects.
          </p>
          <ProjectChecklist
            loading={projects.isPending}
            failed={projects.isError}
            onRetry={() => void projects.refetch()}
            projects={projects.data ?? []}
            selected={draft.project_ids}
            onChange={(ids) => set('project_ids', ids)}
          />
          {errors.project_ids && (
            <p id="agent-projects-error" role="alert" className="text-sm text-danger">
              {errors.project_ids}
            </p>
          )}
        </fieldset>

        {(dropped.purposes.length > 0 || dropped.projects.length > 0) && (
          <Callout tone="warning" title="Its runs there stop">
            Taking away{' '}
            {[
              ...dropped.purposes.map((kind) => KIND_COPY[kind].purpose.toLowerCase()),
              ...dropped.projects.map((project) => project.name),
            ].join(', ')}{' '}
            cancels the agent’s active runs of that kind or in that project.
          </Callout>
        )}

        <p className="text-sm text-muted">
          The agent works only on the idea of a run someone asked for: outside a run its key does
          nothing, and it never sees other evaluators’ scores.
        </p>
      </SheetBody>
      <SheetFooter>
        <Button type="button" variant="ghost" onClick={onDone}>
          Cancel
        </Button>
        <Button
          type="submit"
          variant="primary"
          loading={pending}
          aria-keyshortcuts={ariaKeys(SHORTCUTS.submitForm.keys)}
        >
          {agent ? 'Save changes' : 'Register agent'}
          <ButtonShortcut keys={SHORTCUTS.submitForm.keys} />
        </Button>
      </SheetFooter>
    </form>
  )
}

function ProjectChecklist({
  projects,
  selected,
  onChange,
  loading,
  failed,
  onRetry,
}: {
  projects: { id: string; name: string; archived_at?: string | null }[]
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
        icon={<CloudOff />}
        title="Couldn’t load the projects"
        action={
          <Button size="sm" variant="secondary" onClick={onRetry}>
            Try again
          </Button>
        }
      />
    )
  }
  return (
    <ul
      id="agent-project_ids"
      tabIndex={-1}
      aria-label="Projects the agent serves"
      className="flex max-h-56 flex-col overflow-y-auto rounded-lg border py-1 outline-offset-2"
    >
      {projects.map((project) => (
        <li key={project.id} className="px-3 py-1.5">
          <Field inline label={project.name}>
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
