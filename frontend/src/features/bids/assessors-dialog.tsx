import { Plus, X } from 'lucide-react'
import { useState } from 'react'

import { useSetBidAssessors } from '@/api/bids'
import { describeError, isApiError } from '@/api/errors'
import type { BidCall, ProjectVisibility, UserRef } from '@/api/types'
import { Avatar } from '@/components/ui/avatar'
import { Button } from '@/components/ui/button'
import { Callout } from '@/components/ui/callout'
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
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { toast } from '@/components/ui/toaster'
import { latestDueInput } from '@/features/idea/due-date'
import { PeopleList } from '@/features/idea/people-list'

import { useCallZone } from './call-dates'

const MAX_PER_SECTION = 10

/**
 * Who assesses each section, and by when (contract-phase10 §7.1): the complete state,
 * sent in one save (session only). People added are asked by notification; someone who
 * submitted an assessment of a section stays on it, and you can't step out of a section
 * you still owe (the server's 403 / 409 say so, worded here).
 */
export function AssessorsDialog({
  ideaKey,
  projectSlug,
  visibility,
  call,
  meId,
  open,
  onOpenChange,
}: {
  ideaKey: string
  projectSlug: string
  /** In a private project, only people with a role there can assess (c28). */
  visibility: ProjectVisibility | undefined
  call: BidCall
  meId: string
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const save = useSetBidAssessors(ideaKey)
  const initial = () =>
    new Map(call.template.sections.map((s) => [s.id, s.assessors.map((a) => a.user)]))
  const [people, setPeople] = useState<Map<string, UserRef[]>>(initial)
  const zone = useCallZone()
  const [due, setDue] = useState(zone.toInput(call.assessment_due_at))
  const [adding, setAdding] = useState<string | null>(null)
  const privateProject = visibility === 'private'

  const problem = save.error
    ? (() => {
        if (isApiError(save.error) && save.error.code === 'cannot_remove_self') {
          return 'You still owe assessments of a section you took yourself off. Submit them first, or ask another call manager to remove you.'
        }
        if (isApiError(save.error) && save.error.code === 'assessor_has_submitted') {
          return `${save.error.detail ?? 'Someone you removed has submitted an assessment.'} Submitted assessments are kept, so they stay on their section.`
        }
        if (isApiError(save.error) && save.error.code === 'assessor_not_eligible') {
          const detail = save.error.problem?.errors?.[0]?.msg ?? save.error.detail
          return `${detail ?? 'Someone can’t assess here'}. ${
            privateProject
              ? 'In a private project, assessors need a role in it: add them as members first.'
              : 'Assessors must be active people, never an AI agent.'
          }`
        }
        const { title, description } = describeError(save.error)
        return description ? `${title}. ${description}` : title
      })()
    : null

  const remove = (sectionId: string, userId: string) => {
    save.reset()
    setPeople((current) => {
      const next = new Map(current)
      next.set(
        sectionId,
        (next.get(sectionId) ?? []).filter((u) => u.id !== userId),
      )
      return next
    })
  }
  const add = (sectionId: string, user: UserRef) => {
    save.reset()
    setPeople((current) => {
      const next = new Map(current)
      const list = next.get(sectionId) ?? []
      next.set(
        sectionId,
        list.some((u) => u.id === user.id)
          ? list.filter((u) => u.id !== user.id)
          : [...list, user].slice(0, MAX_PER_SECTION),
      )
      return next
    })
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (next) {
          setPeople(initial())
          setDue(zone.toInput(call.assessment_due_at))
        } else save.reset()
        onOpenChange(next)
      }}
    >
      <DialogContent size="xl" mobile="fullscreen">
        <DialogHeader>
          <DialogTitle>Assessors</DialogTitle>
          <DialogDescription>
            Each section’s assessors score it for every bid, blind: they see nobody else’s scores
            for a bid until they have submitted their own.{' '}
            {privateProject
              ? 'This project is private: assessors need a role in it.'
              : 'Anyone who can see this idea can assess.'}
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="flex flex-col gap-5">
          {problem && <Callout tone="danger" title={problem} role="alert" />}
          <ul className="flex flex-col divide-y divide-subtle rounded-lg border">
            {call.template.sections.map((section) => {
              const list = people.get(section.id) ?? []
              return (
                <li key={section.id} className="flex flex-col gap-2 px-4 py-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <h3 className="text-sm font-medium text-primary">
                      {section.title}{' '}
                      <span className="font-normal text-muted">
                        · {section.weight}%{section.has_price ? ' · holds the price' : ''}
                      </span>
                    </h3>
                    <Popover
                      open={adding === section.id}
                      onOpenChange={(next) => setAdding(next ? section.id : null)}
                    >
                      <PopoverTrigger asChild>
                        <Button
                          variant="ghost"
                          size="sm"
                          disabled={list.length >= MAX_PER_SECTION}
                          aria-label={`Add an assessor to ${section.title}`}
                        >
                          <Plus /> Add
                        </Button>
                      </PopoverTrigger>
                      <PopoverContent
                        align="end"
                        collisionPadding={16}
                        className="w-80 p-0"
                        aria-label={`Assessors of ${section.title}`}
                      >
                        <PeopleList
                          projectSlug={projectSlug}
                          label={`Assessors of ${section.title}`}
                          selected={list.map((u) => u.id)}
                          meId={meId}
                          includeNonMembers={!privateProject}
                          ineligible={(person) =>
                            privateProject && person.project_role === null
                              ? 'Not in this project · add them as a member first'
                              : undefined
                          }
                          onSelect={(person) =>
                            add(section.id, {
                              id: person.id,
                              display_name: person.display_name,
                              avatar_url: person.avatar_url,
                              initials: person.initials,
                            })
                          }
                          listClassName="max-h-72"
                        />
                      </PopoverContent>
                    </Popover>
                  </div>
                  {list.length === 0 ? (
                    <p className="text-sm text-muted">Nobody yet.</p>
                  ) : (
                    <ul
                      className="flex flex-wrap gap-2"
                      aria-label={`Assessors of ${section.title}`}
                    >
                      {list.map((user) => (
                        <li
                          key={user.id}
                          className="flex items-center gap-1.5 rounded-full border bg-surface py-0.5 pr-0.5 pl-1 text-sm"
                        >
                          <Avatar
                            name={user.display_name}
                            src={user.avatar_url}
                            size="xs"
                            decorative
                          />
                          <span className="text-primary">
                            {user.display_name}
                            {user.id === meId && <span className="text-muted"> (you)</span>}
                          </span>
                          <Button
                            variant="ghost"
                            size="icon-sm"
                            className="size-6 rounded-full"
                            aria-label={`Remove ${user.display_name} from ${section.title}`}
                            onClick={() => remove(section.id, user.id)}
                          >
                            <X />
                          </Button>
                        </li>
                      ))}
                    </ul>
                  )}
                </li>
              )
            })}
          </ul>
          <Field
            label="Assessments due"
            description={`Optional. By the end of that day${zone.differs ? ` (${zone.timeZone} time)` : ''}; assessors are reminded 2 days before and on the day.`}
          >
            <DatePicker
              value={due}
              onValueChange={setDue}
              min={zone.pickerMin(due)}
              max={latestDueInput()}
            />
          </Field>
        </DialogBody>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            variant="primary"
            loading={save.isPending}
            onClick={() =>
              save.mutate(
                {
                  sections: call.template.sections.map((s) => ({
                    section_id: s.id,
                    user_ids: (people.get(s.id) ?? []).map((u) => u.id),
                  })),
                  due_at:
                    due === zone.toInput(call.assessment_due_at)
                      ? call.assessment_due_at
                      : zone.fromInput(due),
                },
                {
                  onSuccess: () => {
                    toast.success('Assessors saved', {
                      description: 'Anyone new is told which sections they assess.',
                    })
                    onOpenChange(false)
                  },
                },
              )
            }
          >
            Save assessors
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
