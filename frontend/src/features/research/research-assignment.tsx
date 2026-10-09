import { useQueryClient } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import {
  CalendarClock,
  Check,
  ChevronDown,
  TriangleAlert,
  Undo2,
  UserRoundMinus,
  UserRoundPen,
} from 'lucide-react'
import { useRef, useState, type ReactNode } from 'react'

import { describeError } from '@/api/errors'
import { useChangeIdeaStatus } from '@/api/ideas'
import {
  forgetIdea,
  useIdeaResearch,
  useRemoveResearcher,
  useSetResearchAssignment,
} from '@/api/research'
import type {
  IdeaStatus,
  ResearchAssignment,
  ResearchStep,
  UserRef,
  UserSearchResult,
} from '@/api/types'
import { Avatar } from '@/components/ui/avatar'
import { Button } from '@/components/ui/button'
import { Callout } from '@/components/ui/callout'
import { CommandGroup, CommandItem } from '@/components/ui/command'
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
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Field } from '@/components/ui/field'
import { ariaKeys, ButtonShortcut } from '@/components/ui/kbd'
import { toast } from '@/components/ui/toaster'
import {
  dateInputInDays,
  fromDateInput,
  latestDueInput,
  pickerMin,
  toDateInput,
} from '@/features/idea/due-date'
import { useIdeaPage } from '@/features/idea/idea-context'
import { PeopleList } from '@/features/idea/people-list'
import { dueOn } from '@/features/notifications/notification-text'
import { formatDate } from '@/lib/dates'
import { focusWhenRendered } from '@/lib/focus'
import { SHORTCUTS, useShortcut } from '@/lib/shortcuts'
import { gatedStatuses } from '@/lib/status'
import { cn } from '@/lib/utils'

/*
 * Phase 8b (contract-phase8b §10): who does an idea's research and by when.
 * "Research: Bob Chen · due Fri 9 Oct" in the sidebar and the Research panel;
 * owners and admins change it (a person picker over everyone active, people
 * outside the project marked, and a due date); the researcher hands it back.
 * Removing the researcher is choosing the owner in Change (UX review S2: one path).
 * Past Research nobody new is asked (adversarial check L2: they could only read it),
 * so Change becomes Remove there, and goes when there is nobody to remove.
 */

/** Where focus goes when the control that was used is gone (WCAG 2.4.3): Change, else the panel's heading. */
export const RESEARCHER_CHANGE_ID = 'researcher-change'
export const RESEARCH_HEADING_TOGGLE_ID = 'research-heading-toggle'
const researchFocusFallback = () =>
  document.getElementById(RESEARCHER_CHANGE_ID) ??
  document.getElementById(RESEARCH_HEADING_TOGGLE_ID)

const QUICK_PICKS = [
  { days: 3, label: 'In 3 days' },
  { days: 7, label: 'In a week' },
  { days: 14, label: 'In 2 weeks' },
] as const

/** What a guest researcher sees, and what an internal non-member gains (review S2). */
export const OUTSIDER_LINES = {
  private:
    'They’ll see this idea, its comments and activity and its research checklist, not scores, evaluations or the proposal.',
  internal: 'They’ll be able to answer the checklist and comment.',
} as const

/** Past Research (a status after it, not closed): nobody new is asked to research it. */
export function researchFinished(step: ResearchStep, status: IdeaStatus): boolean {
  return gatedStatuses(step).includes(status)
}

/**
 * The idea's assignment as the page knows it: the Research panel's query (shared
 * cache), else what the idea itself carries while that loads. `canAssign` is false
 * past Research when only the owner does it (nothing left to change: L2), and
 * `finished` turns Change into Remove.
 */
export function useAssignment() {
  const { ideaKey, idea, me, researchStep } = useIdeaPage()
  const research = useIdeaResearch(ideaKey, { enabled: researchStep !== 'off' })
  const data = research.data
  const assignment: ResearchAssignment = data?.assignment ?? {
    researcher: idea.researcher,
    researcher_in_project: true,
    assigned_at: null,
    due_at: idea.research_due_at,
    overdue: false,
  }
  // The owner named explicitly: handing it back would hand it to themselves (UX m1).
  const ownerResearches =
    assignment.researcher !== null && assignment.researcher.id === idea.owner?.id
  const finished = researchFinished(researchStep, idea.status)
  // Past Research: someone to remove (an admin researching it hands it back instead).
  const someoneAsked =
    assignment.researcher !== null && !ownerResearches && assignment.researcher.id !== me.id
  return {
    assignment,
    finished,
    canAssign:
      (data?.permissions.can_assign ?? idea.permissions.can_assign_researcher) &&
      (!finished || someoneAsked),
    canAssignOutside:
      data?.permissions.can_assign_outside_researcher ??
      idea.permissions.can_assign_outside_researcher,
    canHandBack:
      (data?.permissions.can_hand_back ?? idea.permissions.can_hand_back_research) &&
      !ownerResearches,
  }
}

/** Someone outside the project does it, and it isn't you (you know: UX p2). */
function outsideResearcher(assignment: ResearchAssignment, meId: string): boolean {
  return (
    assignment.researcher !== null &&
    !assignment.researcher_in_project &&
    assignment.researcher.id !== meId
  )
}

/** "Bob Chen", "You", "Sven Lindqvist (owner)": who does the research, in words. */
export function researcherName(
  assignment: Pick<ResearchAssignment, 'researcher'>,
  owner: UserRef | null,
  meId: string,
): string {
  const person = assignment.researcher ?? owner
  if (!person) return 'The owner, once there is one'
  const you = person.id === meId
  const isOwner = owner !== null && person.id === owner.id
  if (you) return isOwner ? 'You (owner)' : 'You'
  return isOwner ? `${person.display_name} (owner)` : person.display_name
}

/** "due Fri 9 Oct", or "overdue, was due Fri 9 Oct" (warning tone, words not colour alone). */
export function ResearchDue({
  assignment,
  className,
}: {
  assignment: Pick<ResearchAssignment, 'due_at' | 'overdue'>
  className?: string
}) {
  if (!assignment.due_at) return null
  if (assignment.overdue) {
    return (
      // The warning tone wins over a muted line's colour: overdue is never grey.
      <span className={cn('inline-flex items-center gap-1', className, 'text-warning')}>
        <TriangleAlert aria-hidden="true" className="size-3.5 shrink-0" />
        overdue, was due {formatDate(assignment.due_at)}
      </span>
    )
  }
  return <span className={className}>{dueOn(assignment.due_at)}</span>
}

/** "Research: Bob Chen · Not in this project · due Fri 9 Oct" as one line of text. */
export function assignmentText(
  assignment: ResearchAssignment,
  owner: UserRef | null,
  meId: string,
): string {
  const parts = [`Research: ${researcherName(assignment, owner, meId)}`]
  if (outsideResearcher(assignment, meId)) parts.push('not in this project')
  if (assignment.due_at) {
    parts.push(
      assignment.overdue
        ? `overdue, was due ${formatDate(assignment.due_at)}`
        : dueOn(assignment.due_at),
    )
  }
  return parts.join(' · ')
}

/**
 * The sidebar's value (UX m2): the person who was asked, wrapping rather than cut
 * off; while the owner does it, a muted "Owner" (their name is in the row above), and
 * "No one yet" without an owner. The full sentence is the control's name.
 */
function ResearcherValue({ assignment }: { assignment: ResearchAssignment }) {
  const { idea, me } = useIdeaPage()
  const owner = idea.owner
  const person = assignment.researcher
  if (!person || person.id === owner?.id) {
    return <span className="text-muted">{owner ? 'Owner' : 'No one yet'}</span>
  }
  return (
    <span className="flex min-w-0 items-center gap-2">
      <Avatar name={person.display_name} src={person.avatar_url} size="xs" decorative />
      <span className="min-w-0 break-words text-primary">
        {person.id === me.id ? 'You' : person.display_name}
      </span>
    </span>
  )
}

/** "Not in this project · due Fri 9 Oct" under the name (nothing when there's nothing). */
function ResearcherFacts({ assignment }: { assignment: ResearchAssignment }) {
  const { me } = useIdeaPage()
  const outside = outsideResearcher(assignment, me.id)
  if (!outside && !assignment.due_at) return null
  return (
    <span className="flex flex-wrap items-center gap-x-1.5 pb-1 text-xs text-muted">
      {outside && <span>Not in this project</span>}
      {outside && assignment.due_at && <span aria-hidden="true">·</span>}
      <ResearchDue assignment={assignment} />
    </span>
  )
}

/**
 * The sidebar's "Research" value: the person, and for owners and admins Change (the
 * dialog); for the researcher, "Hand back"; both in a menu when you may do both. The
 * facts (outside the project, the due date) sit under it.
 */
export function ResearcherField() {
  const { idea, me, openDialog } = useIdeaPage()
  const { assignment, canAssign, canHandBack, finished } = useAssignment()
  const change = finished ? 'Remove the researcher' : 'Change researcher or due date'
  const ChangeIcon = finished ? UserRoundMinus : UserRoundPen
  const name = assignmentText(assignment, idea.owner, me.id)
  const value = <ResearcherValue assignment={assignment} />
  const trigger = (action: string, onClick?: () => void) => (
    <Button
      variant="ghost"
      size="sm"
      // Long names wrap (two lines at most in practice) instead of "Sven Lindqvist (o…".
      className="-ml-2 h-auto min-h-7 max-w-full py-1 text-left font-normal whitespace-normal"
      aria-label={`${name}. ${action}`}
      onClick={onClick}
    >
      {value}
      <ChevronDown aria-hidden="true" className="text-muted" />
    </Button>
  )
  return (
    <span className="flex w-full min-w-0 flex-col items-start">
      {canAssign && canHandBack ? (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>{trigger('Change or hand back')}</DropdownMenuTrigger>
          <DropdownMenuContent align="start">
            <DropdownMenuItem onSelect={() => openDialog('researcher')}>
              <ChangeIcon /> {change}…
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={() => openDialog('hand-back')}>
              <Undo2 /> Hand back the research…
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      ) : canAssign ? (
        trigger(change, () => openDialog('researcher'))
      ) : canHandBack ? (
        trigger('Hand back the research', () => openDialog('hand-back'))
      ) : (
        <span className="flex min-h-8 items-center">{value}</span>
      )}
      <ResearcherFacts assignment={assignment} />
    </span>
  )
}

/**
 * The Research panel's line: "Research: Bob Chen · due Fri 9 Oct" with Change for
 * owners and admins and Hand back for the researcher (phones reach it here; the
 * sidebar folds into Details).
 */
export function ResearcherLine() {
  const { me, idea, openDialog } = useIdeaPage()
  const { assignment, canAssign, canHandBack, finished } = useAssignment()
  const person = assignment.researcher ?? idea.owner
  const outside = outsideResearcher(assignment, me.id)
  return (
    <div
      className="flex flex-wrap items-center gap-x-3 gap-y-2 text-sm"
      data-testid="researcher-line"
    >
      <p className="flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-1 text-secondary">
        <span className="text-muted">Research:</span>
        {person && (
          <Avatar name={person.display_name} src={person.avatar_url} size="xs" decorative />
        )}
        <span className="font-medium text-primary">
          {researcherName(assignment, idea.owner, me.id)}
        </span>
        {outside && (
          <>
            <span aria-hidden="true" className="text-muted">
              ·
            </span>
            <span className="text-muted">not in this project</span>
          </>
        )}
        {assignment.due_at && (
          <>
            <span aria-hidden="true" className="text-muted">
              ·
            </span>
            <ResearchDue assignment={assignment} className="text-muted" />
          </>
        )}
      </p>
      {(canAssign || canHandBack) && (
        <span className="flex items-center gap-1">
          {canAssign && (
            <Button
              id={RESEARCHER_CHANGE_ID}
              size="sm"
              variant="ghost"
              className="text-secondary"
              aria-label={finished ? 'Remove the researcher' : 'Change researcher or due date'}
              onClick={() => openDialog('researcher')}
            >
              {finished ? (
                <>
                  <UserRoundMinus /> Remove
                </>
              ) : (
                <>
                  <CalendarClock /> Change
                </>
              )}
            </Button>
          )}
          {canHandBack && (
            <Button
              size="sm"
              variant="ghost"
              className="text-secondary"
              onClick={() => openDialog('hand-back')}
            >
              <Undo2 /> Hand back
            </Button>
          )}
        </span>
      )}
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* Change (and "Start research")                                       */
/* ------------------------------------------------------------------ */

type Choice =
  /** Nobody assigned: the owner does it. */
  { kind: 'owner' } | { kind: 'person'; person: UserRef; inProject: boolean }

/**
 * "Change researcher or due date" and the "Start research" dialog (the primary
 * action in the status before Research: lead decision on Phase 8 review S3).
 */
export function ResearchAssignmentDialog({
  open,
  onOpenChange,
  mode,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  mode: 'change' | 'start'
}) {
  const { finished } = useAssignment()
  const removing = mode === 'change' && finished
  const removed = useRef(false)
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      {removing ? (
        <DialogContent
          size="sm"
          role="alertdialog"
          onCloseAutoFocus={() => {
            // Remove went with the researcher: focus the Research heading (WCAG 2.4.3).
            if (!removed.current) return
            removed.current = false
            focusWhenRendered(researchFocusFallback)
          }}
        >
          {open && (
            <RemoveResearcherForm
              onDone={(done) => {
                removed.current = done
                onOpenChange(false)
              }}
            />
          )}
        </DialogContent>
      ) : (
        <DialogContent size="md" mobile="fullscreen" className="overflow-hidden">
          {open && <AssignmentForm mode={mode} onDone={() => onOpenChange(false)} />}
        </DialogContent>
      )}
    </Dialog>
  )
}

/**
 * Past Research (adversarial check L2): nobody new is asked, so Change only removes the
 * researcher (the owner does it again; the answers and the due date stay).
 */
function RemoveResearcherForm({ onDone }: { onDone: (removed: boolean) => void }) {
  const { idea, ideaKey, me, project, statusLabel } = useIdeaPage()
  const { assignment } = useAssignment()
  const remove = useRemoveResearcher(ideaKey)
  const person = assignment.researcher
  if (!person) return null
  const name = person.id === me.id ? 'You' : person.display_name
  const owner = idea.owner
  const ownerDoes = !owner
    ? 'The idea’s owner does'
    : owner.id === me.id
      ? 'You (the owner) do'
      : `${owner.display_name} (the owner) does`
  const loses =
    !assignment.researcher_in_project &&
    (project?.visibility ?? 'private') === 'private' &&
    person.id !== me.id
  const confirm = () =>
    remove.mutate(
      {},
      {
        onSuccess: () => {
          onDone(true)
          toast.success(
            owner
              ? `${owner.id === me.id ? 'You (owner)' : `${owner.display_name} (owner)`} will do the research`
              : 'The owner will do the research',
          )
        },
      },
    )
  return (
    <>
      <DialogHeader>
        <DialogTitle>
          Remove {person.id === me.id ? 'yourself' : person.display_name} as researcher?
        </DialogTitle>
        <DialogDescription className="truncate">
          {idea.key} · {idea.title}
        </DialogDescription>
      </DialogHeader>
      <DialogBody className="flex flex-col gap-2 text-sm text-secondary">
        <p>
          {idea.key} is in {statusLabel(idea.status)}, past Research, so nobody new can be asked to
          research it.
        </p>
        <p>
          {ownerDoes} the research again. {name === 'You' ? 'Your' : `${name}’s`} answers stay.
          {loses && ` ${person.display_name} will no longer see ${idea.key}.`}
        </p>
      </DialogBody>
      <DialogFooter className="pt-5">
        <Button variant="ghost" onClick={() => onDone(false)}>
          Cancel
        </Button>
        <Button variant="primary" loading={remove.isPending} onClick={confirm}>
          Remove
        </Button>
      </DialogFooter>
    </>
  )
}

/**
 * Under the date field: the day in words (the native field's format follows the
 * browser: UX p4), what a date does, and an overdue date said as such (UX M1).
 */
function dueDescription(due: string, currentDue: string, assignment: ResearchAssignment): string {
  if (!due) return 'Optional. No due date: no reminders, and it isn’t shown as overdue.'
  if (due === currentDue && assignment.overdue && assignment.due_at) {
    return `Was due ${formatDate(assignment.due_at)} (overdue). Pick a new date, or keep it.`
  }
  const day = fromDateInput(due)
  const reminders = 'They’re reminded 2 days before and on the day while a required item is open.'
  return day ? `${formatDate(day)}. ${reminders}` : reminders
}

function initialChoice(assignment: ResearchAssignment, owner: UserRef | null): Choice {
  const researcher = assignment.researcher
  if (!researcher || owner?.id === researcher.id) return { kind: 'owner' }
  return { kind: 'person', person: researcher, inProject: assignment.researcher_in_project }
}

function AssignmentForm({ mode, onDone }: { mode: 'change' | 'start'; onDone: () => void }) {
  const { idea, ideaKey, me, project, statusLabel } = useIdeaPage()
  const { assignment, canAssignOutside } = useAssignment()
  const assign = useSetResearchAssignment(ideaKey)
  const changeStatus = useChangeIdeaStatus(ideaKey)
  const owner = idea.owner
  const [choice, setChoice] = useState<Choice>(() => initialChoice(assignment, owner))
  const currentDue = toDateInput(assignment.due_at)
  const [due, setDue] = useState(currentDue)
  const [error, setError] = useState<{ title: string; description?: string } | null>(null)
  const pending = assign.isPending || changeStatus.isPending

  // The owner explicitly assigned (the seed's GREEN-6) stays explicit when kept.
  const explicitOwner =
    assignment.researcher !== null && owner !== null && assignment.researcher.id === owner.id
  const researcherId = choice.kind === 'person' ? choice.person.id : explicitOwner ? owner.id : null
  const currentId = assignment.researcher?.id ?? null
  // The day kept as it was: send the stored moment back unchanged (an overdue one too).
  const dueAt = due === currentDue ? assignment.due_at : due ? fromDateInput(due) : null
  const changed = researcherId !== currentId || due !== currentDue
  const outsider = choice.kind === 'person' && !choice.inProject
  const visibility = project?.visibility ?? 'private'
  // A guest researcher chosen away loses the idea: say so before Save (S2: removing is
  // choosing someone else here).
  const losing =
    assignment.researcher !== null &&
    !assignment.researcher_in_project &&
    visibility === 'private' &&
    researcherId !== currentId &&
    assignment.researcher.id !== me.id
      ? assignment.researcher
      : null
  // An outsider an admin asked, seen by someone whose picker lists only the project's
  // people (the owner of a private idea): a row of its own, so they can keep them (and
  // change only the due date) and the highlight can start on them.
  const keptOutsider =
    !canAssignOutside &&
    assignment.researcher !== null &&
    !assignment.researcher_in_project &&
    assignment.researcher.id !== owner?.id
      ? assignment.researcher
      : null
  const keptChosen =
    keptOutsider !== null && choice.kind === 'person' && choice.person.id === keptOutsider.id

  const finish = (message: string, description?: string) => {
    onDone()
    toast.success(message, description ? { description } : undefined)
  }

  const submit = () => {
    if (pending) return
    setError(null)
    const who =
      choice.kind === 'person'
        ? choice.person.id === me.id
          ? 'You'
          : choice.person.display_name
        : owner?.id === me.id
          ? 'You (owner)'
          : owner
            ? `${owner.display_name} (owner)`
            : 'The owner'
    const when = dueAt ? `Due ${formatDate(dueAt)}` : undefined
    const doer = choice.kind === 'person' ? choice.person : owner
    const doesIt = !doer
      ? 'The owner does the research'
      : doer.id === me.id
        ? 'You do the research'
        : `${doer.display_name} does the research`
    // The status change's own toast says where it went, with Undo; its second line says
    // who does the research and by when (UX m4).
    const move = () =>
      changeStatus.mutate(
        {
          status: 'research',
          toastDescription: [
            doesIt,
            dueAt
              ? `${Date.parse(dueAt) < Date.now() ? 'overdue, was due' : 'due'} ${formatDate(dueAt)}`
              : null,
          ]
            .filter(Boolean)
            .join(' · '),
        },
        {
          onSuccess: onDone,
          onError: (failure) => setError(describeError(failure)),
        },
      )
    if (!changed) {
      if (mode === 'start') move()
      else onDone()
      return
    }
    assign.mutate(
      { researcher_id: researcherId, due_at: dueAt },
      {
        onSuccess: () => {
          if (mode === 'start') move()
          else
            finish(
              researcherId === currentId
                ? 'Research due date saved'
                : `${who} will do the research`,
              when,
            )
        },
        onError: (failure) => setError(describeError(failure)),
      },
    )
  }

  useShortcut('submitForm', submit)

  const ownerRow = (
    <CommandGroup>
      <CommandItem
        value="research-owner"
        onSelect={() => setChoice({ kind: 'owner' })}
        className="h-auto min-h-11 py-1.5 sm:h-auto sm:min-h-10"
      >
        {owner ? (
          <Avatar name={owner.display_name} src={owner.avatar_url} size="sm" decorative />
        ) : (
          <span aria-hidden="true" className="size-6 shrink-0 rounded-full bg-subtle" />
        )}
        <span className="flex min-w-0 flex-1 flex-col">
          <span className="truncate">
            {owner
              ? owner.id === me.id
                ? 'You (owner)'
                : `${owner.display_name} (owner)`
              : 'The owner'}
            {choice.kind === 'owner' && <span className="sr-only">, chosen</span>}
          </span>
          <span className="truncate text-xs text-muted">
            {owner ? 'The idea’s owner does the research' : 'Whoever owns the idea does it'}
          </span>
        </span>
        <Check
          aria-hidden="true"
          className={cn('text-accent!', choice.kind === 'owner' ? 'opacity-100' : 'opacity-0')}
        />
      </CommandItem>
      {keptOutsider && (
        <CommandItem
          value="research-current"
          onSelect={() => setChoice({ kind: 'person', person: keptOutsider, inProject: false })}
          className="h-auto min-h-11 py-1.5 sm:h-auto sm:min-h-10"
        >
          <Avatar
            name={keptOutsider.display_name}
            src={keptOutsider.avatar_url}
            size="sm"
            decorative
          />
          <span className="flex min-w-0 flex-1 flex-col">
            <span className="truncate">
              {keptOutsider.display_name}
              {keptChosen && <span className="sr-only">, chosen</span>}
            </span>
            <span className="truncate text-xs text-muted">Not in this project</span>
          </span>
          <Check
            aria-hidden="true"
            className={cn('text-accent!', keptChosen ? 'opacity-100' : 'opacity-0')}
          />
        </CommandItem>
      )}
    </CommandGroup>
  )

  return (
    <form
      className="flex min-h-0 flex-1 flex-col"
      onSubmit={(event) => {
        event.preventDefault()
        submit()
      }}
    >
      <DialogHeader>
        <DialogTitle>{mode === 'start' ? 'Start research' : 'Who does the research'}</DialogTitle>
        <DialogDescription className="truncate">
          {idea.key} · {idea.title}
        </DialogDescription>
      </DialogHeader>
      <DialogBody className="flex flex-col gap-4">
        {mode === 'start' && (
          <p className="text-sm text-secondary">
            {idea.key} moves to {statusLabel('research')}. Whoever does the research answers the
            checklist; it’s in their My work.
          </p>
        )}
        {error && (
          <Callout tone="danger" role="alert" title={error.title}>
            {error.description}
          </Callout>
        )}
        <div className="flex flex-col gap-2">
          <p className="text-sm font-medium text-primary" id="researcher-picker-label">
            Researcher
          </p>
          <p className="text-sm text-secondary">
            Chosen:{' '}
            <span className="font-medium text-primary">
              {choice.kind === 'person'
                ? choice.person.id === me.id
                  ? 'You'
                  : choice.person.display_name
                : owner
                  ? owner.id === me.id
                    ? 'You (owner)'
                    : `${owner.display_name} (owner)`
                  : 'The owner'}
            </span>
            {outsider && <span className="text-muted"> · Not in this project</span>}
          </p>
          <div className="overflow-hidden rounded-lg border">
            <PeopleList
              projectSlug={idea.project.slug}
              selected={choice.kind === 'person' ? [choice.person.id] : []}
              meId={me.id}
              label="Researcher"
              placeholder={canAssignOutside ? 'Search everyone…' : 'Search the project’s people…'}
              includeNonMembers={canAssignOutside}
              // Anyone active may do the research, viewers and people outside the project too.
              ineligible={() => undefined}
              exclude={owner ? [owner.id] : []}
              before={ownerRow}
              beforeChosen={
                choice.kind === 'owner'
                  ? 'research-owner'
                  : keptChosen
                    ? 'research-current'
                    : undefined
              }
              listClassName="max-h-64"
              onSelect={(person: UserSearchResult) =>
                setChoice({
                  kind: 'person',
                  person: {
                    id: person.id,
                    display_name: person.display_name,
                    avatar_url: person.avatar_url,
                    initials: person.initials,
                  },
                  inProject: person.project_role !== null,
                })
              }
            />
          </div>
          {(outsider || losing) && (
            // One quiet note (UX p3): what the person chosen will see, and who stops seeing it.
            <Callout
              tone="neutral"
              role="status"
              title={
                outsider
                  ? visibility === 'internal'
                    ? OUTSIDER_LINES.internal
                    : OUTSIDER_LINES.private
                  : `${losing?.display_name ?? ''} will no longer see ${idea.key}.`
              }
            >
              {outsider && losing ? `${losing.display_name} will no longer see ${idea.key}.` : null}
            </Callout>
          )}
          {!outsider && !canAssignOutside && visibility === 'private' && (
            <p className="text-xs text-muted">
              Only a project admin can ask someone outside this project.
            </p>
          )}
        </div>
        <Field label="Research due date" description={dueDescription(due, currentDue, assignment)}>
          {/* "No due date" sits by the field: on a phone it never wraps onto a row alone. */}
          <div className="flex flex-wrap items-center gap-1.5">
            <DatePicker
              value={due}
              onValueChange={setDue}
              // An overdue date stays valid until it is changed (UX M1): a dialog that
              // keeps it still saves, and Start research still starts.
              min={pickerMin(currentDue)}
              max={latestDueInput()}
            />
            {due && (
              <Button type="button" size="sm" variant="ghost" onClick={() => setDue('')}>
                No due date
              </Button>
            )}
          </div>
        </Field>
        <div className="-mt-2 flex flex-wrap gap-1.5">
          {QUICK_PICKS.map((pick) => (
            <Button
              key={pick.days}
              type="button"
              size="sm"
              variant="outline"
              onClick={() => setDue(dateInputInDays(pick.days))}
            >
              {pick.label}
            </Button>
          ))}
        </div>
      </DialogBody>
      <DialogFooter>
        <Button type="button" variant="ghost" onClick={onDone}>
          Cancel
        </Button>
        <Button
          type="submit"
          variant="primary"
          loading={pending}
          aria-keyshortcuts={ariaKeys(SHORTCUTS.submitForm.keys)}
          className="max-sm:h-11"
        >
          {mode === 'start' ? 'Start research' : 'Save'}
          <ButtonShortcut keys={SHORTCUTS.submitForm.keys} />
        </Button>
      </DialogFooter>
    </form>
  )
}

/* ------------------------------------------------------------------ */
/* Hand back                                                           */
/* ------------------------------------------------------------------ */

/**
 * The researcher's "Hand back" (confirmed: a guest loses the idea with it). A guest
 * goes to My work afterwards; anyone else stays on the idea.
 */
export function HandBackDialog({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const { idea, ideaKey, guest } = useIdeaPage()
  const remove = useRemoveResearcher(ideaKey)
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const owner = idea.owner
  const handedBack = useRef(false)

  const confirm = () => {
    remove.mutate(
      { guest },
      {
        onSuccess: () => {
          handedBack.current = true
          onOpenChange(false)
          toast.success('You handed the research back', {
            description: owner
              ? `${owner.display_name} (the owner) does it again; your answers stay.`
              : 'Your answers stay.',
          })
          // A guest can't open the idea any more: off to My work, then nothing of it
          // stays cached (contract-phase8b §4.6).
          // Replacing the entry: Back doesn't lead to a page they can no longer open (UX p6).
          if (guest) {
            void navigate({ to: '/', replace: true }).then(() => forgetIdea(queryClient, ideaKey))
          }
        },
      },
    )
  }

  const body: ReactNode = guest
    ? `Your answers stay. You’ll no longer see ${idea.key}: only people in ${idea.project.name} can.`
    : owner
      ? `${owner.display_name} (the owner) does the research again. Your answers stay.`
      : 'The idea’s owner does the research again. Your answers stay.'

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        size="sm"
        role="alertdialog"
        onCloseAutoFocus={() => {
          // "Hand back" went with the handing back: Change (an admin), else the Research
          // heading, when focus would otherwise fall to the page (UX M3). A guest leaves
          // for My work, whose heading takes it.
          if (!handedBack.current || guest) return
          handedBack.current = false
          focusWhenRendered(researchFocusFallback)
        }}
      >
        <DialogHeader>
          <DialogTitle>Hand back the research of {idea.key}?</DialogTitle>
          <DialogDescription>{body}</DialogDescription>
        </DialogHeader>
        <DialogFooter className="pt-5">
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button variant="primary" loading={remove.isPending} onClick={confirm}>
            Hand back
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
