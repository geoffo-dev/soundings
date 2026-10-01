import { Link } from '@tanstack/react-router'
import { Bell, BellOff, CheckCheck, CloudOff, Settings2 } from 'lucide-react'
import { useState } from 'react'

import {
  useMarkAllNotificationsRead,
  useMarkNotificationRead,
  useNotifications,
  useNotificationSummary,
} from '@/api/notifications'
import type { NotificationItem } from '@/api/types'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { SegmentedControl } from '@/components/ui/segmented-control'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetTitle,
  SheetTrigger,
} from '@/components/ui/sheet'
import { Skeleton, SkeletonGroup } from '@/components/ui/skeleton'
import { WithTooltip } from '@/components/ui/tooltip'
import { SM_UP, useMediaQuery } from '@/lib/media'
import { SHORTCUTS } from '@/lib/shortcuts'
import { cn } from '@/lib/utils'

import { InboxList } from './inbox-list'
import { isKnownNotification, unreadBadge } from './notification-text'

/** How many notifications the bell shows before "See all". */
const PANEL_LIMIT = 20

/**
 * The bell in the top bar (contract-phase3 §3.2): the unread count (polled
 * about once a minute and on focus), and the latest notifications in a
 * popover (desktop) or a full-height sheet (phones). "g i" opens the full page.
 */
export function NotificationBell() {
  const summary = useNotificationSummary()
  const wide = useMediaQuery(SM_UP)
  const [open, setOpen] = useState(false)
  const count = summary.data?.unread_count ?? 0
  const badge = unreadBadge(count)
  const label =
    count === 0 ? 'Notifications' : `Notifications, ${count > 99 ? 'more than 99' : count} unread`

  const trigger = (
    <Button
      variant="ghost"
      size="icon-sm"
      aria-label={label}
      className="relative"
      data-testid="notification-bell"
    >
      <Bell />
      {badge && (
        <span
          aria-hidden="true"
          className="absolute -top-1 -right-1 inline-flex h-4 min-w-4 items-center justify-center rounded-full bg-accent px-1 text-xs leading-none font-semibold text-accent-foreground tabular-nums ring-2 ring-surface"
        >
          {badge}
        </span>
      )}
    </Button>
  )

  const close = () => setOpen(false)

  if (!wide) {
    return (
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetTrigger asChild>{trigger}</SheetTrigger>
        <SheetContent side="right" size="md" className="gap-0">
          <InboxPanel variant="sheet" onDone={close} unreadCount={count} />
        </SheetContent>
      </Sheet>
    )
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <WithTooltip content="Notifications" shortcut={SHORTCUTS.goToNotifications.keys}>
        <PopoverTrigger asChild>{trigger}</PopoverTrigger>
      </WithTooltip>
      <PopoverContent
        align="end"
        aria-label="Notifications"
        className="flex max-h-popover-tall w-md flex-col p-0"
      >
        <InboxPanel variant="popover" onDone={close} unreadCount={count} />
      </PopoverContent>
    </Popover>
  )
}

function InboxPanel({
  variant,
  onDone,
  unreadCount,
}: {
  variant: 'popover' | 'sheet'
  /** Close the popover or sheet (after opening an item or a link). */
  onDone: () => void
  unreadCount: number
}) {
  const [filter, setFilter] = useState<'all' | 'unread'>('all')
  const list = useNotifications({ unread: filter === 'unread' })
  const markRead = useMarkNotificationRead()
  const markAll = useMarkAllNotificationsRead()
  const items = (list.data?.items ?? []).filter(isKnownNotification).slice(0, PANEL_LIMIT)

  const open = (item: NotificationItem) => {
    if (item.read_at === null) markRead.mutate(item.id)
    onDone()
  }

  const Title = variant === 'sheet' ? SheetTitle : 'h2'
  return (
    <>
      <div
        className={cn(
          'flex shrink-0 flex-col gap-2 border-b border-subtle',
          variant === 'sheet' ? 'px-4 pt-3 pb-3' : 'px-3 pt-3 pb-2.5',
        )}
      >
        {/* In the sheet, only the title row leaves room for its close button. */}
        <div className={cn('flex items-center gap-2', variant === 'sheet' && 'pr-10')}>
          <Title className="mr-auto text-base font-semibold text-primary">Notifications</Title>
          <WithTooltip content="Email preferences">
            <Button variant="ghost" size="icon-sm" asChild>
              <Link to="/settings/notifications" onClick={onDone} aria-label="Email preferences">
                <Settings2 />
              </Link>
            </Button>
          </WithTooltip>
        </div>
        {variant === 'sheet' && (
          <SheetDescription className="sr-only">
            Updates about ideas you own, evaluate, watch or are mentioned in.
          </SheetDescription>
        )}
        <div className="flex items-center gap-2">
          <SegmentedControl
            size="sm"
            aria-label="Show"
            value={filter}
            onValueChange={setFilter}
            options={[
              { value: 'all', label: 'All' },
              {
                value: 'unread',
                label: unreadCount > 0 ? `Unread (${unreadBadge(unreadCount) ?? 0})` : 'Unread',
              },
            ]}
          />
          <Button
            variant="ghost"
            size="sm"
            className="ml-auto"
            // Not `disabled`: focus would fall to the page when it empties the list.
            aria-disabled={unreadCount === 0 || undefined}
            onClick={() => {
              if (unreadCount > 0) markAll(unreadCount)
            }}
          >
            <CheckCheck />
            Mark all read
          </Button>
        </div>
      </div>

      {/* A plain scroller: Radix ScrollArea's table layout would defeat `truncate`. */}
      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain">
        {list.isPending ? (
          <SkeletonGroup label="Loading notifications" className="flex flex-col gap-4 px-3 py-4">
            {[0, 1, 2].map((i) => (
              <div key={i} className="flex items-start gap-3">
                <Skeleton className="size-7 rounded-full" />
                <div className="flex flex-1 flex-col gap-2 pt-0.5">
                  <Skeleton className="h-3.5 w-3/4" />
                  <Skeleton className="h-3 w-1/2" />
                </div>
              </div>
            ))}
          </SkeletonGroup>
        ) : list.isError ? (
          <EmptyState
            role="alert"
            size="compact"
            icon={<CloudOff />}
            title="Couldn’t load your notifications"
            description="Check your connection and try again."
            action={
              <Button size="sm" onClick={() => void list.refetch()}>
                Try again
              </Button>
            }
          />
        ) : items.length === 0 ? (
          <EmptyState
            size="compact"
            icon={filter === 'unread' ? <CheckCheck /> : <BellOff />}
            title={filter === 'unread' ? 'You’re all caught up' : 'No notifications yet'}
            description={
              filter === 'unread'
                ? 'Nothing unread. Older notifications are under All.'
                : 'When someone asks for your view, mentions you or moves an idea you follow, it shows up here.'
            }
          />
        ) : (
          <InboxList items={items} onOpen={open} density="compact" className="pb-1" />
        )}
      </div>

      <div className="flex shrink-0 items-center justify-center border-t border-subtle p-1.5">
        <Button variant="ghost" size="sm" className="w-full" asChild>
          <Link
            to="/notifications"
            search={filter === 'unread' ? { unread: true } : {}}
            onClick={onDone}
          >
            See all notifications
          </Link>
        </Button>
      </div>
    </>
  )
}
