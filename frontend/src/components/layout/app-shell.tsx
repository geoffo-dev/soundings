import type { ReactNode } from 'react'

import { Sidebar } from '@/components/layout/sidebar'
import { SidebarProvider, useSidebar } from '@/components/layout/sidebar-context'
import { TopBar, type TopBarProps } from '@/components/layout/top-bar'
import { Sheet, SheetContent, SheetDescription, SheetTitle } from '@/components/ui/sheet'
import { VisuallyHidden } from '@/components/ui/visually-hidden'
import { cn } from '@/lib/utils'

export interface AppShellProps {
  children: ReactNode
  topBar?: TopBarProps
  /** Override the viewport height (the /design page embeds a small preview). */
  className?: string
}

/**
 * Sidebar + inset content panel (Linear-style). Desktop: collapsible sidebar
 * ("[" toggles). Phones/tablets: the sidebar becomes a drawer from the top bar.
 */
export function AppShell(props: AppShellProps) {
  return (
    <SidebarProvider>
      <ShellLayout {...props} />
    </SidebarProvider>
  )
}

function ShellLayout({ children, topBar, className }: AppShellProps) {
  const { collapsed, mobileOpen, setMobileOpen } = useSidebar()

  return (
    <div className={cn('flex h-dvh overflow-hidden bg-background', className)}>
      <a
        href="#main"
        className="sr-only z-50 rounded-md bg-elevated px-3 py-2 text-sm font-medium shadow-overlay focus:not-sr-only focus:fixed focus:top-2 focus:left-2"
      >
        Skip to content
      </a>

      <aside
        className={cn(
          'hidden w-(--sidebar-width) shrink-0 transition-[margin] duration-200 ease-out md:block',
          collapsed && 'md:-ml-(--sidebar-width)',
        )}
        aria-hidden={collapsed || undefined}
        inert={collapsed || undefined}
      >
        <Sidebar />
      </aside>

      <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
        <SheetContent
          side="left"
          hideClose
          className="md:hidden"
          onOpenAutoFocus={(event) => {
            // Start on the current page's link, not the first button (whose
            // tooltip would pop up on a phone).
            const current = (event.currentTarget as HTMLElement | null)?.querySelector<HTMLElement>(
              '[data-status="active"], [data-current="true"]',
            )
            if (current) {
              event.preventDefault()
              current.focus()
            }
          }}
        >
          <VisuallyHidden>
            <SheetTitle>Navigation</SheetTitle>
            <SheetDescription>Main navigation</SheetDescription>
          </VisuallyHidden>
          <Sidebar variant="drawer" onNavigate={() => setMobileOpen(false)} />
        </SheetContent>
      </Sheet>

      <div className={cn('flex min-w-0 flex-1 flex-col md:py-2 md:pr-2', collapsed && 'md:pl-2')}>
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden bg-surface md:rounded-lg md:border">
          <TopBar {...topBar} />
          <main
            id="main"
            tabIndex={-1}
            className="min-h-0 flex-1 overflow-y-auto focus:outline-none"
          >
            {children}
          </main>
        </div>
      </div>
    </div>
  )
}
