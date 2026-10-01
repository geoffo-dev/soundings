import { Link } from '@tanstack/react-router'
import { BellRing } from 'lucide-react'
import type { KeyboardEvent, MouseEvent } from 'react'

import type { NotificationItem } from '@/api/types'
import { Avatar } from '@/components/ui/avatar'
import { RelativeTime, useNow } from '@/components/ui/relative-time'
import { NAV_ITEM_ATTRIBUTE } from '@/lib/list-navigation'
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
  /** Mark rows for page-wide j/k navigation (the full page). */
  navItems?: boolean
  /** Level of the day headings: 2 on the page, 3 under the popover's title. */
  headingLevel?: 2 | 3
  className?: string
}

/**
 * The inbox, newest first, grouped by day (Today, Yesterday, Mon 28 Sept): one
 * row per notification with who did it, the idea, a plain sentence and when.
 * Unread rows have a dot and a stronger title (never colour alone: the dot has
 * a label). Rows are links: Enter opens, ↑/↓ move between them.
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
            {group.items.map((item) => (
              <li key={item.id}>
                <InboxRow
                  item={item}
                  now={now}
                  onOpen={onOpen}
                  density={density}
                  navItem={navItems}
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
}: {
  item: NotificationItem
  now: number
  onOpen: (item: NotificationItem) => void
  density: 'comfortable' | 'compact'
  navItem: boolean
}) {
  const unread = item.read_at === null
  const sentence = describeNotification(item, now)
  const link = notificationLink(item)
  const label = `${unread ? 'Unread: ' : ''}${notificationText(item, now)}. ${item.idea.key} ${item.idea.title}`
  return (
    <Link
      to="/ideas/$ideaKey"
      params={{ ideaKey: link.ideaKey }}
      search={link.evaluate ? { evaluate: true } : {}}
      hash={link.hash}
      onClick={(event: MouseEvent) => {
        // Modified clicks open a new tab: still read, but this view stays.
        if (event.defaultPrevented) return
        onOpen(item)
      }}
      data-notification-row=""
      {...(navItem ? { [NAV_ITEM_ATTRIBUTE]: '' } : {})}
      aria-label={label}
      className={cn(
        'group flex items-start gap-3 rounded-md transition-colors duration-100 hover:bg-subtle focus-visible:-outline-offset-2',
        density === 'compact' ? 'px-3 py-2.5' : 'px-3 py-3',
      )}
    >
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
          <RelativeTime
            date={item.created_at}
            style="narrow"
            tooltip={false}
            className="shrink-0 text-xs text-muted"
          />
        </span>
        <span className="text-sm text-secondary">
          {sentence.actor && <span className="font-medium text-primary">{sentence.actor} </span>}
          {sentence.text}
        </span>
        {sentence.quote && (
          <span className="line-clamp-2 text-sm [overflow-wrap:anywhere] text-muted">
            “{sentence.quote}”
          </span>
        )}
      </span>
      <span className="flex w-2 shrink-0 justify-center pt-1.5">
        {unread && <span aria-hidden="true" className="size-2 rounded-full bg-accent" />}
      </span>
    </Link>
  )
}
