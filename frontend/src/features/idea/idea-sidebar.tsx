import {
  ChevronDown,
  Circle,
  CircleCheck,
  CircleDashed,
  Lock,
  LockOpen,
  Pencil,
  UserMinus,
  UserPlus,
  UserRoundPen,
  X,
} from 'lucide-react'
import {
  useEffect,
  useId,
  useRef,
  useState,
  type FocusEvent,
  type KeyboardEvent,
  type ReactNode,
} from 'react'

import { useIdeaAiRuns } from '@/api/ai'
import { describeError } from '@/api/errors'
import {
  useRemoveEvaluator,
  useSetEvaluationClosed,
  useSetIdeaOwner,
  useUpdateIdea,
  useVolunteerAsOwner,
} from '@/api/ideas'
import { useProjectTags } from '@/api/projects'
import type { AiRun, IdeaEvaluator } from '@/api/types'
import { AiBadge } from '@/components/ui/ai-badge'
import { Avatar } from '@/components/ui/avatar'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Field } from '@/components/ui/field'
import { ProgressTicks } from '@/components/ui/progress-ticks'
import { RelativeTime } from '@/components/ui/relative-time'
import { Spinner } from '@/components/ui/spinner'
import { StatusBadge } from '@/components/ui/status-badge'
import { TagInput } from '@/components/ui/tag-input'
import { WithTooltip } from '@/components/ui/tooltip'
import { isActiveRun } from '@/features/ai/ai-copy'
import { showRun } from '@/features/ai/idea-ai'
import { SubmissionPanel } from '@/features/moderation/idea-submission'
import { formatDateTime } from '@/lib/dates'
import { focusWhenRendered } from '@/lib/focus'
import { SHORTCUTS } from '@/lib/shortcuts'
import { requestResearchFocus } from '@/features/research/research-focus'
import { cn } from '@/lib/utils'

import { DueDateField } from './due-date-field'
import { useIdeaPage } from './idea-context'
import { primaryAction } from './primary-action'
import { ScorePanel } from './score-panel'

/**
 * The right-hand column (and the phone "Details" sheet): status, owner,
 * evaluators with their due date, the score, tags. Every control is shown
 * only when the API's `permissions` allow it.
 */
export function IdeaProperties({ className }: { className?: string }) {
  const { idea, ideaKey } = useIdeaPage()
  return (
    <div className={cn('flex flex-col gap-6', className)}>
      <dl className="grid grid-cols-[4rem_minmax(0,1fr)] items-center gap-x-3 gap-y-1.5 text-sm">
        <PropertyRow label="Status">
          <StatusField />
        </PropertyRow>
        <PropertyRow label="Owner">
          <OwnerField />
        </PropertyRow>
      </dl>
      <EvaluatorsSection />
      <ScorePanel />
      <TagsSection />
      <SubmissionPanel idea={idea} ideaKey={ideaKey} />
    </div>
  )
}

function PropertyRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <dt className="text-sm text-muted">{label}</dt>
      <dd className="flex min-h-8 min-w-0 items-center">{children}</dd>
    </>
  )
}

function StatusField() {
  const { idea, openDialog } = useIdeaPage()
  const badge = (
    <StatusBadge
      status={idea.status}
      resolution={idea.resolution}
      label={idea.status_label}
      variant="plain"
    />
  )
  if (!idea.permissions.can_change_status) return badge
  return (
    <WithTooltip content="Change status" shortcut={SHORTCUTS.changeStatus.keys}>
      <Button
        variant="ghost"
        size="sm"
        className="-ml-2 max-w-full"
        aria-label={`Status: ${idea.status_label}. Change status`}
        onClick={() => openDialog('status')}
      >
        {badge}
        <ChevronDown aria-hidden="true" className="text-muted" />
      </Button>
    </WithTooltip>
  )
}

function OwnerField() {
  const { idea, ideaKey, me, openDialog } = useIdeaPage()
  const setOwner = useSetIdeaOwner(ideaKey)
  const volunteer = useVolunteerAsOwner(ideaKey)
  const { permissions } = idea
  const owner = idea.owner

  if (!owner) {
    if (permissions.can_assign_owner) {
      // Like the owned case: the value is the control.
      return (
        <WithTooltip content="Assign owner" shortcut={SHORTCUTS.assignOwner.keys}>
          <Button
            variant="ghost"
            size="sm"
            className="-ml-2 font-normal text-muted"
            aria-label="Owner: none. Assign owner"
            onClick={() => openDialog('owner')}
          >
            <UserRoundPen />
            No owner
            <ChevronDown aria-hidden="true" />
          </Button>
        </WithTooltip>
      )
    }
    // "I'll own this" is usually the page's primary action already (header, phone bar).
    const offerHere = permissions.can_volunteer && primaryAction(idea, me.id)?.kind !== 'volunteer'
    return (
      <div className="flex flex-wrap items-center gap-1">
        <span className="text-muted">No owner</span>
        {offerHere && (
          <Button variant="ghost" size="sm" onClick={() => volunteer.mutate({})}>
            I’ll own this
          </Button>
        )}
      </div>
    )
  }

  const isMe = owner.id === me.id
  const person = (
    <span className="flex min-w-0 items-center gap-2">
      <Avatar name={owner.display_name} src={owner.avatar_url} size="xs" decorative />
      <span className="truncate text-primary">{owner.display_name}</span>
    </span>
  )
  const canStepDown = isMe && permissions.can_release_owner
  if (!permissions.can_assign_owner && !canStepDown) return person

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="sm"
          className="-ml-2 max-w-full font-normal"
          aria-label={`Owner: ${owner.display_name}${isMe ? ' (you)' : ''}. Change owner`}
        >
          {person}
          <ChevronDown aria-hidden="true" className="text-muted" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start">
        {permissions.can_assign_owner && (
          <DropdownMenuItem onSelect={() => openDialog('owner')}>
            <UserRoundPen /> Change owner…
          </DropdownMenuItem>
        )}
        {canStepDown ? (
          <DropdownMenuItem onSelect={() => setOwner.mutate({ owner: null })}>
            <UserMinus /> Step down as owner
          </DropdownMenuItem>
        ) : (
          permissions.can_assign_owner && (
            <DropdownMenuItem onSelect={() => setOwner.mutate({ owner: null })}>
              <UserMinus /> Remove owner
            </DropdownMenuItem>
          )
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

function EvaluatorsSection() {
  const { idea, ideaKey, me, project, openDialog, setTab } = useIdeaPage()
  // Phase 6: an AI evaluator's row says while its run is working (no score data).
  const aiRuns = useIdeaAiRuns(ideaKey).data?.items
  const activeAiRun = (userId: string) =>
    aiRuns?.find(
      (run) =>
        run.kind === 'evaluate' &&
        run.agent.user_id === userId &&
        (run.status === 'queued' || run.status === 'running'),
    )
  const remove = useRemoveEvaluator(ideaKey)
  const setClosed = useSetEvaluationClosed(ideaKey)
  const { permissions } = idea
  const { submitted, total } = idea.evaluator_progress
  const evaluationClosed = idea.evaluation_closed_at !== null && idea.status !== 'closed'
  const headingId = useId()
  const sectionRef = useRef<HTMLElement>(null)
  const inviteRef = useRef<HTMLButtonElement>(null)
  // An AI evaluator's progress button goes when its run ends: if it had focus, focus
  // "Invite evaluators" (or the AI menu, where agents are asked) rather than <body>.
  const runStateHadFocus = useRef(false)
  const activeRunIds = (aiRuns ?? [])
    .filter((run) => run.kind === 'evaluate' && isActiveRun(run))
    .map((run) => run.id)
    .join()
  useEffect(() => {
    if (!runStateHadFocus.current) return
    const active = document.activeElement
    if (active && active !== document.body && active.isConnected) return
    runStateHadFocus.current = false
    focusWhenRendered(
      () =>
        inviteRef.current ?? document.querySelector<HTMLElement>('button[aria-label="AI actions"]'),
      { force: true },
    )
  }, [activeRunIds])
  // "Close evaluation" and "Reopen" replace each other: keep focus on the one shown.
  const toggleRef = useRef<HTMLButtonElement>(null)
  const toggleHadFocus = useRef(false)
  useEffect(() => {
    if (!toggleHadFocus.current) return
    toggleHadFocus.current = false
    toggleRef.current?.focus()
  }, [evaluationClosed])
  const toggleClosed = (closed: boolean) => {
    toggleHadFocus.current = true
    setClosed.mutate({ closed })
  }
  const removeEvaluator = (evaluator: IdeaEvaluator, button: HTMLElement) => {
    // The row goes at once (Undo in the toast): focus the next remove button, else
    // the previous one, else "Invite evaluators", rather than losing it.
    const buttons = [
      ...(button.closest('ul')?.querySelectorAll<HTMLElement>('[data-remove-evaluator]') ?? []),
    ]
    const index = buttons.indexOf(button)
    ;(buttons[index + 1] ?? buttons[index - 1] ?? inviteRef.current)?.focus()
    remove(evaluator.user)
  }

  return (
    <section ref={sectionRef} aria-labelledby={headingId} className="flex flex-col gap-2">
      <div className="flex min-h-7 items-center justify-between gap-2">
        <h2 id={headingId} className="text-sm font-medium text-primary">
          Evaluators
        </h2>
        {total > 0 && <ProgressTicks done={submitted} total={total} />}
      </div>

      {total === 0 ? (
        <p className="text-sm text-muted">
          {permissions.can_invite_evaluators
            ? 'Invite 2–4 people to evaluate this idea.'
            : 'Nobody has been asked to evaluate this idea yet.'}
        </p>
      ) : (
        <ul aria-label="Evaluators" className="-mx-2 flex flex-col">
          {idea.evaluators.map((evaluator) => {
            const isMe = evaluator.user.id === me.id
            // Contract §3.5: others only, and never someone who has submitted.
            const removable =
              permissions.can_remove_evaluators && !isMe && evaluator.state !== 'submitted'
            return (
              <li
                key={evaluator.user.id}
                className="group relative flex min-h-9 items-center gap-2 rounded-md px-2 transition-colors hover:bg-subtle"
              >
                <Avatar
                  name={evaluator.user.display_name}
                  src={evaluator.user.avatar_url}
                  isAgent={evaluator.is_ai}
                  // The "AI" pill after the name marks it: one marker per row.
                  agentBadge={false}
                  size="sm"
                  decorative
                />
                <span className="flex min-w-0 flex-1 items-center gap-1.5">
                  <span className="min-w-0 truncate text-sm text-primary">
                    {evaluator.user.display_name}
                    {isMe && <span className="text-muted"> (you)</span>}
                  </span>
                  {evaluator.is_ai && <AiBadge />}
                </span>
                {evaluator.is_ai && activeAiRun(evaluator.user.id) ? (
                  <AiRunState
                    run={activeAiRun(evaluator.user.id)}
                    onShow={(runId) => showRun(runId, setTab)}
                    onFocusChange={(focused) => {
                      runStateHadFocus.current = focused
                    }}
                  />
                ) : (
                  <EvaluatorState evaluator={evaluator} own={isMe} />
                )}
                {removable && (
                  <WithTooltip content="Remove evaluator">
                    <Button
                      data-remove-evaluator
                      variant="ghost"
                      size="icon-sm"
                      aria-label={`Remove ${evaluator.user.display_name} as evaluator`}
                      className={cn(
                        // Over the state tick with a mouse (appears on hover or focus); beside it on touch.
                        'absolute right-1 bg-subtle opacity-0 group-hover:opacity-100 focus-visible:opacity-100',
                        'pointer-coarse:static pointer-coarse:-mr-1 pointer-coarse:bg-transparent pointer-coarse:opacity-100',
                      )}
                      onClick={(event) => removeEvaluator(evaluator, event.currentTarget)}
                    >
                      <X />
                    </Button>
                  </WithTooltip>
                )}
              </li>
            )
          })}
        </ul>
      )}

      {permissions.can_invite_evaluators &&
        // Phase 8: the first invite waits for the research checklist. Admins keep the
        // button (the 409's dialog offers "Invite anyway"); owners are told why.
        (permissions.invite_blocked_by_research && !project?.permissions.can_manage ? (
          <p className="text-sm text-muted">
            Finish the research checklist before inviting evaluators.{' '}
            <button
              type="button"
              className="font-medium text-accent underline-offset-4 hover:underline"
              onClick={() => {
                requestResearchFocus(ideaKey)
                setTab('overview')
              }}
            >
              Open research
            </button>
          </p>
        ) : (
          <>
            <Button
              ref={inviteRef}
              variant="ghost"
              size="sm"
              className="-ml-2 self-start text-secondary"
              aria-describedby={
                permissions.invite_blocked_by_research ? 'invite-research-note' : undefined
              }
              onClick={() => openDialog('invite')}
            >
              <UserPlus />
              Invite evaluators
            </Button>
            {permissions.invite_blocked_by_research && (
              <p id="invite-research-note" className="-mt-1 text-xs text-muted">
                Finish the research checklist first (admins can invite anyway).
              </p>
            )}
          </>
        ))}

      {(total > 0 || idea.evaluation_due_at) && (
        <dl className="grid grid-cols-[4rem_minmax(0,1fr)] items-center gap-x-3 text-sm">
          <dt className="text-muted">Due</dt>
          <dd className="flex min-h-8 min-w-0 items-center">
            <DueDateField />
          </dd>
        </dl>
      )}

      {idea.status === 'closed' ? (
        total > 0 && (
          <p className="flex items-center gap-2 text-sm text-muted">
            <Lock aria-hidden="true" className="size-3.5 shrink-0" />
            Evaluation ended when the idea was closed.
          </p>
        )
      ) : evaluationClosed ? (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-md bg-background px-3 py-2 text-sm">
          <span className="flex items-center gap-2 text-secondary">
            <Lock aria-hidden="true" className="size-3.5 shrink-0 text-muted" />
            <span>
              Evaluation closed{' '}
              {idea.evaluation_closed_at && <RelativeTime date={idea.evaluation_closed_at} />}
            </span>
          </span>
          {permissions.can_close_evaluation && (
            <Button
              ref={toggleRef}
              variant="ghost"
              size="sm"
              className="-mr-1"
              onClick={() => toggleClosed(false)}
            >
              <LockOpen />
              Reopen
            </Button>
          )}
        </div>
      ) : (
        permissions.can_close_evaluation &&
        total > 0 && (
          <Button
            ref={toggleRef}
            variant="ghost"
            size="sm"
            className="-ml-2 self-start text-secondary"
            onClick={() => toggleClosed(true)}
          >
            <Lock />
            Close evaluation
          </Button>
        )
      )}
    </section>
  )
}

const STATE = {
  submitted: { Icon: CircleCheck, className: 'text-success', label: 'Submitted' },
  draft: { Icon: CircleDashed, className: 'text-warning', label: 'Draft saved (only you see it)' },
  invited: { Icon: Circle, className: 'text-control', label: 'Not submitted yet' },
} as const

/** An AI evaluator whose run is on: a spinner that takes you to the run's card. */
function AiRunState({
  run,
  onShow,
  onFocusChange,
}: {
  run: AiRun | undefined
  onShow: (runId: string) => void
  /** Focus came or went (a removed button blurs to nothing: that stays "had focus"). */
  onFocusChange: (focused: boolean) => void
}) {
  if (!run) return null
  const label = run.status === 'queued' ? 'AI run waiting to start' : 'AI run in progress'
  return (
    <WithTooltip content={`${label}: view progress`}>
      <Button
        variant="ghost"
        size="icon-sm"
        className="-mr-1 text-accent"
        data-ai-run-state={run.id}
        aria-label={`${label}. View progress`}
        onClick={() => onShow(run.id)}
        onFocus={() => onFocusChange(true)}
        onBlur={(event) => {
          if (event.relatedTarget) onFocusChange(false)
        }}
      >
        <Spinner className="size-3.5" />
      </Button>
    </WithTooltip>
  )
}

/** A tick per evaluator: submitted ✓, your own draft, or not yet — icon plus accessible text. */
function EvaluatorState({ evaluator, own }: { evaluator: IdeaEvaluator; own: boolean }) {
  // Drafts are private: the API reports others' drafts as `invited`.
  const state = evaluator.state === 'draft' && !own ? 'invited' : evaluator.state
  const { Icon, className, label } = STATE[state]
  const detail =
    state === 'submitted' && evaluator.submitted_at
      ? `Submitted ${formatDateTime(evaluator.submitted_at)}`
      : label
  return (
    <WithTooltip content={detail}>
      <span role="img" aria-label={label} className={cn('inline-flex shrink-0', className)}>
        <Icon aria-hidden="true" className="size-4" />
      </span>
    </WithTooltip>
  )
}

function TagsSection() {
  const { idea, ideaKey } = useIdeaPage()
  const update = useUpdateIdea(ideaKey)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)
  const [wantSuggestions, setWantSuggestions] = useState(false)
  const suggestions = useProjectTags(wantSuggestions ? idea.project.slug : undefined)
  const canEdit = idea.permissions.can_edit
  const sectionRef = useRef<HTMLElement>(null)
  const headingId = useId()
  // Guards against a second commit from the blur that follows closing.
  const active = useRef(false)
  // Where focus goes once the editor opens or closes.
  const pendingFocus = useRef<'input' | 'edit' | null>(null)

  useEffect(() => {
    const target = pendingFocus.current
    if (!target) return
    pendingFocus.current = null
    const selector = target === 'input' ? 'input' : '[data-tags-edit]'
    sectionRef.current?.querySelector<HTMLElement>(selector)?.focus()
  }, [editing])

  const start = () => {
    active.current = true
    setDraft(idea.tags)
    setError(null)
    setEditing(true)
    pendingFocus.current = 'input'
  }
  const close = () => {
    active.current = false
    setEditing(false)
    pendingFocus.current = 'edit'
  }
  const commit = () => {
    if (!active.current) return
    close()
    const same =
      draft.length === idea.tags.length &&
      draft.every((tag) => idea.tags.some((t) => t.toLowerCase() === tag.toLowerCase()))
    if (same) return
    update.mutate(
      { tags: draft },
      {
        onError: (failure) => {
          const { title, description } = describeError(failure)
          setError(description ? `${title}. ${description}` : title)
          active.current = true
          setEditing(true)
        },
      },
    )
  }
  const onBlur = (event: FocusEvent<HTMLDivElement>) => {
    const next = event.relatedTarget
    if (next instanceof Node && event.currentTarget.contains(next)) return
    commit()
  }
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== 'Escape') return
    // Esc first closes the suggestions.
    const target = event.target instanceof Element ? event.target : null
    if (target?.closest('[role="combobox"][aria-expanded="true"]')) return
    event.preventDefault()
    close()
  }

  return (
    <section ref={sectionRef} aria-labelledby={headingId} className="flex flex-col gap-2">
      <div className="flex min-h-7 items-center justify-between gap-2">
        <h2 id={headingId} className="text-sm font-medium text-primary">
          Tags
        </h2>
        {canEdit && !editing && idea.tags.length > 0 && (
          <WithTooltip content="Edit tags">
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label="Edit tags"
              data-tags-edit=""
              onClick={start}
            >
              <Pencil />
            </Button>
          </WithTooltip>
        )}
      </div>
      {editing ? (
        // Saves when focus leaves the editor; Esc cancels.
        // eslint-disable-next-line jsx-a11y/no-static-element-interactions
        <div className="flex flex-col gap-2" onBlur={onBlur} onKeyDown={onKeyDown}>
          <Field label="Tags" hideLabel error={error} description="Enter or comma adds a tag.">
            <TagInput
              value={draft}
              onValueChange={setDraft}
              suggestions={suggestions.data?.map((tag) => tag.name)}
              onFirstFocus={() => setWantSuggestions(true)}
              placeholder="Add a tag…"
            />
          </Field>
          <div className="flex gap-2">
            <Button size="sm" variant="primary" onClick={commit}>
              Done
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onMouseDown={(event) => event.preventDefault()}
              onClick={close}
            >
              Cancel
            </Button>
          </div>
        </div>
      ) : idea.tags.length > 0 ? (
        <ul aria-label="Tags" className="flex flex-wrap gap-1.5">
          {idea.tags.map((tag) => (
            <li key={tag}>
              <Badge className="h-6 px-2 text-sm font-normal">{tag}</Badge>
            </li>
          ))}
        </ul>
      ) : canEdit ? (
        <Button
          variant="ghost"
          size="sm"
          className="-ml-2 self-start text-muted"
          data-tags-edit=""
          onClick={start}
        >
          Add tags
        </Button>
      ) : (
        <p className="text-sm text-muted">No tags</p>
      )}
    </section>
  )
}
