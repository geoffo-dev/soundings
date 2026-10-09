import { useQueryClient } from '@tanstack/react-query'
import { Link, useLocation, useParams } from '@tanstack/react-router'
import {
  ChevronsUpDown,
  Inbox,
  Keyboard,
  LogOut,
  Monitor,
  Moon,
  Palette,
  PanelLeftClose,
  Plus,
  RotateCw,
  Settings,
  ShieldCheck,
  SquarePen,
  Sun,
} from 'lucide-react'
import type { ReactNode } from 'react'

import { findCachedIdea } from '@/api/cache'
import { useProjects } from '@/api/projects'
import { useReviewCounts } from '@/api/submissions'
import type { CurrentUser } from '@/api/types'
import { useWorkCounts } from '@/api/work'
import { useAppCommands } from '@/components/layout/app-commands'
import { Logo } from '@/components/layout/logo'
import { ProjectTile } from '@/components/layout/project-tile'
import { useSidebar } from '@/components/layout/sidebar-context'
import { useTheme } from '@/components/theme-provider'
import { Avatar } from '@/components/ui/avatar'
import { CountBadge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuShortcut,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { ariaKeys } from '@/components/ui/kbd'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Skeleton } from '@/components/ui/skeleton'
import { WithTooltip } from '@/components/ui/tooltip'
import { ADMIN_PAGES, isAdminPath } from '@/features/admin/settings-frame'
import { DevUserSwitcher } from '@/features/auth/dev-user-switcher'
import { useCurrentUser } from '@/features/auth/current-user'
import { useSignOut } from '@/features/auth/use-sign-out'
import { openCreateProject } from '@/lib/dialogs'
import { designPageEnabled } from '@/lib/env'
import { SHORTCUTS } from '@/lib/shortcuts'
import { isThemePreference } from '@/lib/theme'
import { cn } from '@/lib/utils'

const navItem = cn(
  'group flex h-8 items-center gap-2.5 rounded-md px-2 text-sm font-medium text-secondary',
  'transition-colors duration-100 hover:bg-subtle hover:text-primary',
  'data-[status=active]:bg-subtle-hover data-[status=active]:text-primary',
  'data-[current=true]:bg-subtle-hover data-[current=true]:text-primary',
  '[&_svg]:size-4 [&_svg]:shrink-0 [&_svg]:text-muted data-[status=active]:[&_svg]:text-primary',
)

const subItem = cn(
  'flex h-7 items-center gap-2 rounded-md pr-2 pl-8.5 text-sm text-muted',
  'transition-colors duration-100 hover:bg-subtle hover:text-primary',
)

export interface SidebarProps {
  /** Rendered inside the mobile drawer (no collapse button, closes on navigate). */
  variant?: 'desktop' | 'drawer'
  onNavigate?: () => void
}

export function Sidebar({ variant = 'desktop', onNavigate }: SidebarProps) {
  const user = useCurrentUser()
  const pathname = useLocation({ select: (location) => location.pathname })
  const adminPage = isAdminPath(pathname)
  const settingsPage = pathname === '/settings' || pathname.startsWith('/settings/')
  const { toggleCollapsed } = useSidebar()
  const { newIdea, canCreateIdeas } = useAppCommands()

  return (
    <nav aria-label="Main" className="flex h-full flex-col gap-1 bg-background">
      <div className="flex h-12 shrink-0 items-center gap-1 pr-2 pl-3">
        <Link to="/" onClick={onNavigate} className="-m-1 mr-auto rounded-md p-1">
          <Logo />
        </Link>
        {canCreateIdeas && (
          <WithTooltip content="New idea" shortcut={SHORTCUTS.newIdea.keys}>
            <Button variant="ghost" size="icon-sm" aria-label="New idea" onClick={newIdea}>
              <SquarePen />
            </Button>
          </WithTooltip>
        )}
        {variant === 'desktop' && (
          <WithTooltip content="Collapse sidebar" shortcut={SHORTCUTS.toggleSidebar.keys}>
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label="Collapse sidebar"
              onClick={toggleCollapsed}
            >
              <PanelLeftClose />
            </Button>
          </WithTooltip>
        )}
      </div>

      <ScrollArea className="min-h-0 flex-1">
        <div className="flex flex-col gap-5 px-2 pb-4">
          <MyWorkNav onNavigate={onNavigate} />
          <ProjectsNav onNavigate={onNavigate} canCreate={user.is_platform_admin} />
        </div>
      </ScrollArea>

      <div className="flex shrink-0 flex-col gap-px border-t border-subtle p-2">
        {user.is_platform_admin && (
          <AdminNav pathname={pathname} active={adminPage} onNavigate={onNavigate} />
        )}
        {/* Your own settings; the admin pages (also under /settings) light up "Admin". */}
        <Link
          to="/settings"
          onClick={onNavigate}
          activeOptions={{ exact: true }}
          className={navItem}
          data-current={(settingsPage && !adminPage) || undefined}
          aria-current={settingsPage && !adminPage ? 'page' : undefined}
        >
          <Settings />
          Settings
        </Link>
        <UserMenu user={user} />
      </div>
    </nav>
  )
}

/**
 * "Admin" (platform admins), and on an admin page its sections under it: the admin
 * area's left nav, in the sidebar it already has (UX review M5).
 */
function AdminNav({
  pathname,
  active,
  onNavigate,
}: {
  pathname: string
  active: boolean
  onNavigate?: () => void
}) {
  return (
    <div className="flex flex-col gap-px">
      <Link
        to="/admin"
        onClick={onNavigate}
        className={navItem}
        data-current={pathname === '/admin' || undefined}
        aria-current={pathname === '/admin' ? 'page' : undefined}
      >
        <ShieldCheck />
        Admin
      </Link>
      {active && (
        <ul aria-label="Admin sections" className="flex flex-col gap-px">
          {ADMIN_PAGES.map((page) => (
            <li key={page.to}>
              <Link
                to={page.to}
                onClick={onNavigate}
                className={cn(
                  subItem,
                  'data-[status=active]:bg-subtle-hover data-[status=active]:text-primary',
                )}
              >
                {page.label}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function MyWorkNav({ onNavigate }: { onNavigate?: () => void }) {
  const counts = useWorkCounts().data
  // Someone in no project (a guest researcher) has no evaluations or ideas to own:
  // those links would lead to nothing, so they go (unless something is still there).
  const noProjects = useProjects().data?.length === 0
  const due = counts?.evaluations_due ?? 0
  const overdue = counts?.evaluations_overdue ?? 0
  const owned = counts?.owned_open ?? 0
  const dueLabel = `${due} due${overdue > 0 ? `, ${overdue} overdue` : ''}`
  // Phase 8b: research you do, shown only while there is some (most people never have any).
  const research = counts?.research_to_do ?? 0
  const researchOverdue = counts?.research_overdue ?? 0
  const researchLabel = `${research} to do${researchOverdue > 0 ? `, ${researchOverdue} overdue` : ''}`
  return (
    <ul className="flex flex-col gap-px">
      <li>
        <Link to="/" onClick={onNavigate} className={navItem} activeOptions={{ exact: true }}>
          <Inbox />
          My work
        </Link>
      </li>
      {(!noProjects || due > 0) && (
        <li>
          <Link
            to="/"
            hash="evaluations"
            onClick={onNavigate}
            className={subItem}
            aria-label={`Evaluations, ${dueLabel}`}
          >
            <span className="flex-1 truncate">Evaluations</span>
            {overdue > 0 && <span aria-hidden="true" className="size-1.5 rounded-full bg-danger" />}
            {due > 0 && <CountBadge aria-hidden="true">{due}</CountBadge>}
          </Link>
        </li>
      )}
      {research > 0 && (
        <li>
          <Link
            to="/"
            hash="research"
            onClick={onNavigate}
            className={subItem}
            aria-label={`Research, ${researchLabel}`}
          >
            <span className="flex-1 truncate">Research</span>
            {researchOverdue > 0 && (
              <span aria-hidden="true" className="size-1.5 rounded-full bg-danger" />
            )}
            <CountBadge aria-hidden="true">{research}</CountBadge>
          </Link>
        </li>
      )}
      {(!noProjects || owned > 0) && (
        <li>
          <Link
            to="/"
            hash="owned"
            onClick={onNavigate}
            className={subItem}
            aria-label={`Ideas I own, ${owned} open`}
          >
            <span className="flex-1 truncate">Ideas I own</span>
            {owned > 0 && <CountBadge aria-hidden="true">{owned}</CountBadge>}
          </Link>
        </li>
      )}
    </ul>
  )
}

function ProjectsNav({ onNavigate, canCreate }: { onNavigate?: () => void; canCreate: boolean }) {
  const projects = useProjects()
  // Phase 8b: a guest researcher works on ideas without being in their projects.
  const researching = (useWorkCounts().data?.research_to_do ?? 0) > 0
  const reviews = new Map(
    useReviewCounts(projects.data).map(({ project, count }) => [project.id, count]),
  )
  const queryClient = useQueryClient()
  const params: { slug?: string; ideaKey?: string } = useParams({ strict: false })
  // On an idea page, highlight the idea's project.
  const activeSlug =
    params.slug ??
    (params.ideaKey ? findCachedIdea(queryClient, params.ideaKey)?.project.slug : undefined)

  return (
    <SidebarSection title="Projects">
      {projects.isPending ? (
        [0, 1, 2].map((i) => (
          <li key={i} aria-hidden="true" className="flex h-8 items-center gap-2.5 px-2">
            <Skeleton className="size-4.5 rounded-sm" />
            <Skeleton className="h-3 w-28" />
          </li>
        ))
      ) : projects.isError ? (
        <li className="flex items-center justify-between gap-2 px-2 py-1 text-sm text-muted">
          Couldn’t load projects
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label="Retry loading projects"
            onClick={() => void projects.refetch()}
          >
            <RotateCw />
          </Button>
        </li>
      ) : projects.data.length === 0 ? (
        <li className="px-2 py-1 text-sm text-muted">
          {canCreate
            ? 'No projects yet'
            : researching
              ? 'No projects'
              : 'No projects yet — ask an admin to add you'}
        </li>
      ) : (
        projects.data.map((project) => {
          const waiting = reviews.get(project.id) ?? 0
          return (
            <li key={project.id}>
              <Link
                to="/p/$slug"
                params={{ slug: project.slug }}
                onClick={onNavigate}
                className={navItem}
                data-current={project.slug === activeSlug || undefined}
              >
                <ProjectTile name={project.name} />
                <span className="truncate">{project.name}</span>
              </Link>
              {waiting > 0 && (
                // Public ideas held for review are on no board: admins see them here.
                <Link
                  to="/p/$slug/review"
                  params={{ slug: project.slug }}
                  onClick={onNavigate}
                  className={cn(
                    subItem,
                    'data-[status=active]:bg-subtle-hover data-[status=active]:text-primary',
                  )}
                  // In context: it sits right under its project's link (WCAG 2.4.4).
                  aria-label={`Review new ideas, ${String(waiting)} waiting`}
                >
                  <span className="flex-1 truncate">Review</span>
                  <CountBadge aria-hidden="true">{waiting}</CountBadge>
                </Link>
              )}
            </li>
          )
        })
      )}
      {canCreate && (
        <li>
          <button
            type="button"
            onClick={() => {
              onNavigate?.()
              openCreateProject()
            }}
            className={cn(navItem, 'w-full text-muted')}
          >
            <Plus />
            New project
          </button>
        </li>
      )}
    </SidebarSection>
  )
}

function SidebarSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section aria-label={title} className="flex flex-col gap-px">
      <h2 className="px-2 pb-1 text-xs font-medium text-muted">{title}</h2>
      <ul className="flex flex-col gap-px">{children}</ul>
    </section>
  )
}

const THEME_ICON = { light: Sun, dark: Moon, system: Monitor } as const

function UserMenu({ user }: { user: CurrentUser }) {
  const { preference, setPreference } = useTheme()
  const { openShortcutSheet } = useAppCommands()
  const signOut = useSignOut()
  const ThemeIcon = THEME_ICON[preference]
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          className={cn(navItem, 'h-10 w-full text-left data-[state=open]:bg-subtle-hover')}
          aria-label={`Account menu for ${user.display_name}`}
        >
          <Avatar name={user.display_name} src={user.avatar_url} size="sm" decorative />
          <span className="min-w-0 flex-1 truncate text-primary">{user.display_name}</span>
          <ChevronsUpDown />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        side="top"
        align="start"
        className="w-(--radix-dropdown-menu-trigger-width) min-w-56"
      >
        <DropdownMenuLabel className="flex flex-col gap-0.5 pb-2">
          <span className="text-sm font-medium text-primary">{user.display_name}</span>
          <span className="truncate font-normal">{user.email}</span>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuLabel className="flex items-center gap-1.5">
          <ThemeIcon className="size-3.5" aria-hidden="true" /> Theme
        </DropdownMenuLabel>
        <DropdownMenuRadioGroup
          value={preference}
          onValueChange={(value) => {
            if (isThemePreference(value)) setPreference(value)
          }}
        >
          <DropdownMenuRadioItem value="system">
            <Monitor /> System
          </DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="light">
            <Sun /> Light
          </DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="dark">
            <Moon /> Dark
          </DropdownMenuRadioItem>
        </DropdownMenuRadioGroup>
        <DropdownMenuSeparator />
        <DropdownMenuItem
          onSelect={openShortcutSheet}
          aria-keyshortcuts={ariaKeys(SHORTCUTS.shortcutSheet.keys)}
        >
          <Keyboard /> Keyboard shortcuts
          <DropdownMenuShortcut keys={SHORTCUTS.shortcutSheet.keys} />
        </DropdownMenuItem>
        {designPageEnabled && (
          <DropdownMenuItem asChild>
            <Link to="/design">
              <Palette /> Design system
            </Link>
          </DropdownMenuItem>
        )}
        {import.meta.env.DEV && <DevUserSwitcher currentUserId={user.id} />}
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={signOut}>
          <LogOut /> Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
