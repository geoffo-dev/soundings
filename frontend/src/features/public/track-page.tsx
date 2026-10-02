import {
  CloudOff,
  Hourglass,
  LinkIcon,
  MailCheck,
  MailWarning,
  Trash2,
  UserRoundX,
} from 'lucide-react'
import { useEffect, useRef, useState, type ReactNode } from 'react'

import { describeError, isApiError } from '@/api/errors'
import {
  useEraseTrackedSubmission,
  useResendVerificationEmail,
  useSetSubmissionUpdates,
  useTrackedSubmission,
} from '@/api/public'
import type { EffectiveBranding, TrackedSubmission } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Callout } from '@/components/ui/callout'
import { EmptyState } from '@/components/ui/empty-state'
import { Field } from '@/components/ui/field'
import { Skeleton, SkeletonGroup } from '@/components/ui/skeleton'
import { StatusBadge, StatusDot } from '@/components/ui/status-badge'
import { Switch } from '@/components/ui/switch'
import { ConfirmDialog } from '@/features/admin/confirm-dialog'
import { formatDate } from '@/lib/dates'
import { statusTone, type StatusTone } from '@/lib/status'
import { cn } from '@/lib/utils'

import { TRACKING_TOKEN, useFragmentToken } from './fragment-token'
import { PublicCard, PublicLayout } from './public-layout'

/**
 * /track#<token> (contract-phase4 §3.7): what the submitter sent and where it
 * is now, a calm timeline of status changes (dates and labels only: no people,
 * comments or scores), status emails on or off, the confirmation email again,
 * and "Delete my details". Unknown and erased links read the same.
 */
export function TrackPage() {
  const token = useFragmentToken(TRACKING_TOKEN)
  const tracked = useTrackedSubmission(token)
  const [erasedWith, setErasedWith] = useState<EffectiveBranding | null>(null)

  if (erasedWith) {
    return (
      <PublicLayout branding={erasedWith} width="narrow">
        <PublicCard>
          <StateMessage icon={<UserRoundX />} title="Your details are deleted" focus>
            Your name, email address and this private link are gone. The team still has your idea.
          </StateMessage>
        </PublicCard>
      </PublicLayout>
    )
  }

  if (!token) {
    return (
      <PublicLayout branding={null} width="narrow">
        <PublicCard>
          <StateMessage icon={<LinkIcon />} title="This tracking link is incomplete">
            Open the private link from your confirmation page or email. It ends with a long code
            after “#”.
          </StateMessage>
        </PublicCard>
      </PublicLayout>
    )
  }

  if (tracked.isError) {
    const error = tracked.error
    const status = isApiError(error) ? error.status : 0
    return (
      <PublicLayout branding={null} width="narrow">
        <PublicCard>
          {status === 404 || status === 422 ? (
            <StateMessage icon={<LinkIcon />} title="We can’t find this submission">
              It may have been removed, or the link is incomplete. Check you copied the whole link.
            </StateMessage>
          ) : (
            <EmptyState
              role="alert"
              size="compact"
              headingLevel={1}
              icon={<CloudOff />}
              title={status === 429 ? 'Too many requests just now' : 'We couldn’t load your idea'}
              description={
                status === 429
                  ? 'Wait a minute, then try again.'
                  : 'Check your connection and try again.'
              }
              action={
                <Button variant="primary" onClick={() => void tracked.refetch()}>
                  Try again
                </Button>
              }
            />
          )}
        </PublicCard>
      </PublicLayout>
    )
  }

  if (!tracked.data) return <TrackSkeleton />
  return (
    <TrackedView
      token={token}
      tracked={tracked.data}
      onErased={() => setErasedWith(tracked.data.branding)}
    />
  )
}

function StateMessage({
  icon,
  title,
  children,
  focus = false,
}: {
  icon: ReactNode
  title: string
  children: ReactNode
  focus?: boolean
}) {
  const heading = useRef<HTMLHeadingElement>(null)
  useEffect(() => {
    if (focus) heading.current?.focus()
  }, [focus])
  return (
    <div className="flex flex-col gap-2">
      <span
        aria-hidden="true"
        className="flex size-10 items-center justify-center rounded-xl border bg-surface text-muted [&_svg]:size-5"
      >
        {icon}
      </span>
      <h1
        ref={heading}
        tabIndex={-1}
        className="text-xl font-semibold text-primary focus:outline-none"
      >
        {title}
      </h1>
      <p className="text-base text-secondary">{children}</p>
    </div>
  )
}

function TrackSkeleton() {
  return (
    <PublicLayout branding={undefined}>
      <SkeletonGroup label="Loading your idea" className="flex flex-col gap-6">
        <div className="flex flex-col gap-2 px-1">
          <Skeleton className="h-4 w-40" />
          <Skeleton className="h-7 w-3/4" />
        </div>
        <div className="flex flex-col gap-4 rounded-xl border bg-surface p-4 sm:p-6">
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-2/3" />
          <Skeleton className="h-6 w-28 rounded-md" />
          <Skeleton className="h-16 w-full" />
        </div>
      </SkeletonGroup>
    </PublicLayout>
  )
}

/** What a status means for the person who sent the idea, in plain words. */
export function statusMeaning(
  status: TrackedSubmission['status'],
  resolution: TrackedSubmission['resolution'],
): string {
  switch (status) {
    case 'new':
      return 'The team has your idea and will look at it soon.'
    case 'evaluating':
      return 'The team is weighing it up: a few people are looking at it closely.'
    case 'shortlisted':
      return 'Good news: the team thinks it’s worth taking further.'
    case 'proposal':
      return 'The team is writing a proposal to take it forward.'
    case 'closed':
      return resolution === 'accepted'
        ? 'The team has decided to go ahead with it.'
        : resolution === 'rejected'
          ? 'The team has decided not to take it forward. Thank you for sending it.'
          : 'The team has put it aside for now. It may come back later.'
  }
}

const HELD_COPY = {
  email_verification: {
    label: 'Waiting for you to confirm your email address',
    text: 'Open the link we emailed you. The team gets your idea once you confirm.',
  },
  moderation: {
    label: 'Waiting for review',
    text: 'The team reviews new ideas before they’re shared. This page updates when it’s through.',
  },
} as const

function TrackedView({
  token,
  tracked,
  onErased,
}: {
  token: string
  tracked: TrackedSubmission
  onErased: () => void
}) {
  const held = tracked.held_for ? HELD_COPY[tracked.held_for] : null
  return (
    <PublicLayout branding={tracked.branding} projectName={tracked.project.name}>
      <div className="flex flex-col gap-1 px-1">
        <p className="text-sm text-muted">
          Your idea for {tracked.project.name} · sent {formatDate(tracked.submitted_at)}
        </p>
        <h1 className="text-2xl font-semibold text-balance break-words text-primary">
          {tracked.title}
        </h1>
      </div>

      <PublicCard>
        <p className="text-base break-words whitespace-pre-line text-secondary">
          {tracked.summary}
        </p>
        <div className="flex flex-col gap-2 border-t border-subtle pt-4">
          <h2 className="text-sm font-medium text-muted">Where it is now</h2>
          {held ? (
            <div className="flex flex-col gap-1">
              <span className="inline-flex items-center gap-2 text-base font-medium text-primary">
                <Hourglass aria-hidden="true" className="size-4 text-muted" />
                {held.label}
              </span>
              <p className="text-sm text-muted">{held.text}</p>
            </div>
          ) : (
            <div className="flex flex-col items-start gap-1.5">
              <StatusBadge
                status={tracked.status}
                resolution={tracked.resolution}
                label={tracked.status_label}
              />
              <p className="text-sm text-secondary">
                {statusMeaning(tracked.status, tracked.resolution)}
              </p>
            </div>
          )}
        </div>
        <Timeline tracked={tracked} />
      </PublicCard>

      <EmailSettings token={token} tracked={tracked} />
      <DeleteDetails token={token} onErased={onErased} />
    </PublicLayout>
  )
}

/**
 * Sent, then "With the team" once it is through (confirmed and, where the team
 * reviews new ideas, approved), then every status change since: dates and labels
 * only.
 */
function Timeline({ tracked }: { tracked: TrackedSubmission }) {
  const items: { key: string; label: string; at: string | null; tone: StatusTone | null }[] = [
    { key: 'sent', label: 'Sent', at: tracked.submitted_at, tone: null },
    ...(tracked.held_for
      ? []
      : [{ key: 'with-team', label: 'With the team', at: tracked.reached_team_at, tone: null }]),
    ...tracked.history.map((change, index) => ({
      key: `${change.at}-${index}`,
      label: change.status_label,
      at: change.at,
      tone: statusTone(change.status, change.resolution),
    })),
  ]
  return (
    <div className="flex flex-col gap-2 border-t border-subtle pt-4">
      <h2 className="text-sm font-medium text-muted">History</h2>
      <ol className="flex flex-col">
        {items.map((item, index) => (
          <li key={item.key} className="relative flex gap-3 pb-3 last:pb-0">
            {index < items.length - 1 && (
              <span
                aria-hidden="true"
                className="absolute top-4 bottom-0 left-1 w-px -translate-x-1/2 bg-border"
              />
            )}
            <span className="flex h-5 w-2 shrink-0 items-center justify-center">
              {item.tone ? (
                <StatusDot tone={item.tone} />
              ) : (
                <span aria-hidden="true" className="size-2 rounded-full bg-control" />
              )}
            </span>
            <span className="flex min-w-0 flex-1 flex-wrap items-baseline justify-between gap-x-3 text-sm">
              <span className="font-medium text-primary">{item.label}</span>
              {item.at && (
                <time dateTime={item.at} className="text-muted tabular-nums">
                  {formatDate(item.at)}
                </time>
              )}
            </span>
          </li>
        ))}
      </ol>
    </div>
  )
}

function EmailSettings({ token, tracked }: { token: string; tracked: TrackedSubmission }) {
  const updates = useSetSubmissionUpdates(token)
  const resend = useResendVerificationEmail(token)
  const [resent, setResent] = useState(false)

  if (!tracked.email_hint) {
    return (
      <PublicCard className="gap-2">
        <h2 className="text-base font-semibold text-primary">Email updates</h2>
        <p className="text-sm text-muted">
          You didn’t leave an email address, so we can’t send you updates. Check back here any time.
        </p>
      </PublicCard>
    )
  }

  const wantsUpdates = updates.isPending ? updates.variables : tracked.wants_updates
  const resendError = resend.isError ? resendMessage(resend.error) : null

  return (
    <PublicCard className="gap-4">
      <div className="flex flex-col gap-1">
        <h2 className="text-base font-semibold text-primary">Email updates</h2>
        <p className="flex items-center gap-1.5 text-sm text-muted">
          {tracked.email_verified ? (
            <MailCheck aria-hidden="true" className="size-4 text-success" />
          ) : (
            <MailWarning aria-hidden="true" className="size-4 text-warning" />
          )}
          <span>
            {tracked.email_hint} · {tracked.email_verified ? 'confirmed' : 'not confirmed yet'}
          </span>
        </p>
      </div>
      <Field
        inline
        label="Email me when the status changes"
        description={
          tracked.email_verified
            ? 'Only about this idea.'
            : 'We send these once you’ve confirmed your address.'
        }
        error={updates.isError ? describeError(updates.error).title : undefined}
      >
        <Switch
          checked={wantsUpdates}
          disabled={updates.isPending}
          onCheckedChange={(checked) => updates.mutate(checked)}
        />
      </Field>
      {!tracked.email_verified && (
        <div className="flex flex-col gap-2 rounded-lg bg-subtle px-3 py-3">
          <p className="text-sm text-secondary">
            Didn’t get our email? Check your spam folder, or we can send it again.
          </p>
          <div>
            <Button
              variant="outline"
              loading={resend.isPending}
              disabled={!tracked.can_resend_verification}
              onClick={() =>
                resend.mutate(undefined, {
                  onSuccess: () => setResent(true),
                })
              }
            >
              Send the confirmation email again
            </Button>
          </div>
          <p aria-live="polite" className="text-sm">
            {resent && !resend.isError ? (
              <span className="text-success">Sent. It can take a minute to arrive.</span>
            ) : resendError ? (
              <span className="text-danger">{resendError}</span>
            ) : !tracked.can_resend_verification ? (
              <span className="text-muted">
                We can’t send another one just now (at most 3 a day). Try again tomorrow.
              </span>
            ) : null}
          </p>
        </div>
      )}
    </PublicCard>
  )
}

function resendMessage(error: unknown): string {
  if (isApiError(error)) {
    if (error.status === 429) return 'We’ve sent it 3 times today. You can ask again tomorrow.'
    if (error.code === 'already_verified') return 'Your address is already confirmed.'
    if (error.code === 'smtp_not_configured') return 'Email isn’t available right now.'
  }
  return 'That didn’t work. Check your connection and try again.'
}

function DeleteDetails({ token, onErased }: { token: string; onErased: () => void }) {
  const erase = useEraseTrackedSubmission(token)
  const [open, setOpen] = useState(false)
  return (
    <section
      aria-labelledby="delete-details-heading"
      className={cn('flex flex-col gap-3 px-1 sm:flex-row sm:items-center sm:justify-between')}
    >
      <div className="flex flex-col gap-0.5">
        <h2 id="delete-details-heading" className="text-sm font-medium text-primary">
          Delete my details
        </h2>
        <p className="text-sm text-muted">
          Removes your name, email address and this link. The idea stays with the team.
        </p>
      </div>
      <Button variant="outline" className="shrink-0" onClick={() => setOpen(true)}>
        <Trash2 aria-hidden="true" />
        Delete my details
      </Button>
      <ConfirmDialog
        open={open}
        onOpenChange={(next) => {
          setOpen(next)
          if (!next) erase.reset()
        }}
        title="Delete your details?"
        description="This removes your name, email address and this private link. You won’t be able to follow your idea any more. The idea stays with the team."
        confirmLabel="Delete my details"
        tone="danger"
        pending={erase.isPending}
        onConfirm={() =>
          erase.mutate(undefined, {
            onSuccess: () => {
              setOpen(false)
              onErased()
            },
          })
        }
      >
        {erase.isError && (
          <Callout role="alert" tone="danger" title="That didn’t work">
            {isApiError(erase.error) && erase.error.status === 404
              ? 'This link no longer works: your details may already be deleted.'
              : 'Nothing changed. Check your connection and try again.'}
          </Callout>
        )}
      </ConfirmDialog>
    </section>
  )
}
