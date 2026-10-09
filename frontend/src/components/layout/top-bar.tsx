import { Link, useMatches } from '@tanstack/react-router'
import { ChevronRight, Menu, PanelLeftOpen, Search } from 'lucide-react'
import type { ReactNode } from 'react'

import { useAppCommands } from '@/components/layout/app-commands'
import { useSidebar } from '@/components/layout/sidebar-context'
import { Button } from '@/components/ui/button'
import { KbdShortcut } from '@/components/ui/kbd'
import { WithTooltip } from '@/components/ui/tooltip'
import { NotificationBell } from '@/features/notifications/notification-bell'
import { cn } from '@/lib/utils'
import { SHORTCUTS } from '@/lib/shortcuts'

export interface Crumb {
  label: string
  /** Omit for the current page. */
  to?: string
}

/**
 * Breadcrumbs from the matched routes: a static `staticData: { crumb }`, a
 * dynamic `crumb` string returned by the route's loader (e.g. a project name),
 * or a loader `crumbs` array for several levels (e.g. project › idea key). A
 * loader's `crumbRoot` starts the trail afresh (the admin pages live under
 * /settings but read "Admin › Users").
 */
function useRouteCrumbs(): Crumb[] {
  const matches = useMatches()
  return matches.reduce<Crumb[]>((trail, match) => {
    const data = match.loaderData as
      { crumb?: unknown; crumbs?: unknown; crumbRoot?: unknown } | undefined
    if (Array.isArray(data?.crumbRoot)) return [...(data.crumbRoot as Crumb[])]
    if (Array.isArray(data?.crumbs)) return [...trail, ...(data.crumbs as Crumb[])]
    const label = typeof data?.crumb === 'string' ? data.crumb : match.staticData.crumb
    return label ? [...trail, { label, to: match.pathname }] : trail
  }, [])
}

export interface TopBarProps {
  /** Override route-derived breadcrumbs (e.g. with an idea title). */
  crumbs?: Crumb[]
  /** Page-level actions on the right (keep to one primary). */
  actions?: ReactNode
  /** The notification bell (signed-in shell); off in previews such as /design. */
  showBell?: boolean
}

export function TopBar({ crumbs, actions, showBell = true }: TopBarProps) {
  const routeCrumbs = useRouteCrumbs()
  const items = crumbs ?? routeCrumbs
  const { collapsed, toggleCollapsed, setMobileOpen } = useSidebar()
  const { openCommandPalette } = useAppCommands()

  return (
    <header className="flex h-12 shrink-0 items-center gap-2 border-b border-subtle px-3 md:px-4">
      <Button
        variant="ghost"
        size="icon-sm"
        className="md:hidden"
        aria-label="Open navigation"
        onClick={() => setMobileOpen(true)}
      >
        <Menu />
      </Button>
      {collapsed && (
        <WithTooltip content="Expand sidebar" shortcut={SHORTCUTS.toggleSidebar.keys}>
          <Button
            variant="ghost"
            size="icon-sm"
            className="hidden md:inline-flex"
            aria-label="Expand sidebar"
            onClick={toggleCollapsed}
          >
            <PanelLeftOpen />
          </Button>
        </WithTooltip>
      )}

      {/* No trail (a not-found page): no empty Breadcrumb landmark either. */}
      {items.length === 0 ? (
        <div className="flex-1" />
      ) : (
        <nav aria-label="Breadcrumb" className="min-w-0 flex-1">
          <ol className="flex min-w-0 items-center gap-1 text-sm">
            {items.map((crumb, index) => {
              const last = index === items.length - 1
              return (
                <li key={`${crumb.label}-${index}`} className="flex min-w-0 items-center gap-1">
                  {index > 0 && (
                    <ChevronRight aria-hidden="true" className="size-3.5 shrink-0 text-muted" />
                  )}
                  {last || !crumb.to ? (
                    <span
                      aria-current={last ? 'page' : undefined}
                      // A level that isn't a link (a guest researcher's project): quiet text.
                      className={cn('truncate', last ? 'font-medium text-primary' : 'text-muted')}
                    >
                      {crumb.label}
                    </span>
                  ) : (
                    <Link
                      to={crumb.to}
                      className="truncate rounded-sm text-muted hover:text-primary"
                    >
                      {crumb.label}
                    </Link>
                  )}
                </li>
              )
            })}
          </ol>
        </nav>
      )}

      <div className="flex items-center gap-2">
        {actions}
        {showBell && <NotificationBell />}
        <Button
          variant="outline"
          size="sm"
          onClick={openCommandPalette}
          aria-label="Search and commands"
          aria-keyshortcuts="Meta+K Control+K"
          className="gap-2 text-muted sm:w-52 sm:justify-start"
        >
          <Search />
          <span className="hidden sm:inline">Search…</span>
          <KbdShortcut
            keys={SHORTCUTS.commandPalette.keys}
            className="ml-auto hidden sm:inline-flex"
          />
        </Button>
      </div>
    </header>
  )
}
