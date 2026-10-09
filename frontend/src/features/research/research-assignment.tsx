import { useQueryClient } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import {
  CalendarClock,
  Check,
  ChevronDown,
  TriangleAlert,
  Undo2,
  UserMinus,
  UserRoundPen,
} from 'lucide-react'
import { useState, type ReactNode } from 'react'

import { describeError } from '@/api/errors'
import { useChangeIdeaStatus } from '@/api/ideas'
import {
  forgetIdea,
  useIdeaResearch,
  useRemoveResearcher,
  useSetResearchAssignment,
} from '@/api/research'
import type { ResearchAssignment, UserRef, UserSearchResult } from '@/api/types'
import { offerUndo } from '@/api/undo'
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
  toDateInput,
  todayInput,
} from '@/features/idea/due-date'
import { useIdeaPage } from '@/features/idea/idea-context'
import { PeopleList } from '@/features/idea/people-list'
import { dueOn } from '@/features/notifications/notification-text'
import { formatDate } from '@/lib/dates'
import { SHORTCUTS, useShortcut } from '@/lib/shortcuts'
import { cn } from '@/lib/utils'

/*
 * Phase 8b (contract-phase8b §10): who does an idea's research and by when.
 * "Research: Bob Chen · due Fri 9 Oct" in the sidebar and the Research panel;
 * owners and admins change it (a person picker over everyone active, people
 * outside the project marked, and a due date); the researcher hands it back.
 */

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

/**
 * The idea's assignment as the page knows it: the Research panel's query (shared
 * cache), else what the idea itself carries while that loads.
 */
export function useAssignment() {
  const { ideaKey, idea, researchStep } = useIdeaPage()
  const research = useIdeaResearch(ideaKey, { enabled: researchStep !== 'off' })
  const data = research.data
  const assignment: ResearchAssignment = data?.assignment ?? {
    researcher: idea.researcher,
    researcher_in_project: true,
    assigned_at: null,
    due_at: idea.research_due_at,
    overdue: false,
  }
  return {
    assignment,
    canAssign: data?.permissions.can_assign ?? idea.permissions.can_assign_researcher,
    canAssignOutside:
      data?.permissions.can_assign_outside_researcher ??
      idea.permissions.can_assign_outside_researcher,
    canHandBack: data?.permissions.can_hand_back ?? idea.permissions.can_hand_back_research,
  }
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
  if (assignment.researcher && !assignment.researcher_in_project) parts.push('not in this project')
  if (assignment.due_at) {
    parts.push(
      assignment.overdue
        ? `overdue, was due ${formatDate(assignment.due_at)}`
        : dueOn(assignment.due_at),
    )
  }
  return parts.join(' · ')
}

/** The person (avatar and name): "Bob Chen", "You (owner)". */
function ResearcherPerson({ assignment }: { assignment: ResearchAssignment }) {
  const { idea, me } = useIdeaPage()
  const person = assignment.researcher ?? idea.owner
  return (
    <span className="flex min-w-0 items-center gap-2">
      {person && <Avatar name={person.display_name} src={person.avatar_url} size="xs" decorative />}
      <span className={cn('truncate', person ? 'text-primary' : 'text-muted')}>
        {researcherName(assignment, idea.owner, me.id)}
      </span>
    </span>
  )
}

/** "Not in this project · due Fri 9 Oct" under the name (nothing when there's nothing). */
function ResearcherFacts({ assignment }: { assignment: ResearchAssignment }) {
  const outside = assignment.researcher !== null && !assignment.researcher_in_project
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
 * The sidebar's "Research" value: the person, and for owners and admins a menu
 * (Change… / Remove); for the researcher, "Hand back…". The facts (outside the
 * project, the due date) sit under it.
 */
export function ResearcherField() {
  const { idea, me, openDialog } = useIdeaPage()
  const { assignment, canAssign, canHandBack } = useAssignment()
  const remove = useRemoveAssignment()
  const person = <ResearcherPerson assignment={assignment} />
  const name = assignmentText(assignment, idea.owner, me.id)
  return (
    <span className="flex w-full min-w-0 flex-col items-start">
      {canAssign || canHandBack ? (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="ghost"
              size="sm"
              className="-ml-2 max-w-full font-normal"
              aria-label={`${name}. ${canAssign ? 'Change' : 'Hand back'}`}
            >
              {person}
              <ChevronDown aria-hidden="true" className="text-muted" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start">
            {canAssign && (
              <DropdownMenuItem onSelect={() => openDialog('researcher')}>
                <UserRoundPen /> Change researcher or due date…
              </DropdownMenuItem>
            )}
            {canAssign && assignment.researcher && assignment.researcher.id !== me.id && (
              <DropdownMenuItem onSelect={() => remove(assignment)}>
                <UserMinus /> Remove researcher
              </DropdownMenuItem>
            )}
            {canHandBack && (
              <DropdownMenuItem onSelect={() => openDialog('hand-back')}>
                <Undo2 /> Hand back the research…
              </DropdownMenuItem>
            )}
          </DropdownMenuContent>
        </DropdownMenu>
      ) : (
        <span className="flex min-h-8 items-center">{person}</span>
      )}
      <ResearcherFacts assignment={assignment} />
    </span>
  )
}

/**
 * The Research panel's line: "Research: Bob Chen · due Fri 9 Oct" with Change /
 * Remove for owners and admins and Hand back for the researcher (phones reach it
 * here; the sidebar folds into Details).
 */
export function ResearcherLine() {
  const { me, idea, openDialog } = useIdeaPage()
  const { assignment, canAssign, canHandBack } = useAssignment()
  const remove = useRemoveAssignment()
  const person = assignment.researcher ?? idea.owner
  const outside = assignment.researcher !== null && !assignment.researcher_in_project
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
              size="sm"
              variant="ghost"
              className="text-secondary"
              aria-label="Change researcher or due date"
              onClick={() => openDialog('researcher')}
            >
              <CalendarClock /> Change
            </Button>
          )}
          {canAssign && assignment.researcher && assignment.researcher.id !== me.id && (
            <Button
              size="sm"
              variant="ghost"
              className="text-secondary"
              aria-label={`Remove ${assignment.researcher.display_name} as researcher`}
              onClick={() => remove(assignment)}
            >
              Remove
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

/** "Remove researcher" (owners and admins): at once, with an Undo that asks them again. */
function useRemoveAssignment() {
  const { ideaKey, idea } = useIdeaPage()
  const remove = useRemoveResearcher(ideaKey)
  const assign = useSetResearchAssignment(ideaKey)
  return (assignment: ResearchAssignment) => {
    const previous = assignment.researcher
    if (!previous) return
    remove.mutate(
      {},
      {
        onSuccess: () =>
          offerUndo(`${previous.display_name} is no longer researching ${idea.key}`, () =>
            assign.mutate(
              { researcher_id: previous.id, due_at: assignment.due_at },
              {
                onError: (error) => {
                  const { title, description } = describeError(error)
                  toast.error(title, { description })
                },
              },
            ),
          ),
      },
    )
  }
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
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="md" mobile="fullscreen" className="overflow-hidden">
        {open && <AssignmentForm mode={mode} onDone={() => onOpenChange(false)} />}
      </DialogContent>
    </Dialog>
  )
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
  const dueAt = due ? fromDateInput(due) : null
  const changed = researcherId !== currentId || due !== currentDue
  const outsider = choice.kind === 'person' && !choice.inProject
  const visibility = project?.visibility ?? 'private'
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
    // The status change's own toast says where it went, with Undo.
    const move = () =>
      changeStatus.mutate(
        { status: 'research' },
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
          {outsider ? (
            <p className="text-sm text-secondary" role="status">
              {visibility === 'internal' ? OUTSIDER_LINES.internal : OUTSIDER_LINES.private}
            </p>
          ) : (
            !canAssignOutside &&
            visibility === 'private' && (
              <p className="text-xs text-muted">
                Only a project admin can ask someone outside this project.
              </p>
            )
          )}
        </div>
        <Field
          label="Research due date"
          description={
            due
              ? 'They’re reminded 2 days before and on the day while a required item is open.'
              : 'Optional. No due date: no reminders, and it isn’t shown as overdue.'
          }
        >
          {/* "No due date" sits by the field: on a phone it never wraps onto a row alone. */}
          <div className="flex flex-wrap items-center gap-1.5">
            <DatePicker
              value={due}
              onValueChange={setDue}
              min={todayInput()}
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

  const confirm = () => {
    remove.mutate(
      { guest },
      {
        onSuccess: () => {
          onOpenChange(false)
          toast.success('You handed the research back', {
            description: owner
              ? `${owner.display_name} (the owner) does it again; your answers stay.`
              : 'Your answers stay.',
          })
          // A guest can't open the idea any more: off to My work, then nothing of it
          // stays cached (contract-phase8b §4.6).
          if (guest) void navigate({ to: '/' }).then(() => forgetIdea(queryClient, ideaKey))
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
      <DialogContent size="sm" role="alertdialog">
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
