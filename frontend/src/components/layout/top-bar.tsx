import { Link, useMatches } from '@tanstack/react-router'
import { ChevronRight, Menu, PanelLeftOpen, Search } from 'lucide-react'
import type { ReactNode } from 'react'

import { useAppCommands } from '@/components/layout/app-commands'
import { useSidebar } from '@/components/layout/sidebar-context'
import { Button } from '@/components/ui/button'
import { KbdShortcut } from '@/components/ui/kbd'
import { WithTooltip } from '@/components/ui/tooltip'
import { SHORTCUTS } from '@/lib/shortcuts'

export interface Crumb {
  label: string
  /** Omit for the current page. */
  to?: string
}

/**
 * Breadcrumbs from the matched routes: a static `staticData: { crumb }`, or a
 * dynamic `crumb` string returned by the route's loader (e.g. an idea title).
 */
function useRouteCrumbs(): Crumb[] {
  const matches = useMatches()
  return matches.flatMap((match) => {
    const loaderCrumb: unknown = (match.loaderData as { crumb?: unknown } | undefined)?.crumb
    const label = typeof loaderCrumb === 'string' ? loaderCrumb : match.staticData.crumb
    return label ? [{ label, to: match.pathname }] : []
  })
}

export interface TopBarProps {
  /** Override route-derived breadcrumbs (e.g. with an idea title). */
  crumbs?: Crumb[]
  /** Page-level actions on the right (keep to one primary). */
  actions?: ReactNode
}

export function TopBar({ crumbs, actions }: TopBarProps) {
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
                    className="truncate font-medium text-primary"
                  >
                    {crumb.label}
                  </span>
                ) : (
                  <Link to={crumb.to} className="truncate rounded-sm text-muted hover:text-primary">
                    {crumb.label}
                  </Link>
                )}
              </li>
            )
          })}
        </ol>
      </nav>

      <div className="flex items-center gap-2">
        {actions}
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
