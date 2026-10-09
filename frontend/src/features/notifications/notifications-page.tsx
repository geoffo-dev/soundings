import { Link } from '@tanstack/react-router'
import { BellOff, CheckCheck, CloudOff, Settings2 } from 'lucide-react'

import {
  useMarkAllNotificationsRead,
  useMarkNotificationRead,
  useNotifications,
  useNotificationSummary,
} from '@/api/notifications'
import type { NotificationItem } from '@/api/types'
import { Page, PageHeader } from '@/components/layout/page'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'
import { SegmentedControl } from '@/components/ui/segmented-control'
import { Skeleton, SkeletonGroup } from '@/components/ui/skeleton'
import { useListNavigation } from '@/lib/list-navigation'
import { rememberRow, useReturnToRow } from '@/lib/return-to-row'

import { InboxList } from './inbox-list'
import { isKnownNotification, unreadBadge } from './notification-text'

/**
 * /notifications (contract-phase3 §3.2): the whole inbox, newest first, grouped
 * by day; All or Unread. Opening a notification marks it read; "Mark all read"
 * clears the rest. j/k move between rows, Enter opens.
 */
export function NotificationsPage({
  unread,
  onUnreadChange,
}: {
  unread: boolean
  onUnreadChange: (unread: boolean) => void
}) {
  const summary = useNotificationSummary()
  const list = useNotifications({ unread })
  const markRead = useMarkNotificationRead()
  const markAll = useMarkAllNotificationsRead()
  const { listRef } = useListNavigation()
  const unreadCount = summary.data?.unread_count ?? 0
  const items = (list.data?.items ?? []).filter(isKnownNotification)

  const open = (item: NotificationItem) => {
    // Back from the idea: focus returns to this row, not the top of the page.
    rememberRow('notifications', item.id)
    if (item.read_at === null) markRead.mutate(item.id)
  }
  useReturnToRow('notifications', items.length > 0)

  return (
    <Page>
      <PageHeader
        title="Notifications"
        description="Updates about ideas you own, evaluate, research, watch or are mentioned in."
        actions={
          <>
            <Button variant="ghost" size="md" asChild>
              <Link to="/settings/notifications">
                <Settings2 />
                Email preferences
              </Link>
            </Button>
            <Button
              variant="secondary"
              // Not `disabled`: focus would fall to the page when it empties the list.
              aria-disabled={unreadCount === 0 || undefined}
              onClick={() => {
                if (unreadCount > 0) markAll(unreadCount)
              }}
            >
              <CheckCheck />
              Mark all read
            </Button>
          </>
        }
      />
      <div className="flex flex-col gap-4">
        <SegmentedControl
          aria-label="Show"
          value={unread ? 'unread' : 'all'}
          onValueChange={(value) => onUnreadChange(value === 'unread')}
          options={[
            { value: 'all', label: 'All' },
            {
              value: 'unread',
              label: unreadCount > 0 ? `Unread (${unreadBadge(unreadCount) ?? 0})` : 'Unread',
            },
          ]}
        />
        {list.isPending ? (
          <SkeletonGroup label="Loading notifications" className="flex flex-col gap-5 px-3 py-2">
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="flex items-start gap-3">
                <Skeleton className="size-7 rounded-full" />
                <div className="flex flex-1 flex-col gap-2 pt-0.5">
                  <Skeleton className="h-3.5 w-2/3" />
                  <Skeleton className="h-3 w-1/2" />
                </div>
              </div>
            ))}
          </SkeletonGroup>
        ) : list.isError ? (
          <EmptyState
            role="alert"
            size="compact"
            className="rounded-lg border"
            icon={<CloudOff />}
            title="Couldn’t load your notifications"
            description="Check your connection and try again."
            action={
              <Button variant="secondary" onClick={() => void list.refetch()}>
                Try again
              </Button>
            }
          />
        ) : items.length === 0 ? (
          <EmptyState
            headingLevel={2}
            className="rounded-lg border"
            icon={unread ? <CheckCheck /> : <BellOff />}
            title={unread ? 'You’re all caught up' : 'No notifications yet'}
            description={
              unread
                ? 'Nothing unread. Earlier notifications are under All.'
                : 'When someone asks for your view, mentions you, or moves an idea you own, evaluate or watch, it shows up here.'
            }
            action={
              unread ? (
                <Button variant="secondary" onClick={() => onUnreadChange(false)}>
                  Show all
                </Button>
              ) : (
                <Button variant="secondary" asChild>
                  <Link to="/">Go to My work</Link>
                </Button>
              )
            }
          />
        ) : (
          <div ref={listRef} className="-mx-3 flex max-w-3xl flex-col gap-2">
            <InboxList items={items} onOpen={open} navItems headingLevel={2} />
            {list.hasNextPage && (
              <Button
                variant="ghost"
                size="sm"
                className="self-start text-muted"
                loading={list.isFetchingNextPage}
                onClick={() => void list.fetchNextPage()}
              >
                Load older notifications
              </Button>
            )}
          </div>
        )}
      </div>
    </Page>
  )
}
