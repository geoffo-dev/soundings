import { useNavigate } from '@tanstack/react-router'
import { ArrowRight, CloudOff, KeyRound, Search } from 'lucide-react'
import { useState } from 'react'

import { useDevLogin, useDevUsers } from '@/api/auth'
import { hasErrorCode } from '@/api/errors'
import type { CurrentUser } from '@/api/types'
import { LogoMark } from '@/components/layout/logo'
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
 * /login — Phase 1 development sign-in: pick a user from `list_dev_users`.
 * Phase 2 puts the organisation's single sign-on button in the slot above the
 * list (and hides the list in production, where dev login is disabled).
 */
export function LoginPage({ next }: { next?: string }) {
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

  const devLoginDisabled = hasErrorCode(users.error, 'not_found')

  return (
    <div className="flex min-h-dvh flex-col items-center bg-background px-4 py-10 sm:justify-center sm:py-16">
      <main id="main" className="flex w-full max-w-md flex-col gap-6">
        <div className="flex flex-col items-center gap-3 text-center">
          <LogoMark className="size-10" />
          <div className="flex flex-col gap-1">
            <h1 className="text-2xl font-semibold text-primary">Sign in to Soundings</h1>
            <p className="text-base text-muted">Share ideas, own them, and score them fairly.</p>
          </div>
        </div>

        <section
          aria-labelledby="dev-login-heading"
          className="flex flex-col gap-4 rounded-xl border bg-surface p-4 sm:p-5"
        >
          {/* Phase 2: <SingleSignOnButton /> and an "or" divider go here. */}
          <div className="flex flex-col gap-1 px-1">
            <h2 id="dev-login-heading" className="text-base font-semibold text-primary">
              Choose who you are
            </h2>
            <p className="text-sm text-muted">
              Development sign-in: no password needed. Single sign-on replaces this in production.
            </p>
          </div>

          {users.isPending ? (
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
          ) : users.isError ? (
            devLoginDisabled ? (
              <EmptyState
                size="compact"
                icon={<KeyRound />}
                title="Sign-in isn’t set up yet"
                description="Ask your administrator to connect single sign-on for Soundings."
              />
            ) : (
              <EmptyState
                role="alert"
                size="compact"
                icon={<CloudOff />}
                title="We couldn’t load the sign-in options"
                description="Check your connection and try again."
                action={
                  <Button variant="primary" onClick={() => void users.refetch()}>
                    Try again
                  </Button>
                }
              />
            )
          ) : (
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
                  // The one input on the page: focus it so typing filters right away.
                  // eslint-disable-next-line jsx-a11y/no-autofocus
                  autoFocus
                />
              )}
              {visible.length === 0 ? (
                <p className="px-1 py-6 text-center text-sm text-muted">
                  Nobody matches “{filter}”.
                </p>
              ) : (
                <ul ref={listRef} aria-label="People" className="-mx-1 flex flex-col gap-0.5 p-1">
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
                          <Avatar
                            name={user.display_name}
                            src={user.avatar_url}
                            size="lg"
                            decorative
                          />
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
          )}
        </section>

        <p className="text-center text-xs text-muted pointer-coarse:hidden">
          Use <kbd className="font-sans">↑</kbd> <kbd className="font-sans">↓</kbd> to choose and{' '}
          <kbd className="font-sans">Enter</kbd> to sign in.
        </p>
      </main>
    </div>
  )
}
