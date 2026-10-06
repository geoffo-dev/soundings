import { Link, useLocation } from '@tanstack/react-router'
import { type ReactNode, useEffect, useMemo, useRef } from 'react'

import { Page, PageHeader } from '@/components/layout/page'
import { useCurrentUser } from '@/features/auth/current-user'
import { useScrollFade } from '@/components/ui/scroll-fade'
import { cn, mergeRefs } from '@/lib/utils'

/** The settings pages, in nav order. Admin pages are for platform admins only. */
export const SETTINGS_PAGES = [
  { to: '/settings', label: 'Account', admin: false },
  { to: '/settings/notifications', label: 'Notifications', admin: false },
  { to: '/settings/api-keys', label: 'API keys', admin: false },
  { to: '/settings/users', label: 'Users', admin: true },
  { to: '/settings/groups', label: 'Groups', admin: true },
  { to: '/settings/sso', label: 'Sign-in (SSO)', short: 'SSO', admin: true },
  { to: '/settings/email', label: 'Email', admin: true },
  { to: '/settings/branding', label: 'Branding', admin: true },
  { to: '/settings/all-api-keys', label: 'All API keys', short: 'All keys', admin: true },
  { to: '/settings/audit', label: 'Audit log', admin: true },
] as const

/**
 * /settings and its pages (SPEC §5 screen 7, wireframe 07): one "Settings"
 * page with a row of sections, like project settings. Everyone has Account
 * (profile, appearance, projects they manage), Notifications (email
 * preferences) and API keys (theirs); platform admins also get Users, Groups,
 * Sign-in (SSO), Email, Branding, All API keys and the Audit log, after a
 * divider. Anyone else never sees the admin sections (and their URLs are a 404).
 */
export function SettingsFrame({ children }: { children: ReactNode }) {
  const me = useCurrentUser()
  return (
    <Page>
      {/* The section row says what's here; each page has its own heading and purpose. */}
      <PageHeader title="Settings" />
      <div className="flex flex-col gap-6">
        <SettingsNav admin={me.is_platform_admin} />
        {children}
      </div>
    </Page>
  )
}

const navLink = cn(
  'relative -mb-px inline-flex h-9 shrink-0 items-center border-b-2 border-transparent px-0.5 text-sm font-medium whitespace-nowrap text-muted',
  'transition-colors duration-150 hover:text-primary focus-visible:rounded-sm focus-visible:outline-offset-0',
  'data-[status=active]:border-accent data-[status=active]:text-primary',
)

function SettingsNav({ admin }: { admin: boolean }) {
  const pages = SETTINGS_PAGES.filter((page) => admin || !page.admin)
  const listRef = useRef<HTMLUListElement>(null)
  const fade = useScrollFade<HTMLUListElement>()
  const ref = useMemo(() => mergeRefs(listRef, fade), [fade])
  const pathname = useLocation({ select: (location) => location.pathname })
  // On phones the row scrolls sideways: bring the current section into view (an
  // admin on Email or Audit log would otherwise see the row end at "SSO"). Only the
  // row scrolls, never the page.
  useEffect(() => {
    const list = listRef.current
    const active = list?.querySelector<HTMLElement>('a[data-status="active"]')
    if (!list || !active) return
    const row = list.getBoundingClientRect()
    const link = active.getBoundingClientRect()
    const margin = 40 // the padding and the faded edge
    if (link.right > row.right - margin) list.scrollLeft += link.right - row.right + margin
    else if (link.left < row.left + margin) list.scrollLeft -= row.left + margin - link.left
  }, [pathname, admin])
  return (
    // On phones the row runs to the screen's edges, fading the side with more.
    <nav aria-label="Settings sections" className="-mx-4 sm:mx-0">
      <ul
        ref={ref}
        className="scrollbar-none flex items-center gap-4 overflow-x-auto border-b scroll-fade-x px-4 sm:px-0"
      >
        {pages.map((page, index) => (
          <li key={page.to} className="flex shrink-0 items-center gap-4">
            {page.admin && !pages[index - 1]?.admin && (
              <span aria-hidden="true" className="h-4 w-px bg-border" />
            )}
            <Link
              to={page.to}
              activeOptions={{ exact: page.to === '/settings' }}
              className={navLink}
              // On phones the row would be cut off: a shorter visible label, same name.
              aria-label={'short' in page ? page.label : undefined}
            >
              {'short' in page ? (
                <>
                  <span className="sm:hidden">{page.short}</span>
                  <span className="hidden sm:inline">{page.label}</span>
                </>
              ) : (
                page.label
              )}
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  )
}

/**
 * A settings page's own heading (h2 under the "Settings" h1), its one-line
 * purpose and its actions (one primary).
 */
export function AdminPageHeader({
  title,
  description,
  actions,
  back,
}: {
  title: ReactNode
  description?: ReactNode
  actions?: ReactNode
  /** A quiet link above the title, e.g. back to the list. */
  back?: ReactNode
}) {
  return (
    <div className="flex flex-col gap-2">
      {back}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex min-w-0 flex-col gap-1">
          <h2 className="text-xl font-semibold text-primary">{title}</h2>
          {description && <p className="max-w-2xl text-sm text-muted">{description}</p>}
        </div>
        {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
      </div>
    </div>
  )
}

/** A titled block inside an admin page (h3), optionally with actions on the right. */
export function AdminSection({
  id,
  title,
  description,
  actions,
  children,
  className,
}: {
  id: string
  title: ReactNode
  description?: ReactNode
  actions?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <section
      id={id}
      aria-labelledby={`${id}-heading`}
      className={cn('flex scroll-mt-6 flex-col gap-3', className)}
    >
      <div className="flex flex-wrap items-end justify-between gap-x-4 gap-y-2">
        <div className="flex min-w-0 flex-col gap-0.5">
          <h3 id={`${id}-heading`} className="text-base font-semibold text-primary">
            {title}
          </h3>
          {description && <p className="max-w-2xl text-sm text-muted">{description}</p>}
        </div>
        {actions}
      </div>
      {children}
    </section>
  )
}
