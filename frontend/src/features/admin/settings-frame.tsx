import { Link, useLocation } from '@tanstack/react-router'
import {
  ArrowLeft,
  Bot,
  ChevronRight,
  KeyRound,
  Mail,
  Palette,
  ScrollText,
  UserRound,
  UsersRound,
} from 'lucide-react'
import { type ReactNode, useEffect, useMemo, useRef } from 'react'

import { Page, PageHeader } from '@/components/layout/page'
import { useScrollFade } from '@/components/ui/scroll-fade'
import { cn, mergeRefs } from '@/lib/utils'

/** Your own settings, in tab order (everyone). */
export const SETTINGS_PAGES = [
  { to: '/settings', label: 'Account' },
  { to: '/settings/notifications', label: 'Notifications' },
  { to: '/settings/api-keys', label: 'API keys' },
] as const

/**
 * The admin area (platform admins): its own sidebar entry and a left nav; on phones
 * the /admin page lists the sections. The pages keep their /settings/… URLs.
 */
export const ADMIN_PAGES = [
  {
    to: '/settings/users',
    label: 'Users',
    description: 'Who can sign in, their roles, sign-in links and sessions.',
    icon: UserRound,
  },
  {
    to: '/settings/groups',
    label: 'Groups',
    description: 'Groups of people, and how they follow your identity provider.',
    icon: UsersRound,
  },
  {
    to: '/settings/sso',
    label: 'Sign-in (SSO)',
    description: 'The single sign-on settings in effect and the break-glass account.',
    icon: KeyRound,
  },
  {
    to: '/settings/email',
    label: 'Email',
    description: 'The mail server in effect, a test email and the outbox.',
    icon: Mail,
  },
  {
    to: '/settings/branding',
    label: 'Branding',
    description: 'Name, logo, colours and font for the app, emails and exports.',
    icon: Palette,
  },
  {
    to: '/settings/ai-agents',
    label: 'AI agents',
    description: 'kagent agents that evaluate, research and draft, and their keys.',
    icon: Bot,
  },
  {
    to: '/settings/audit',
    label: 'Audit log',
    description: 'Sign-ins, admin changes, keys and AI runs: who did what, when.',
    icon: ScrollText,
  },
] as const

/** Whether a path is one of the admin pages (or the /admin list). */
export function isAdminPath(pathname: string): boolean {
  return (
    pathname === '/admin' ||
    ADMIN_PAGES.some((page) => pathname === page.to || pathname.startsWith(`${page.to}/`))
  )
}

/**
 * /settings, /settings/notifications and /settings/api-keys (SPEC §5 screen 7,
 * wireframe 07): your own settings, one "Settings" page with three tabs:
 * Account (profile, appearance, projects you manage), Notifications (email
 * preferences) and API keys. The admin pages have their own frame (AdminFrame).
 */
export function SettingsFrame({ children }: { children: ReactNode }) {
  return (
    <Page>
      {/* The tab row says what's here; each page has its own heading and purpose. */}
      <PageHeader title="Settings" />
      <div className="flex flex-col gap-6">
        <SettingsNav />
        {children}
      </div>
    </Page>
  )
}

const navLink = cn(
  'relative -mb-px inline-flex h-9 shrink-0 items-center border-b-2 border-transparent px-0.5 text-sm font-medium whitespace-nowrap text-muted',
  'transition-colors duration-150 hover:text-primary focus-visible:rounded-sm focus-visible:outline-offset-0',
  'data-[status=active]:border-accent-control data-[status=active]:text-primary',
)

function SettingsNav() {
  const listRef = useRef<HTMLUListElement>(null)
  const fade = useScrollFade<HTMLUListElement>()
  const ref = useMemo(() => mergeRefs(listRef, fade), [fade])
  const pathname = useLocation({ select: (location) => location.pathname })
  // On narrow phones the row may scroll sideways: bring the current tab into view.
  // Only the row scrolls, never the page.
  useEffect(() => {
    const list = listRef.current
    const active = list?.querySelector<HTMLElement>('a[data-status="active"]')
    if (!list || !active) return
    const row = list.getBoundingClientRect()
    const link = active.getBoundingClientRect()
    const margin = 40 // the padding and the faded edge
    if (link.right > row.right - margin) list.scrollLeft += link.right - row.right + margin
    else if (link.left < row.left + margin) list.scrollLeft -= row.left + margin - link.left
  }, [pathname])
  return (
    <nav aria-label="Settings sections" className="-mx-4 sm:mx-0">
      <ul
        ref={ref}
        className="scrollbar-none flex items-center gap-4 overflow-x-auto border-b scroll-fade-x px-4 sm:px-0"
      >
        {SETTINGS_PAGES.map((page) => (
          <li key={page.to} className="flex shrink-0">
            <Link
              to={page.to}
              activeOptions={{ exact: page.to === '/settings' }}
              className={navLink}
            >
              {page.label}
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  )
}

/**
 * The admin pages (platform admins; UX review M5): an "Admin" page whose sections
 * are listed in the app's sidebar under "Admin" (a left nav that costs the content
 * no room). Phones have no sidebar on screen: a link back to the /admin list takes
 * its place.
 */
export function AdminFrame({ children }: { children: ReactNode }) {
  return (
    <Page>
      <PageHeader title="Admin" />
      <div className="flex flex-col gap-6">
        <Link
          to="/admin"
          className="-mt-2 inline-flex w-fit items-center gap-1.5 rounded-sm text-sm text-muted hover:text-primary md:hidden"
        >
          <ArrowLeft aria-hidden="true" className="size-4" />
          All admin settings
        </Link>
        {children}
      </div>
    </Page>
  )
}

/** /admin: the admin sections as a list (the phone's nav; a contents page on wide screens). */
export function AdminOverview() {
  return (
    <Page>
      <PageHeader
        title="Admin"
        description="Settings for everyone in Soundings. Only platform admins see these."
      />
      <nav aria-label="Admin sections">
        <ul className="divide-y divide-subtle overflow-hidden rounded-lg border bg-surface">
          {ADMIN_PAGES.map((page) => {
            const Icon = page.icon
            return (
              <li key={page.to}>
                <Link
                  to={page.to}
                  className="flex items-center gap-3 px-4 py-3 transition-colors duration-100 hover:bg-subtle focus-visible:-outline-offset-2"
                >
                  <Icon aria-hidden="true" className="size-4 shrink-0 text-muted" />
                  <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                    <span className="text-base font-medium text-primary">{page.label}</span>
                    <span className="text-sm text-muted">{page.description}</span>
                  </span>
                  <ChevronRight aria-hidden="true" className="size-4 shrink-0 text-muted" />
                </Link>
              </li>
            )
          })}
        </ul>
      </nav>
    </Page>
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
