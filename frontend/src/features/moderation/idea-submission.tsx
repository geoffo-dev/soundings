import { useNavigate } from '@tanstack/react-router'
import { Check, Globe, Hourglass, Mail, MailCheck, Trash2, UserRoundX } from 'lucide-react'
import { useRef, useState } from 'react'

import { describeError } from '@/api/errors'
import {
  useEraseSubmitter,
  useIdeaSubmission,
  useModerate,
  useModerationPending,
} from '@/api/submissions'
import type { IdeaDetail, IdeaSubmission } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Callout } from '@/components/ui/callout'
import { RelativeTime } from '@/components/ui/relative-time'
import { toast } from '@/components/ui/toaster'
import { ConfirmDialog } from '@/features/admin/confirm-dialog'
import { formatDate } from '@/lib/dates'
import { focusWhenRendered } from '@/lib/focus'

/*
 * Public submissions on the idea page (contract-phase4 §3.6, §3.9): a banner
 * with Approve / Reject while an idea waits for review (only admins can open
 * one), who sent it ("Submitted by Jo via the public form"), and for admins
 * the submitter's contact details with "Erase submitter details".
 */

/** The submission behind a public idea (no request for ideas from members). */
function useSubmissionOf(idea: IdeaDetail, ideaKey: string) {
  // A guest researcher can't read the submission (Phase 8b: 404 for column R).
  return useIdeaSubmission(ideaKey, {
    enabled: idea.via_public_form && idea.permissions.can_view_project,
  })
}

/** "· Submitted by Jo via the public form 2 days ago" in the idea's header line. */
export function PublicSubmitterLine({ idea, ideaKey }: { idea: IdeaDetail; ideaKey: string }) {
  const submission = useSubmissionOf(idea, ideaKey).data
  if (!idea.via_public_form) return null
  return (
    <span className="hidden min-w-0 truncate xs:inline">
      <span aria-hidden="true">· </span>
      {submission?.name
        ? `Submitted by ${submission.name} via the public form `
        : 'Via the public form '}
      <RelativeTime date={idea.created_at} tooltip={false} />
    </span>
  )
}

/**
 * Above an idea held for moderation (admins only reach it): it is read-only
 * and on no board or list until approved. Approve and Reject wait for their
 * Undo toast; a rejected idea is deleted, so the page goes back to the queue.
 */
export function HeldIdeaBanner({ idea, ideaKey }: { idea: IdeaDetail; ideaKey: string }) {
  const submission = useSubmissionOf(idea, ideaKey).data
  const moderate = useModerate()
  const navigate = useNavigate()
  const pending = useModerationPending(idea)
  const banner = useRef<HTMLDivElement>(null)
  if (idea.held_for !== 'moderation') return null
  const canModerate = submission?.permissions.can_moderate ?? false
  // The buttons go while the Undo toast is open: focus stays on the banner (it says
  // what is happening), then, once approved, moves to the idea's tabs below it.
  const onHide = () => focusWhenRendered(() => banner.current)
  const afterApproval = () =>
    focusWhenRendered(() =>
      document.querySelector<HTMLElement>('[role="tab"][aria-selected="true"]'),
    )
  const target = { id: idea.id, key: idea.key, title: idea.title, project: idea.project }

  return (
    <div
      ref={banner}
      tabIndex={-1}
      role="region"
      aria-label="Waiting for review"
      className="mb-5 flex flex-col gap-3 rounded-lg border border-warning/40 bg-warning-subtle px-4 py-3 sm:flex-row sm:items-center sm:justify-between"
    >
      <div className="flex items-start gap-2.5">
        <Hourglass aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-warning" />
        <div className="flex flex-col gap-0.5 text-sm">
          <p className="font-medium text-primary">
            {pending ? 'Waiting for the Undo toast to close…' : 'Waiting for review'}
          </p>
          <p className="text-secondary">
            This idea came in through the public form. Only project admins can see it, and it’s on
            no board or list until it’s approved.
          </p>
        </div>
      </div>
      {canModerate && !pending && (
        <div className="flex shrink-0 gap-2">
          <Button
            variant="outline"
            className="flex-1 sm:flex-none"
            onClick={() =>
              moderate.reject(target, {
                onHide,
                onDone: () =>
                  void navigate({ to: '/p/$slug/review', params: { slug: idea.project.slug } }),
              })
            }
          >
            <Trash2 aria-hidden="true" /> Reject
          </Button>
          <Button
            variant="primary"
            className="flex-1 sm:flex-none"
            onClick={() => moderate.approve(target, { onHide, onDone: afterApproval })}
          >
            <Check aria-hidden="true" /> Approve
          </Button>
        </div>
      )}
    </div>
  )
}

/** In the idea's details: how it came in, and the submitter's details for admins. */
export function SubmissionPanel({ idea, ideaKey }: { idea: IdeaDetail; ideaKey: string }) {
  const submission = useSubmissionOf(idea, ideaKey)
  if (!idea.via_public_form || !submission.data) return null
  return <SubmissionDetails submission={submission.data} ideaKey={ideaKey} />
}

function SubmissionDetails({
  submission,
  ideaKey,
}: {
  submission: IdeaSubmission
  ideaKey: string
}) {
  const erase = useEraseSubmitter(ideaKey)
  const [open, setOpen] = useState(false)
  const contact = submission.contact
  const who = submission.name ? `${submission.name}’s` : 'The submitter’s'

  return (
    <section aria-labelledby="submission-heading" className="flex flex-col gap-2">
      <h2
        id="submission-heading"
        className="flex items-center gap-1.5 text-sm font-medium text-muted"
      >
        <Globe aria-hidden="true" className="size-3.5" />
        Public form
      </h2>
      <div className="flex flex-col gap-1.5 text-sm">
        {submission.erased_at ? (
          <p className="flex items-start gap-1.5 text-secondary">
            <UserRoundX aria-hidden="true" className="mt-0.5 size-3.5 shrink-0 text-muted" />
            <span>Submitter’s details erased {formatDate(submission.erased_at)}</span>
          </p>
        ) : (
          <>
            <p className="text-primary">
              {submission.name ? `Sent by ${submission.name}` : 'Sent without a name'}
              <span className="text-muted">
                {' '}
                · <RelativeTime date={submission.submitted_at} />
              </span>
            </p>
            {contact && (
              <>
                {contact.email ? (
                  <p className="flex min-w-0 items-center gap-1.5 text-secondary">
                    {contact.email_verified ? (
                      <MailCheck aria-hidden="true" className="size-3.5 shrink-0 text-success" />
                    ) : (
                      <Mail aria-hidden="true" className="size-3.5 shrink-0 text-muted" />
                    )}
                    <span className="truncate" title={contact.email}>
                      {contact.email}
                    </span>
                    <span className="shrink-0 text-muted">
                      {contact.email_verified ? 'confirmed' : 'not confirmed'}
                    </span>
                  </p>
                ) : (
                  <p className="text-muted">No email address</p>
                )}
                {contact.email && (
                  <p className="text-muted">
                    {contact.wants_updates
                      ? 'Gets an email when the status changes'
                      : 'Doesn’t get status emails'}
                  </p>
                )}
              </>
            )}
          </>
        )}
      </div>
      {submission.permissions.can_erase && (
        <Button
          variant="ghost"
          size="sm"
          className="-ml-2.5 self-start text-secondary"
          onClick={() => setOpen(true)}
        >
          <UserRoundX aria-hidden="true" /> Erase submitter details…
        </Button>
      )}
      <ConfirmDialog
        open={open}
        onOpenChange={(next) => {
          setOpen(next)
          if (!next) erase.reset()
        }}
        title="Erase the submitter’s details?"
        description={`${who} name, email address and private tracking link will be deleted, along with any emails waiting to go to them. The idea and its history stay. This can’t be undone.`}
        confirmLabel="Erase details"
        tone="danger"
        pending={erase.isPending}
        onConfirm={() =>
          erase.mutate(undefined, {
            onSuccess: () => {
              setOpen(false)
              toast.success('Submitter details erased', {
                description: 'Their tracking link no longer works.',
              })
            },
          })
        }
      >
        <p>
          Personal details they typed into the idea itself aren’t touched: edit the idea to remove
          those.
        </p>
        {erase.isError && (
          <Callout role="alert" tone="danger" title="Nothing was erased" className="mt-3">
            {describeError(erase.error).title}
          </Callout>
        )}
      </ConfirmDialog>
    </section>
  )
}
