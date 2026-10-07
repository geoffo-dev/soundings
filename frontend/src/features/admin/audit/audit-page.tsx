import { ChevronRight, History, KeyRound, ShieldAlert } from 'lucide-react'
import { useCallback, useMemo, useState } from 'react'

import { useAuditEntries } from '@/api/admin'
import type { AuditEntry } from '@/api/types'
import { Avatar } from '@/components/ui/avatar'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'
import { useNow } from '@/components/ui/relative-time'
import { Skeleton, SkeletonGroup } from '@/components/ui/skeleton'
import { WithTooltip } from '@/components/ui/tooltip'
import { calendarDaysBetween, currentLocale, formatDate, formatDateTime } from '@/lib/dates'
import { NAV_ITEM_ATTRIBUTE, useListNavigation } from '@/lib/list-navigation'
import { cn } from '@/lib/utils'

import { AdminPageHeader } from '@/features/admin/settings-frame'
import { usePageVirtualizer } from '@/features/admin/use-page-virtualizer'
import { AuditFilters } from './audit-filters'
import { auditFields, isBreakGlassEntry } from './audit-phrases'
import { hasAuditFilters, toAuditFilters, type AuditSearch } from './audit-search'
import { AuditSentence } from './audit-sentence'

type FeedRow = { kind: 'day'; key: string; label: string } | { kind: 'entry'; entry: AuditEntry }

const ROW_HEIGHT = { day: 40, entry: 60 } as const

const CLEARED: Partial<AuditSearch> = {
  actor: undefined,
  action: undefined,
  project: undefined,
  from: undefined,
  to: undefined,
  target: undefined,
}

/** "Today", "Yesterday", then "Mon 28 Sept" (with the year when it isn't this year). */
export function dayLabel(iso: string, now: number): string {
  const days = calendarDaysBetween(iso, now)
  if (days === 0) return 'Today'
  if (days === 1) return 'Yesterday'
  return formatDate(iso, { now })
}

/** Entries with a day heading before each new day (newest first). */
export function feedRows(entries: AuditEntry[], now: number): FeedRow[] {
  const rows: FeedRow[] = []
  let lastDay = ''
  for (const entry of entries) {
    const date = new Date(entry.created_at)
    const day = `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`
    if (day !== lastDay) {
      rows.push({ kind: 'day', key: `day-${day}`, label: dayLabel(entry.created_at, now) })
      lastDay = day
    }
    rows.push({ kind: 'entry', entry })
  }
  return rows
}

/**
 * Admin settings → Audit log (contract-phase2 §3.11): sign-ins, assignments,
 * evaluations, status changes and admin changes, newest first, each in plain
 * language. Filter by who, what, project, days, or (from a user or group) what
 * it was about; scrolling loads older entries (virtualised). "Details" shows
 * an entry's raw fields.
 */
export function AuditPage({
  search,
  onSearchChange,
}: {
  search: AuditSearch
  /** Merged into the URL's current search. */
  onSearchChange: (patch: Partial<AuditSearch>) => void
}) {
  return (
    <>
      <AdminPageHeader title="Audit log" description="Who did what, newest first." />
      <AuditFilters search={search} onChange={onSearchChange} />
      <AuditFeed search={search} onClear={() => onSearchChange(CLEARED)} />
    </>
  )
}

function AuditFeed({ search, onClear }: { search: AuditSearch; onClear: () => void }) {
  const filters = useMemo(() => toAuditFilters(search), [search])
  const query = useAuditEntries(filters)
  const now = useNow()
  const entries = useMemo(() => query.data?.pages.flatMap((page) => page.items) ?? [], [query.data])
  const rows = useMemo(() => feedRows(entries, now), [entries, now])
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(new Set())
  const { listRef: navRef } = useListNavigation()
  const virtual = usePageVirtualizer({
    count: rows.length,
    estimateSize: (index) => (rows[index]?.kind === 'day' ? ROW_HEIGHT.day : ROW_HEIGHT.entry),
    getItemKey: (index) => {
      const row = rows[index]
      return row ? (row.kind === 'day' ? row.key : row.entry.id) : index
    },
    hasNextPage: query.hasNextPage,
    isFetchingNextPage: query.isFetchingNextPage,
    isError: query.isError,
    fetchNextPage: query.fetchNextPage,
  })
  const { listRef } = virtual
  const containerRef = useCallback(
    (node: HTMLDivElement | null) => {
      listRef(node)
      const cleanup = navRef(node)
      return () => {
        cleanup?.()
        listRef(null)
      }
    },
    [listRef, navRef],
  )

  const toggle = (id: string) =>
    setExpanded((current) => {
      const next = new Set(current)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  if (query.isPending) {
    return (
      <SkeletonGroup label="Loading the audit log" className="flex flex-col">
        <Skeleton className="mb-3 h-3.5 w-20" />
        {Array.from({ length: 7 }, (_, i) => (
          <div key={i} className="flex items-start gap-3 border-b border-subtle py-3">
            <Skeleton className="size-6 rounded-full" />
            <div className="flex flex-1 flex-col gap-1.5">
              <Skeleton className="h-3.5 w-[min(28rem,80%)]" />
              <Skeleton className="h-3 w-32" />
            </div>
          </div>
        ))}
      </SkeletonGroup>
    )
  }

  if (query.isError && entries.length === 0) {
    return (
      <EmptyState
        role="alert"
        size="compact"
        className="rounded-lg border"
        icon={<History />}
        title="Couldn’t load the audit log"
        description="Check your connection and try again."
        action={
          <Button variant="secondary" onClick={() => void query.refetch()}>
            Try again
          </Button>
        }
      />
    )
  }

  if (entries.length === 0) {
    return hasAuditFilters(search) ? (
      <EmptyState
        size="compact"
        className="rounded-lg border"
        icon={<History />}
        title="No entries match these filters"
        description="Try a wider date range or fewer filters."
        action={
          <Button variant="secondary" onClick={onClear}>
            Clear filters
          </Button>
        }
      />
    ) : (
      <EmptyState
        size="compact"
        className="rounded-lg border"
        icon={<History />}
        title="Nothing recorded yet"
        description="Sign-ins and changes appear here as they happen."
      />
    )
  }

  return (
    <section
      aria-label="Audit entries"
      className={cn('transition-opacity duration-150', query.isPlaceholderData && 'opacity-60')}
      aria-busy={query.isPlaceholderData || undefined}
    >
      <div ref={containerRef}>
        {virtual.paddingTop > 0 && (
          <div aria-hidden="true" style={{ height: virtual.paddingTop }} />
        )}
        {virtual.rows.map((item) => {
          const row = rows[item.index]
          if (!row) return null
          return (
            <div key={item.key} ref={virtual.measure} data-index={item.index}>
              {row.kind === 'day' ? (
                <h3
                  className={cn(
                    'pb-1.5 text-xs font-medium text-muted',
                    item.index === 0 ? 'pt-0' : 'pt-5',
                  )}
                >
                  {row.label}
                </h3>
              ) : (
                <AuditRow
                  entry={row.entry}
                  expanded={expanded.has(row.entry.id)}
                  onToggle={() => toggle(row.entry.id)}
                />
              )}
            </div>
          )
        })}
        {virtual.paddingBottom > 0 && (
          <div aria-hidden="true" style={{ height: virtual.paddingBottom }} />
        )}
      </div>
      {query.isFetchingNextPage && (
        <SkeletonGroup label="Loading older entries" className="flex items-start gap-3 py-3">
          <Skeleton className="size-6 rounded-full" />
          <Skeleton className="h-3.5 w-64" />
        </SkeletonGroup>
      )}
      {query.isError && (
        <p role="alert" className="flex items-center justify-center gap-2 py-2 text-sm text-danger">
          Couldn’t load older entries.
          <Button variant="link" size="sm" onClick={() => void query.fetchNextPage()}>
            Try again
          </Button>
        </p>
      )}
      {!query.hasNextPage && entries.length > 20 && (
        <p className="py-4 text-center text-sm text-muted">That’s everything.</p>
      )}
    </section>
  )
}

function ActorMark({ entry }: { entry: AuditEntry }) {
  if (entry.actor) {
    return (
      <Avatar size="sm" name={entry.actor.display_name} src={entry.actor.avatar_url} decorative />
    )
  }
  const denied = entry.action === 'session.sign_in_denied'
  return (
    <span
      aria-hidden="true"
      className={cn(
        'inline-flex size-6 shrink-0 items-center justify-center rounded-full [&_svg]:size-3.5',
        denied ? 'bg-warning-subtle text-warning' : 'bg-subtle text-muted',
      )}
    >
      {denied ? <ShieldAlert /> : <History />}
    </span>
  )
}

function AuditRow({
  entry,
  expanded,
  onToggle,
}: {
  entry: AuditEntry
  expanded: boolean
  onToggle: () => void
}) {
  const sentenceId = `audit-${entry.id}`
  const detailsId = `audit-${entry.id}-details`
  const breakGlass = isBreakGlassEntry(entry)
  const time = new Date(entry.created_at)
  return (
    <div className="border-b border-subtle">
      <div className="flex items-start gap-3 py-2.5">
        <span className="mt-0.5">
          <ActorMark entry={entry} />
        </span>
        <div className="flex min-w-0 flex-1 flex-col gap-0.5">
          <AuditSentence entry={entry} id={sentenceId} />
          <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted">
            <WithTooltip content={formatDateTime(time)}>
              <time dateTime={entry.created_at} className="tabular-nums">
                {new Intl.DateTimeFormat(currentLocale(), { timeStyle: 'short' }).format(time)}
              </time>
            </WithTooltip>
            {entry.project && <span className="truncate">{entry.project.name}</span>}
            {breakGlass && (
              <Badge variant="warning">
                <KeyRound aria-hidden="true" />
                {/* A refused attempt never had a session. */}
                {entry.action === 'session.sign_in_denied'
                  ? 'Break-glass attempt'
                  : 'Break-glass session'}
              </Badge>
            )}
          </p>
        </div>
        {/* A quiet chevron at the row's end (a word on every row was noise; UX review p4). */}
        <Button
          variant="ghost"
          size="icon-sm"
          className="shrink-0 text-muted"
          aria-expanded={expanded}
          aria-controls={detailsId}
          aria-describedby={sentenceId}
          onClick={onToggle}
          {...{ [NAV_ITEM_ATTRIBUTE]: '' }}
        >
          <ChevronRight
            aria-hidden="true"
            className={cn('transition-transform duration-150', expanded && 'rotate-90')}
          />
          <span className="sr-only">Details</span>
        </Button>
      </div>
      {expanded && (
        <dl
          id={detailsId}
          className="mb-3 ml-9 grid grid-cols-[minmax(6rem,auto)_minmax(0,1fr)] gap-x-4 gap-y-1 rounded-md bg-subtle px-3 py-2.5 font-mono text-xs"
        >
          {auditFields(entry).map((field) => (
            <div key={field.label} className="contents">
              <dt className="text-muted">{field.label}</dt>
              <dd className="break-all text-secondary">{field.value}</dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  )
}
