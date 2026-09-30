import { X } from 'lucide-react'
import { useMemo, useState } from 'react'

import { useAddEvaluators, useSetEvaluationDueDate } from '@/api/ideas'
import type { UserSearchResult } from '@/api/types'
import { Avatar } from '@/components/ui/avatar'
import { Button } from '@/components/ui/button'
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
import { toast } from '@/components/ui/toaster'
import { SHORTCUTS, useShortcut } from '@/lib/shortcuts'

import { ariaKeys, ButtonShortcut } from './button-shortcut'
import { dateInputInDays, fromDateInput, toDateInput, todayInput } from './due-date'
import { useIdeaPage } from './idea-context'
import { toUserRef } from './owner-dialog'
import { PeopleList } from './people-list'

const MAX_PER_INVITE = 20

/**
 * "Invite evaluators": pick several members or admins and a due date. The
 * first invite pre-fills the project's default window (7 days); later ones
 * keep the idea's date. People already evaluating are shown but can't be picked.
 */
export function InviteDialog({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="md" mobile="fullscreen" className="overflow-hidden">
        {open && <InviteForm onDone={() => onOpenChange(false)} />}
      </DialogContent>
    </Dialog>
  )
}

function names(people: { display_name: string }[]): string {
  const list = people.map((person) => person.display_name)
  if (list.length <= 2) return list.join(' and ')
  return `${list.slice(0, -1).join(', ')} and ${list.at(-1) ?? ''}`
}

function InviteForm({ onDone }: { onDone: () => void }) {
  const { idea, ideaKey, project, me } = useIdeaPage()
  const add = useAddEvaluators(ideaKey)
  const setDueDate = useSetEvaluationDueDate(ideaKey)
  const [picked, setPicked] = useState<UserSearchResult[]>([])
  const firstInvite = idea.evaluators.length === 0
  const current = toDateInput(idea.evaluation_due_at)
  const [due, setDue] = useState(() =>
    current || !firstInvite ? current : dateInputInDays(project?.default_evaluation_days ?? 7),
  )

  const unavailable = useMemo(
    () =>
      new Map(
        idea.evaluators.map((evaluator) => [
          evaluator.user.id,
          evaluator.state === 'submitted' ? 'Already evaluated' : 'Already evaluating',
        ]),
      ),
    [idea.evaluators],
  )

  const toggle = (person: UserSearchResult) =>
    setPicked((current) =>
      current.some((p) => p.id === person.id)
        ? current.filter((p) => p.id !== person.id)
        : current.length >= MAX_PER_INVITE
          ? current
          : [...current, person],
    )

  const submit = () => {
    if (picked.length === 0 || add.isPending) return
    const users = picked.map(toUserRef)
    // Only send a date that changes something; an emptied field means "no due date".
    const clearAfter = due === '' && (current !== '' || firstInvite)
    const dueAt = due !== '' && due !== current ? fromDateInput(due) : undefined
    onDone()
    // mutateAsync: this form unmounts as the dialog closes, and per-call
    // callbacks of mutate() don't run after that.
    add
      .mutateAsync({ users, dueAt })
      .then(() => {
        if (clearAfter) setDueDate.mutate(null)
        toast.success(`Invited ${names(users)}`, {
          description: 'They’ll see it in My work.',
        })
      })
      .catch(() => undefined)
  }

  useShortcut('submitForm', submit)

  return (
    <form
      className="flex min-h-0 flex-1 flex-col"
      onSubmit={(event) => {
        event.preventDefault()
        submit()
      }}
    >
      <DialogHeader>
        <DialogTitle>Invite evaluators</DialogTitle>
        <DialogDescription className="truncate">
          {idea.key} · {idea.title}
        </DialogDescription>
      </DialogHeader>
      <DialogBody className="flex flex-col gap-4">
        <div className="flex flex-col gap-2">
          {picked.length > 0 ? (
            <ul aria-label="Selected people" className="flex flex-wrap gap-1.5">
              {picked.map((person) => (
                <li
                  key={person.id}
                  className="inline-flex h-7 items-center gap-1.5 rounded-full bg-subtle pr-1 pl-1 text-sm text-primary"
                >
                  <Avatar name={person.display_name} src={person.avatar_url} size="xs" decorative />
                  {person.display_name}
                  <button
                    type="button"
                    aria-label={`Remove ${person.display_name}`}
                    onClick={() => toggle(person)}
                    className="inline-flex size-5 items-center justify-center rounded-full text-muted transition-colors hover:bg-subtle-hover hover:text-primary"
                  >
                    <X aria-hidden="true" className="size-3" />
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted">
              Pick 2–4 people who know the area. Their scores stay hidden from each other until each
              submits.
            </p>
          )}
          <div className="overflow-hidden rounded-lg border">
            <PeopleList
              projectSlug={idea.project.slug}
              selected={picked.map((person) => person.id)}
              unavailable={unavailable}
              meId={me.id}
              label="Evaluators"
              placeholder="Search members…"
              onSelect={toggle}
            />
          </div>
        </div>
        <Field
          label="Due date"
          description={
            due
              ? 'Evaluators see it in My work; the idea shows as overdue after it.'
              : 'No due date: evaluators won’t see a deadline.'
          }
        >
          <DatePicker value={due} onValueChange={setDue} min={todayInput()} />
        </Field>
      </DialogBody>
      <DialogFooter>
        <Button type="button" variant="ghost" onClick={onDone}>
          Cancel
        </Button>
        <Button
          type="submit"
          variant="primary"
          disabled={picked.length === 0}
          aria-keyshortcuts={ariaKeys(SHORTCUTS.submitForm.keys)}
          className="max-sm:h-11"
        >
          {picked.length > 1 ? `Invite ${picked.length} people` : 'Invite'}
          <ButtonShortcut keys={SHORTCUTS.submitForm.keys} />
        </Button>
      </DialogFooter>
    </form>
  )
}
