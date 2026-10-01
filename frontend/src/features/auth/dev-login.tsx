import { useNavigate } from '@tanstack/react-router'
import { ArrowRight, CloudOff, Search } from 'lucide-react'
import { useState } from 'react'

import { useDevLogin, useDevUsers } from '@/api/auth'
import type { CurrentUser } from '@/api/types'
import { Avatar } from '@/components/ui/avatar'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'
import { Input } from '@/components/ui/input'
import { Skeleton, SkeletonGroup } from '@/components/ui/skeleton'
import { Spinner } from '@/components/ui/spinner'
import { NAV_ITEM_ATTRIBUTE, useListNavigation } from '@/lib/list-navigation'
import { cn } from '@/lib/utils'

import { safeNextPath } from './session'

const FILTER_FROM = 7

/**
 * Development sign-in (`SOUNDINGS_DEV_LOGIN_ENABLED`, never in production): pick
 * a person from `list_dev_users`. Below the SSO button when both are on.
 */
export function DevLogin({
  next,
  focusOnLoad = false,
  headingId,
}: {
  next?: string
  /** Focus the filter on load (only when this is the one way to sign in). */
  focusOnLoad?: boolean
  /** The heading that names the list (the section's h2). */
  headingId: string
}) {
  const navigate = useNavigate()
  const users = useDevUsers()
  const login = useDevLogin()
  const [filter, setFilter] = useState('')
  const { listRef, focusFirst } = useListNavigation()

  const visible = (users.data ?? []).filter((user) => {
    const q = filter.trim().toLowerCase()
    return !q || user.display_name.toLowerCase().includes(q) || user.email.toLowerCase().includes(q)
  })

  const signIn = (user: CurrentUser) => {
    login.mutate(user.id, {
      onSuccess: () => void navigate({ to: safeNextPath(next), replace: true }),
    })
  }

  if (users.isPending) {
    return (
      <SkeletonGroup label="Loading people" className="flex flex-col gap-1">
        {[0, 1, 2, 3, 4].map((i) => (
          <div key={i} className="flex h-14 items-center gap-3 px-2">
            <Skeleton className="size-9 rounded-full" />
            <div className="flex flex-1 flex-col gap-1.5">
              <Skeleton className="h-3.5 w-32" />
              <Skeleton className="h-3 w-48" />
            </div>
          </div>
        ))}
      </SkeletonGroup>
    )
  }

  if (users.isError) {
    return (
      <EmptyState
        role="alert"
        size="compact"
        icon={<CloudOff />}
        title="We couldn’t load the people to sign in as"
        description="Check your connection and try again."
        action={
          <Button variant="outline" onClick={() => void users.refetch()}>
            Try again
          </Button>
        }
      />
    )
  }

  return (
    <>
      {users.data.length >= FILTER_FROM && (
        <Input
          aria-label="Filter people"
          placeholder="Filter by name or email"
          startIcon={<Search />}
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && visible[0]) signIn(visible[0])
            if (event.key === 'ArrowDown') {
              event.preventDefault()
              focusFirst()
            }
          }}
          // Focused only when picking a person is the way to sign in.
          // eslint-disable-next-line jsx-a11y/no-autofocus
          autoFocus={focusOnLoad}
        />
      )}
      {visible.length === 0 ? (
        <p className="px-1 py-6 text-center text-sm text-muted">Nobody matches “{filter}”.</p>
      ) : (
        <ul ref={listRef} aria-labelledby={headingId} className="-mx-1 flex flex-col gap-0.5 p-1">
          {visible.map((user) => {
            const pending = login.isPending && login.variables === user.id
            return (
              <li key={user.id}>
                <button
                  type="button"
                  {...{ [NAV_ITEM_ATTRIBUTE]: '' }}
                  onClick={() => signIn(user)}
                  disabled={login.isPending}
                  aria-busy={pending || undefined}
                  className={cn(
                    'group flex min-h-14 w-full items-center gap-3 rounded-lg px-2 py-2 text-left',
                    'transition-colors duration-100 hover:bg-subtle focus-visible:bg-subtle',
                    'disabled:cursor-wait',
                  )}
                >
                  <Avatar name={user.display_name} src={user.avatar_url} size="lg" decorative />
                  <span className="flex min-w-0 flex-1 flex-col">
                    <span className="flex items-center gap-2">
                      <span className="truncate text-base font-medium text-primary">
                        {user.display_name}
                      </span>
                      {user.is_platform_admin && <Badge variant="accent">Admin</Badge>}
                    </span>
                    <span className="truncate text-sm text-muted">{user.email}</span>
                  </span>
                  {pending ? (
                    <Spinner className="text-muted" />
                  ) : (
                    <ArrowRight
                      aria-hidden="true"
                      className="size-4 text-muted opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100"
                    />
                  )}
                </button>
              </li>
            )
          })}
        </ul>
      )}
    </>
  )
}
