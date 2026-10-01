import {
  Ban,
  CircleAlert,
  CircleCheck,
  Clock,
  CloudOff,
  Inbox,
  ListFilter,
  MailCheck,
  RotateCw,
  Tag,
} from 'lucide-react'
import { useRef, type ReactNode } from 'react'

import {
  useOutboxEmails,
  useRetryFailedOutboxEmails,
  useRetryOutboxEmail,
  type OutboxFilters,
} from '@/api/admin-email'
import type { EmailStatus, EmailType, OutboxEmail, OutboxStats } from '@/api/types'
import { Avatar } from '@/components/ui/avatar'
import { Button } from '@/components/ui/button'
import { Command, CommandGroup, CommandList } from '@/components/ui/command'
import { EmptyState } from '@/components/ui/empty-state'
import { FilterMenu, FilterMenuOption } from '@/components/ui/filter-menu'
import { RelativeTime } from '@/components/ui/relative-time'
import { Skeleton, SkeletonGroup } from '@/components/ui/skeleton'
import { Spinner } from '@/components/ui/spinner'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { AdminSection } from '@/features/admin/settings-frame'
import { formatRelative } from '@/lib/dates'
import { cn } from '@/lib/utils'

import { EMAIL_STATUS, EMAIL_TYPE_LABEL, errorHint, type StatusTone } from './email-copy'
import { EMAIL_STATUSES, EMAIL_TYPES, type EmailSearch } from './email-search'

/**
 * The outbox (contract-phase3 §3.10): counters, filters by status and type,
 * newest first, with Retry on failed emails that are still recent enough to
 * send (`retryable`) and "Retry all failed". No subjects or bodies: they are
 * rendered when sent and never stored.
 */
export function OutboxSection({
  stats,
  status,
  type,
  onChange,
}: {
  stats: OutboxStats
  /** The statuses in effect (the URL's, or failed by default). */
  status: EmailStatus[]
  type: EmailType[]
  onChange: (patch: Partial<EmailSearch>) => void
}) {
  const filters: OutboxFilters = { status, type }
  const query = useOutboxEmails(filters)
  const retryAll = useRetryFailedOutboxEmails()
  const items = query.data?.items ?? []
  const filtered = status.length > 0 || type.length > 0

  const setStatus = (next: EmailStatus[]) => onChange({ status: next.length ? next : ['all'] })

  return (
    <AdminSection
      id="outbox"
      title="Outbox"
      description="Every email waits here; the worker sends it, and retries while the mail server is down."
      actions={
        stats.failed > 0 ? (
          <Button
            variant="secondary"
            size="sm"
            loading={retryAll.isPending}
            onClick={() => retryAll.mutate()}
          >
            <RotateCw />
            Retry all failed
          </Button>
        ) : undefined
      }
    >
      <OutboxCounters stats={stats} status={status} onStatus={setStatus} />

      <div role="group" aria-label="Filters" className="flex flex-wrap items-center gap-1.5">
        <FilterMenu
          label="Status"
          icon={<ListFilter aria-hidden="true" />}
          value={
            status.length === 0
              ? undefined
              : status.map((value) => EMAIL_STATUS[value].label).join(', ')
          }
          onClear={() => setStatus([])}
        >
          {() => (
            <Command>
              <CommandList aria-label="Statuses">
                <CommandGroup>
                  {EMAIL_STATUSES.map((value) => (
                    <FilterMenuOption
                      key={value}
                      value={value}
                      keywords={[EMAIL_STATUS[value].label]}
                      checked={status.includes(value)}
                      onSelect={() =>
                        setStatus(
                          status.includes(value)
                            ? status.filter((s) => s !== value)
                            : [...status, value],
                        )
                      }
                    >
                      <StatusLabel status={value} />
                    </FilterMenuOption>
                  ))}
                </CommandGroup>
              </CommandList>
            </Command>
          )}
        </FilterMenu>
        <FilterMenu
          label="Type"
          icon={<Tag aria-hidden="true" />}
          value={
            type.length === 0
              ? undefined
              : type.length === 1
                ? EMAIL_TYPE_LABEL[type[0] ?? 'test']
                : `${EMAIL_TYPE_LABEL[type[0] ?? 'test']} +${type.length - 1}`
          }
          onClear={() => onChange({ type: undefined })}
          menuClassName="w-60"
        >
          {() => (
            <Command>
              <CommandList aria-label="Email types">
                <CommandGroup>
                  {EMAIL_TYPES.map((value) => (
                    <FilterMenuOption
                      key={value}
                      value={value}
                      keywords={[EMAIL_TYPE_LABEL[value]]}
                      checked={type.includes(value)}
                      onSelect={() => {
                        const next = type.includes(value)
                          ? type.filter((t) => t !== value)
                          : [...type, value]
                        onChange({ type: next.length ? next : undefined })
                      }}
                    >
                      {EMAIL_TYPE_LABEL[value]}
                    </FilterMenuOption>
                  ))}
                </CommandGroup>
              </CommandList>
            </Command>
          )}
        </FilterMenu>
        {filtered && (
          <Button
            variant="ghost"
            size="sm"
            className="text-secondary"
            onClick={() => onChange({ status: ['all'], type: undefined })}
          >
            Show all
          </Button>
        )}
      </div>

      {query.isPending ? (
        <SkeletonGroup label="Loading the outbox" className="flex flex-col rounded-lg border">
          {[0, 1, 2, 3].map((i) => (
            <div
              key={i}
              className="flex items-center gap-3 border-b border-subtle px-4 py-3 last:border-0"
            >
              <Skeleton className="h-3.5 w-40" />
              <Skeleton className="ml-auto h-3.5 w-24" />
            </div>
          ))}
        </SkeletonGroup>
      ) : query.isError && items.length === 0 ? (
        <EmptyState
          role="alert"
          size="compact"
          className="rounded-lg border"
          icon={<CloudOff />}
          title="Couldn’t load the outbox"
          description="Check your connection and try again."
          action={
            <Button variant="secondary" onClick={() => void query.refetch()}>
              Try again
            </Button>
          }
        />
      ) : items.length === 0 ? (
        <EmptyState
          size="compact"
          className="rounded-lg border"
          icon={filtered ? <Inbox /> : <MailCheck />}
          title={
            status.length === 1 && status[0] === 'failed'
              ? 'No failed emails'
              : filtered
                ? 'No emails match these filters'
                : 'Nothing sent yet'
          }
          description={
            status.length === 1 && status[0] === 'failed'
              ? 'All emails delivered.'
              : filtered
                ? 'Try another status or type.'
                : 'Emails appear here as soon as something is queued.'
          }
          action={
            filtered ? (
              <Button
                variant="secondary"
                onClick={() => onChange({ status: ['all'], type: undefined })}
              >
                Show all emails
              </Button>
            ) : undefined
          }
        />
      ) : (
        <div className="overflow-hidden rounded-lg border">
          <Table mobile="container-cards" aria-label="Outbox emails" className="@3xl:table-fixed">
            <TableHeader>
              <TableRow>
                <TableHead>Email</TableHead>
                <TableHead className="w-44">To</TableHead>
                <TableHead className="w-60">Status</TableHead>
                <TableHead className="w-28 text-right">Queued</TableHead>
                <TableHead className="w-32">
                  <span className="sr-only">Actions</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((email) => (
                <OutboxRow key={email.id} email={email} />
              ))}
            </TableBody>
          </Table>
          {query.hasNextPage && (
            <div className="flex justify-center border-t border-subtle p-1.5">
              <Button
                variant="ghost"
                size="sm"
                loading={query.isFetchingNextPage}
                onClick={() => void query.fetchNextPage()}
              >
                Load older emails
              </Button>
            </div>
          )}
        </div>
      )}
    </AdminSection>
  )
}

function OutboxCounters({
  stats,
  status,
  onStatus,
}: {
  stats: OutboxStats
  status: EmailStatus[]
  onStatus: (status: EmailStatus[]) => void
}) {
  const only = (value: EmailStatus) => status.length === 1 && status[0] === value
  const counter = (
    value: EmailStatus,
    label: string,
    count: number,
    detail: ReactNode,
    tone?: 'danger',
  ) => (
    <button
      type="button"
      aria-pressed={only(value)}
      onClick={() => onStatus(only(value) ? [] : [value])}
      className={cn(
        'flex min-w-0 flex-col items-start gap-0.5 rounded-lg border px-3 py-2.5 text-left transition-colors',
        'hover:border-strong aria-pressed:border-accent aria-pressed:bg-accent-subtle',
      )}
    >
      <span className="text-xs font-medium text-muted">{label}</span>
      <span
        className={cn(
          'text-xl font-semibold tabular-nums',
          tone === 'danger' && count > 0 ? 'text-danger' : 'text-primary',
        )}
      >
        {count.toLocaleString()}
      </span>
      <span className="w-full truncate text-xs text-muted">{detail}</span>
    </button>
  )
  return (
    <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
      {counter(
        'queued',
        'Queued',
        stats.queued,
        stats.oldest_queued_at ? (
          <>
            oldest queued <RelativeTime date={stats.oldest_queued_at} tooltip={false} />
          </>
        ) : (
          'nothing waiting'
        ),
      )}
      {counter('sending', 'Sending now', stats.sending, 'claimed by a worker')}
      {counter('failed', 'Failed', stats.failed, 'kept for 90 days', 'danger')}
      {counter(
        'sent',
        'Sent in 24 h',
        stats.sent_last_24h,
        stats.last_sent_at ? (
          <>
            last sent <RelativeTime date={stats.last_sent_at} tooltip={false} />
          </>
        ) : (
          'none yet'
        ),
      )}
    </div>
  )
}

const TONE_CLASS: Record<StatusTone, string> = {
  success: 'text-success',
  neutral: 'text-secondary',
  info: 'text-info',
  danger: 'text-danger',
  muted: 'text-muted',
}

const STATUS_ICON: Record<EmailStatus, ReactNode> = {
  sent: <CircleCheck />,
  queued: <Clock />,
  sending: <Spinner />,
  failed: <CircleAlert />,
  cancelled: <Ban />,
}

function StatusLabel({ status }: { status: EmailStatus }) {
  const { label, tone } = EMAIL_STATUS[status]
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 font-medium [&_svg]:size-3.5',
        TONE_CLASS[tone],
      )}
    >
      <span aria-hidden="true" className="inline-flex">
        {STATUS_ICON[status]}
      </span>
      {label}
    </span>
  )
}

/** "3 of 12 attempts": while it isn't sent, or when it took more than one. */
function attemptsText(email: OutboxEmail): string | null {
  if (email.status === 'sent') {
    return email.attempts > 1 ? `on attempt ${email.attempts.toLocaleString()}` : null
  }
  if (email.attempts === 0 && email.status !== 'failed') return null
  return `${email.attempts} of ${email.max_attempts} ${email.max_attempts === 1 ? 'attempt' : 'attempts'}`
}

function OutboxRow({ email }: { email: OutboxEmail }) {
  const retry = useRetryOutboxEmail()
  // Retry replaces its button with "Queued": focus moves to the row's status, not the page.
  const statusRef = useRef<HTMLDivElement>(null)
  const hint = errorHint(email.last_error)
  const attempts = attemptsText(email)
  const what =
    email.type === 'test' && email.requested_by
      ? `Test email from ${email.requested_by.display_name}`
      : EMAIL_TYPE_LABEL[email.type]
  return (
    <TableRow data-status={email.status}>
      <TableCell primary className="min-w-0">
        <div className="flex min-w-0 flex-col gap-0.5 py-2">
          <span className="truncate font-medium text-primary">{what}</span>
          {email.idea && (
            <span className="truncate text-xs text-muted">
              <span className="tabular-nums">{email.idea.key}</span> · {email.idea.title}
            </span>
          )}
        </div>
      </TableCell>
      <TableCell label="To" className="min-w-0">
        {email.recipient ? (
          <span className="flex min-w-0 items-center gap-2">
            <Avatar
              name={email.recipient.display_name}
              src={email.recipient.avatar_url}
              size="xs"
              decorative
            />
            <span className="truncate">{email.recipient.display_name}</span>
          </span>
        ) : (
          <span className="truncate text-secondary">{email.address_hint ?? '—'}</span>
        )}
      </TableCell>
      <TableCell label="Status" className="min-w-0">
        <div
          ref={statusRef}
          tabIndex={-1}
          data-outbox-status=""
          className="-mx-1 flex min-w-0 flex-col gap-0.5 rounded-sm px-1 py-2"
        >
          <span className="flex flex-wrap items-center gap-x-2">
            <StatusLabel status={email.status} />
            {attempts && <span className="text-xs text-muted tabular-nums">{attempts}</span>}
          </span>
          {email.last_error && (
            <span
              className="text-xs [overflow-wrap:anywhere] text-secondary"
              title={hint ?? undefined}
            >
              {email.last_error}
            </span>
          )}
          {email.status === 'queued' && email.next_attempt_at && email.attempts > 0 && (
            <span className="text-xs text-muted">
              Next try {formatRelative(email.next_attempt_at)}
            </span>
          )}
          {email.status === 'sent' && email.sent_at && (
            <span className="text-xs text-muted">
              Sent <RelativeTime date={email.sent_at} />
            </span>
          )}
        </div>
      </TableCell>
      <TableCell label="Queued" className="text-secondary @3xl:text-right">
        <RelativeTime date={email.created_at} style="short" />
      </TableCell>
      <TableCell className="@3xl:text-right">
        {email.status === 'failed' && !email.retryable && (
          <span className="text-xs whitespace-nowrap text-muted">Too old to send</span>
        )}
        {email.retryable && (
          <Button
            variant="outline"
            size="sm"
            loading={retry.isPending}
            onClick={() => {
              statusRef.current?.focus()
              retry.mutate(email.id)
            }}
            aria-label={`Retry: ${what}${email.recipient ? ` to ${email.recipient.display_name}` : ''}`}
          >
            <RotateCw />
            Retry
          </Button>
        )}
      </TableCell>
    </TableRow>
  )
}
