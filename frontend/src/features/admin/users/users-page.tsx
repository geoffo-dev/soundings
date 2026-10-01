import { Link } from '@tanstack/react-router'
import { CircleDashed, Link2Off, ShieldCheck, UserPlus, UsersRound } from 'lucide-react'
import { useCallback, useRef, useState, type ReactNode } from 'react'

import { useAdminUsers } from '@/api/admin'
import type { AdminUserSummary } from '@/api/types'
import { Avatar } from '@/components/ui/avatar'
import { Button } from '@/components/ui/button'
import { Command, CommandGroup, CommandList } from '@/components/ui/command'
import { EmptyState } from '@/components/ui/empty-state'
import { FilterChip } from '@/components/ui/filter-chip'
import { FilterMenu, FilterMenuOption } from '@/components/ui/filter-menu'
import { RelativeTime } from '@/components/ui/relative-time'
import { Skeleton, SkeletonGroup } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { useCurrentUser } from '@/features/auth/current-user'
import { NAV_ITEM_ATTRIBUTE, useListNavigation } from '@/lib/list-navigation'
import { ROW_ID_ATTRIBUTE } from '@/lib/return-to-row'
import { useShortcut } from '@/lib/shortcuts'
import { cn } from '@/lib/utils'

import { SearchField } from '@/features/admin/search-field'
import { AdminPageHeader } from '@/features/admin/settings-frame'
import { usePageVirtualizer } from '@/features/admin/use-page-virtualizer'
import { AddUserDialog } from './add-user-dialog'
import { UserBadges } from './user-badges'
import { hasUserFilters, toUserFilters, type UsersSearch } from './users-search'

const ROW_HEIGHT = { table: 52, card: 76 } as const
const CARDS_BELOW_PX = 768

/**
 * Admin settings → Users (contract-phase2 §3.4): everyone who can sign in,
 * searchable and filterable, virtualised (only the rows in view render; pages
 * load as you scroll). A row opens the user's sheet (`/settings/users/$userId`,
 * the child route rendered in `children`). "Add user" pre-creates someone so the
 * right account is linked at their first SSO sign-in.
 */
export function UsersPage({
  search,
  onSearchChange,
  children,
}: {
  search: UsersSearch
  /** Merged into the URL's current search (so a late debounced search doesn't undo a filter). */
  onSearchChange: (patch: Partial<UsersSearch>) => void
  children?: ReactNode
}) {
  const [adding, setAdding] = useState(false)
  const searchRef = useRef<HTMLInputElement>(null)
  useShortcut('focusFilters', () => searchRef.current?.focus())
  const set = onSearchChange

  return (
    <>
      <AdminPageHeader
        title="Users"
        description="Everyone who can sign in."
        actions={
          <Button variant="primary" onClick={() => setAdding(true)}>
            <UserPlus />
            Add user
          </Button>
        }
      />
      <div
        role="group"
        aria-label="Filters"
        className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center sm:gap-1.5"
      >
        <SearchField
          value={search.q}
          onChange={(q) => set({ q })}
          label="Search users"
          placeholder="Search name or email…"
          inputRef={searchRef}
        />
        <div className="flex flex-wrap items-center gap-1.5">
          <FilterMenu
            label="Status"
            icon={<CircleDashed aria-hidden="true" />}
            value={
              search.status === 'active'
                ? 'Active'
                : search.status === 'deactivated'
                  ? 'Deactivated'
                  : undefined
            }
            onClear={() => set({ status: undefined })}
            menuClassName="w-48"
          >
            {(close) => (
              <Command>
                <CommandList aria-label="Statuses">
                  <CommandGroup>
                    {(['active', 'deactivated'] as const).map((status) => (
                      <FilterMenuOption
                        key={status}
                        value={status}
                        checked={search.status === status}
                        onSelect={() => {
                          set({ status: search.status === status ? undefined : status })
                          close()
                        }}
                      >
                        {status === 'active' ? 'Active' : 'Deactivated'}
                      </FilterMenuOption>
                    ))}
                  </CommandGroup>
                </CommandList>
              </Command>
            )}
          </FilterMenu>
          <FilterChip
            pressed={Boolean(search.admins)}
            onPressedChange={(on) => set({ admins: on ? true : undefined })}
            icon={<ShieldCheck aria-hidden="true" />}
          >
            Platform admins
          </FilterChip>
          <FilterChip
            pressed={Boolean(search.unlinked)}
            onPressedChange={(on) => set({ unlinked: on ? true : undefined })}
            icon={<Link2Off aria-hidden="true" />}
          >
            SSO not linked
          </FilterChip>
        </div>
      </div>
      <UsersList
        search={search}
        onClear={() =>
          onSearchChange({
            q: undefined,
            status: undefined,
            admins: undefined,
            unlinked: undefined,
          })
        }
      />
      <AddUserDialog open={adding} onOpenChange={setAdding} />
      {children}
    </>
  )
}

function UsersList({ search, onClear }: { search: UsersSearch; onClear: () => void }) {
  const me = useCurrentUser()
  const query = useAdminUsers(toUserFilters(search))
  const users = query.data?.pages.flatMap((page) => page.items) ?? []
  const [cards, setCards] = useState(false)
  const { listRef: navRef } = useListNavigation()
  const virtual = usePageVirtualizer({
    count: users.length,
    estimateSize: () => (cards ? ROW_HEIGHT.card : ROW_HEIGHT.table),
    getItemKey: (index) => users[index]?.id ?? index,
    hasNextPage: query.hasNextPage,
    isFetchingNextPage: query.isFetchingNextPage,
    isError: query.isError,
    fetchNextPage: query.fetchNextPage,
  })
  const { listRef } = virtual
  const containerRef = useCallback(
    (node: HTMLDivElement | null) => {
      listRef(node)
      const cleanupNav = navRef(node)
      if (!node || typeof ResizeObserver === 'undefined') return cleanupNav
      // Rows become cards under 48rem (Table's container-cards): estimate their height.
      const observer = new ResizeObserver(([entry]) => {
        if (entry) setCards(entry.contentRect.width < CARDS_BELOW_PX)
      })
      observer.observe(node)
      return () => {
        observer.disconnect()
        cleanupNav?.()
        listRef(null)
      }
    },
    [listRef, navRef],
  )

  if (query.isPending) {
    return (
      <SkeletonGroup label="Loading users" className="overflow-hidden rounded-lg border">
        {Array.from({ length: 6 }, (_, i) => (
          <div
            key={i}
            className="flex h-13 items-center gap-3 border-b border-subtle px-4 last:border-0"
          >
            <Skeleton className="size-7 rounded-full" />
            <div className="flex flex-1 flex-col gap-1.5">
              <Skeleton className="h-3.5 w-40" />
              <Skeleton className="h-3 w-56" />
            </div>
            <Skeleton className="hidden h-5 w-24 sm:block" />
            <Skeleton className="hidden h-3 w-16 sm:block" />
          </div>
        ))}
      </SkeletonGroup>
    )
  }

  if (query.isError && users.length === 0) {
    return (
      <EmptyState
        role="alert"
        size="compact"
        className="rounded-lg border"
        icon={<UsersRound />}
        title="Couldn’t load users"
        description="Check your connection and try again."
        action={
          <Button variant="secondary" onClick={() => void query.refetch()}>
            Try again
          </Button>
        }
      />
    )
  }

  if (users.length === 0) {
    return hasUserFilters(search) ? (
      <EmptyState
        size="compact"
        className="rounded-lg border"
        icon={<UsersRound />}
        title="No users match"
        description="Try another name or email, or clear the filters."
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
        icon={<UsersRound />}
        title="No users yet"
        description="Add the people who should sign in first, or turn on auto-create in the SSO settings."
      />
    )
  }

  return (
    <div
      ref={containerRef}
      className={cn(
        'overflow-hidden rounded-lg border transition-opacity duration-150',
        query.isPlaceholderData && 'opacity-60',
      )}
      aria-busy={query.isPlaceholderData || undefined}
    >
      <Table
        mobile="container-cards"
        cardFields="inline"
        aria-label="Users"
        className="@3xl:table-fixed"
      >
        <TableHeader>
          <TableRow>
            <TableHead>Name</TableHead>
            <TableHead className="w-52">Status</TableHead>
            <TableHead className="w-36">SSO account</TableHead>
            <TableHead className="w-28 text-right">Last active</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {virtual.paddingTop > 0 && <Spacer height={virtual.paddingTop} />}
          {virtual.rows.map((row) => {
            const user = users[row.index]
            if (!user) return null
            return (
              <UserRow
                key={row.key}
                user={user}
                index={row.index}
                isMe={user.id === me.id}
                measure={virtual.measure}
              />
            )
          })}
          {virtual.paddingBottom > 0 && <Spacer height={virtual.paddingBottom} />}
        </TableBody>
      </Table>
      {query.isFetchingNextPage && (
        <SkeletonGroup label="Loading more users" className="border-t border-subtle">
          <div className="flex h-13 items-center gap-3 px-4">
            <Skeleton className="size-7 rounded-full" />
            <Skeleton className="h-3.5 w-48" />
          </div>
        </SkeletonGroup>
      )}
      {query.isError && (
        <p
          role="alert"
          className="flex items-center justify-center gap-2 border-t border-subtle py-2 text-sm text-danger"
        >
          Couldn’t load more users.
          <Button variant="link" size="sm" onClick={() => void query.fetchNextPage()}>
            Try again
          </Button>
        </p>
      )}
    </div>
  )
}

function Spacer({ height }: { height: number }) {
  return (
    <tr aria-hidden="true" className="@max-3xl:block">
      <td colSpan={4} className="p-0 @max-3xl:block" style={{ height }} />
    </tr>
  )
}

function UserRow({
  user,
  index,
  isMe,
  measure,
}: {
  user: AdminUserSummary
  index: number
  isMe: boolean
  measure: (node: Element | null) => void
}) {
  return (
    <TableRow
      ref={measure}
      data-index={index}
      className={cn('relative @3xl:h-13', !user.is_active && 'text-muted')}
    >
      <TableCell primary className="min-w-0">
        <Link
          to="/settings/users/$userId"
          params={{ userId: user.id }}
          search={true}
          {...{ [NAV_ITEM_ATTRIBUTE]: '', [ROW_ID_ATTRIBUTE]: user.id }}
          className={cn(
            'flex min-w-0 items-center gap-3 outline-none',
            // The whole row is the link; the focus ring outlines the row.
            'after:absolute after:inset-0 after:rounded-sm',
            'focus-visible:after:outline-2 focus-visible:after:-outline-offset-2 focus-visible:after:outline-focus',
          )}
        >
          <Avatar
            size="sm"
            name={user.display_name}
            src={user.avatar_url}
            isAgent={user.is_service_account}
            decorative
            className={cn(!user.is_active && 'opacity-60')}
          />
          <span className="flex min-w-0 flex-col">
            <span
              className={cn(
                'truncate font-medium',
                user.is_active ? 'text-primary' : 'text-secondary',
              )}
            >
              {user.display_name}
              {isMe && <span className="font-normal text-muted"> (you)</span>}
            </span>
            <span className="truncate text-xs text-muted">{user.email}</span>
          </span>
        </Link>
      </TableCell>
      <TableCell label="Status">
        {user.is_active &&
        !user.is_platform_admin &&
        !user.is_break_glass &&
        !user.is_service_account ? (
          <span className="text-sm text-muted">Active</span>
        ) : (
          <UserBadges user={user} />
        )}
      </TableCell>
      <TableCell label="SSO account">
        {user.has_identity ? (
          <CellText table="Linked" card="SSO linked" className="text-secondary" />
        ) : user.is_break_glass || user.is_service_account ? (
          <CellText table="Never" card="No SSO" />
        ) : (
          <CellText table="Not linked yet" card="SSO not linked" />
        )}
      </TableCell>
      <TableCell label="Last active" className="@3xl:text-right">
        {user.last_seen_at ? (
          <span className="text-sm text-secondary">
            <span className="@3xl:hidden">Last active </span>
            <RelativeTime date={user.last_seen_at} style="short" />
          </span>
        ) : (
          <CellText table="Never" card="Never active" />
        )}
      </TableCell>
    </TableRow>
  )
}

/** A cell's words in the table, and fuller ones for the card's meta line (no column label there). */
function CellText({ table, card, className }: { table: string; card: string; className?: string }) {
  return (
    <span className={cn('text-sm text-muted', className)}>
      <span className="@max-3xl:hidden">{table}</span>
      <span className="@3xl:hidden">{card}</span>
    </span>
  )
}
