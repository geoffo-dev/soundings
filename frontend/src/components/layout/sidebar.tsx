import { Link } from '@tanstack/react-router'
import {
  ChevronsUpDown,
  Inbox,
  Keyboard,
  LogOut,
  Monitor,
  Moon,
  Palette,
  PanelLeftClose,
  Settings,
  SquarePen,
  Sun,
} from 'lucide-react'
import type { ReactNode } from 'react'

import { useAppCommands } from '@/components/layout/app-commands'
import { Logo } from '@/components/layout/logo'
import { ProjectTile } from '@/components/layout/project-tile'
import { useShellData, type ShellData } from '@/components/layout/shell-data'
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
import { ScrollArea } from '@/components/ui/scroll-area'
import { WithTooltip } from '@/components/ui/tooltip'
import { designPageEnabled } from '@/lib/env'
import { isThemePreference } from '@/lib/theme'
import { SHORTCUTS } from '@/lib/shortcuts'
import { cn } from '@/lib/utils'

const navItem = cn(
  'group flex h-8 items-center gap-2.5 rounded-md px-2 text-sm font-medium text-secondary',
  'transition-colors duration-100 hover:bg-subtle hover:text-primary',
  'data-[status=active]:bg-subtle-hover data-[status=active]:text-primary',
  '[&_svg]:size-4 [&_svg]:shrink-0 [&_svg]:text-muted data-[status=active]:[&_svg]:text-primary',
)

export interface SidebarProps {
  /** Rendered inside the mobile drawer (no collapse button, closes on navigate). */
  variant?: 'desktop' | 'drawer'
  onNavigate?: () => void
  /** Override data (used by the /design page preview). */
  data?: ShellData
}

export function Sidebar({ variant = 'desktop', onNavigate, data }: SidebarProps) {
  const shell = useShellData()
  const { user, myWorkCount, projects } = data ?? shell
  const { toggleCollapsed } = useSidebar()
  const { newIdea } = useAppCommands()

  return (
    <nav aria-label="Main" className="flex h-full flex-col gap-1 bg-background">
      <div className="flex h-12 shrink-0 items-center gap-1 pr-2 pl-3">
        <Link to="/" onClick={onNavigate} className="-m-1 mr-auto rounded-md p-1">
          <Logo />
        </Link>
        <WithTooltip content="New idea" shortcut={SHORTCUTS.newIdea.keys}>
          <Button variant="ghost" size="icon-sm" aria-label="New idea" onClick={newIdea}>
            <SquarePen />
          </Button>
        </WithTooltip>
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
          <ul className="flex flex-col gap-px">
            <li>
              <Link to="/" onClick={onNavigate} className={navItem} activeOptions={{ exact: true }}>
                <Inbox />
                My work
                {myWorkCount > 0 && (
                  <CountBadge className="ml-auto" aria-label={`${myWorkCount} items need you`}>
                    {myWorkCount}
                  </CountBadge>
                )}
              </Link>
            </li>
          </ul>

          <SidebarSection title="Projects">
            {projects.length === 0 ? (
              <p className="px-2 py-1 text-sm text-muted">No projects yet</p>
            ) : (
              projects.map((project) => (
                <li key={project.id}>
                  <Link
                    to="/projects/$projectId"
                    params={{ projectId: project.id }}
                    onClick={onNavigate}
                    className={navItem}
                  >
                    <ProjectTile name={project.name} />
                    <span className="truncate">{project.name}</span>
                  </Link>
                </li>
              ))
            )}
          </SidebarSection>
        </div>
      </ScrollArea>

      <div className="flex shrink-0 flex-col gap-px border-t border-subtle p-2">
        <Link to="/settings" onClick={onNavigate} className={navItem}>
          <Settings />
          Settings
        </Link>
        <UserMenu user={user} />
      </div>
    </nav>
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

function UserMenu({ user }: { user: ShellData['user'] }) {
  const { preference, setPreference } = useTheme()
  const { openShortcutSheet } = useAppCommands()
  const ThemeIcon = THEME_ICON[preference]
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          className={cn(navItem, 'h-10 w-full text-left data-[state=open]:bg-subtle-hover')}
          aria-label={`Account menu for ${user.name}`}
        >
          <Avatar name={user.name} src={user.avatarUrl} size="sm" />
          <span className="min-w-0 flex-1 truncate text-primary">{user.name}</span>
          <ChevronsUpDown />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        side="top"
        align="start"
        className="w-(--radix-dropdown-menu-trigger-width) min-w-56"
      >
        <DropdownMenuLabel className="flex flex-col gap-0.5 pb-2">
          <span className="text-sm font-medium text-primary">{user.name}</span>
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
        <DropdownMenuItem onSelect={openShortcutSheet}>
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
        <DropdownMenuSeparator />
        {/* Phase 2 wires this to POST /api/v1/auth/logout. */}
        <DropdownMenuItem disabled>
          <LogOut /> Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
