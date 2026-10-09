import { Link } from '@tanstack/react-router'
import { BellRing } from 'lucide-react'
import type { KeyboardEvent, MouseEvent } from 'react'

import type { NotificationItem } from '@/api/types'
import { Avatar } from '@/components/ui/avatar'
import { RelativeTime, useNow } from '@/components/ui/relative-time'
import { NAV_ITEM_ATTRIBUTE } from '@/lib/list-navigation'
import { ROW_ID_ATTRIBUTE } from '@/lib/return-to-row'
import { cn } from '@/lib/utils'

import {
  describeNotification,
  groupByDay,
  notificationLink,
  notificationText,
} from './notification-text'

export interface InboxListProps {
  items: NotificationItem[]
  /** Called when an item is opened (before navigating): mark it read, close the popover. */
  onOpen: (item: NotificationItem) => void
  /** Popover: tighter padding. */
  density?: 'comfortable' | 'compact'
  /** Mark rows for page-wide j/k navigation and focus return (the full page). */
  navItems?: boolean
  /** Level of the day headings: 2 on the page, 3 under the popover's title. */
  headingLevel?: 2 | 3
  className?: string
}

/**
 * The inbox, newest first, grouped by day (Today, Yesterday, Mon 28 Sept): one
 * row per notification with who did it, the idea, a plain sentence and when.
 * Consecutive notifications about the same idea share its title (shown once,
 * on the first). Unread rows have a dot and a stronger title (never colour
 * alone: the dot has a label). Rows are links: Enter opens, ↑/↓ move between
 * them.
 */
export function InboxList({
  items,
  onOpen,
  density = 'comfortable',
  navItems = false,
  headingLevel = 3,
  className,
}: InboxListProps) {
  const now = useNow()
  const Heading = `h${headingLevel}` as const
  const groups = groupByDay(items, now)

  // ↑/↓ between rows (inside a popover the page-wide j/k is off).
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return
    const rows = [...event.currentTarget.querySelectorAll<HTMLElement>('[data-notification-row]')]
    const index = rows.findIndex((row) => row === document.activeElement)
    if (index === -1) return
    event.preventDefault()
    const next =
      rows[
        event.key === 'ArrowDown' ? Math.min(rows.length - 1, index + 1) : Math.max(0, index - 1)
      ]
    next?.focus()
    next?.scrollIntoView({ block: 'nearest' })
  }

  return (
    // eslint-disable-next-line jsx-a11y/no-static-element-interactions -- arrow keys between the links inside
    <div className={cn('flex flex-col', className)} onKeyDown={onKeyDown}>
      {groups.map((group) => (
        <section key={group.key} aria-labelledby={`inbox-day-${group.key}`}>
          <Heading
            id={`inbox-day-${group.key}`}
            className={cn(
              'text-xs font-medium text-muted',
              density === 'compact' ? 'px-3 pt-3 pb-1' : 'px-3 pt-4 pb-1',
            )}
          >
            {group.label}
          </Heading>
          <ul className="flex flex-col">
            {group.items.map((item, index) => (
              <li key={item.id}>
                <InboxRow
                  item={item}
                  now={now}
                  onOpen={onOpen}
                  density={density}
                  navItem={navItems}
                  sameIdea={group.items[index - 1]?.idea.id === item.idea.id}
                />
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  )
}

function InboxRow({
  item,
  now,
  onOpen,
  density,
  navItem,
  sameIdea,
}: {
  item: NotificationItem
  now: number
  onOpen: (item: NotificationItem) => void
  density: 'comfortable' | 'compact'
  navItem: boolean
  /** The row above is about the same idea: its title isn't repeated. */
  sameIdea: boolean
}) {
  const unread = item.read_at === null
  const sentence = describeNotification(item, now)
  const link = notificationLink(item)
  const label = `${unread ? 'Unread: ' : ''}${notificationText(item, now)}. ${item.idea.key} ${item.idea.title}`
  // Always on the first line, so a short sentence never wraps around it.
  const time = (
    <RelativeTime
      date={item.created_at}
      style="narrow"
      tooltip={false}
      className="shrink-0 text-xs text-muted"
    />
  )
  const what = (
    <span className="min-w-0 flex-1 text-sm text-pretty text-secondary">
      {sentence.actor && <span className="font-medium text-primary">{sentence.actor} </span>}
      <SentenceText text={sentence.text} keepTogether={sentence.keepTogether} />
    </span>
  )
  return (
    <Link
      to="/ideas/$ideaKey"
      params={{ ideaKey: link.ideaKey }}
      search={link.evaluate ? { evaluate: true } : link.research ? { research: true } : {}}
      hash={link.hash}
      onClick={(event: MouseEvent) => {
        // Modified clicks open a new tab: still read, but this view stays.
        if (event.defaultPrevented) return
        onOpen(item)
      }}
      data-notification-row=""
      {...(navItem ? { [NAV_ITEM_ATTRIBUTE]: '', [ROW_ID_ATTRIBUTE]: item.id } : {})}
      aria-label={label}
      data-same-idea={sameIdea || undefined}
      className={cn(
        'group flex items-start gap-3 rounded-md px-3 transition-colors duration-100 hover:bg-subtle focus-visible:-outline-offset-2',
        density === 'compact' ? 'pb-2.5' : 'pb-3',
        // Under the same idea's row: closer, so the two read as one thread.
        sameIdea ? 'pt-0.5' : density === 'compact' ? 'pt-2.5' : 'pt-3',
      )}
    >
      {/* Unread: a dot at the row's start, beside what it marks (not across the page). */}
      <span className="-mx-1.5 flex w-2 shrink-0 justify-center self-center">
        {unread && <span aria-hidden="true" className="size-2 rounded-full bg-accent" />}
      </span>
      {item.actor ? (
        <Avatar name={item.actor.display_name} src={item.actor.avatar_url} size="md" decorative />
      ) : (
        <span
          aria-hidden="true"
          className="flex size-7 shrink-0 items-center justify-center rounded-full bg-subtle text-muted"
        >
          <BellRing className="size-3.5" />
        </span>
      )}
      <span className="flex min-w-0 flex-1 flex-col gap-0.5">
        {sameIdea ? (
          <span className="flex min-w-0 items-baseline gap-2">
            {what}
            {time}
          </span>
        ) : (
          <>
            <span className="flex min-w-0 items-baseline gap-2">
              <span className="shrink-0 text-xs font-medium text-muted tabular-nums">
                {item.idea.key}
              </span>
              <span
                className={cn(
                  'min-w-0 flex-1 truncate text-sm',
                  unread ? 'font-semibold text-primary' : 'font-medium text-secondary',
                )}
              >
                {item.idea.title}
              </span>
              {time}
            </span>
            {what}
          </>
        )}
        {sentence.quote && (
          <span className="line-clamp-2 text-sm [overflow-wrap:anywhere] text-muted">
            “{sentence.quote}”
          </span>
        )}
      </span>
    </Link>
  )
}

/** The sentence, with its due date kept on one line ("due Sat, 3 Oct", never "Sat, / 3 Oct"). */
function SentenceText({ text, keepTogether }: { text: string; keepTogether?: string }) {
  if (!keepTogether || !text.endsWith(keepTogether)) return text
  return (
    <>
      {text.slice(0, -keepTogether.length)}
      <span className="whitespace-nowrap">{keepTogether}</span>
    </>
  )
}
