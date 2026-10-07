import type { ReactNode } from 'react'

import { NavigationProgress } from '@/components/layout/navigation-progress'
import { useRouteFocus } from '@/components/layout/route-focus'
import { Sidebar } from '@/components/layout/sidebar'
import { SidebarProvider, useSidebar } from '@/components/layout/sidebar-context'
import { TopBar, type TopBarProps } from '@/components/layout/top-bar'
import { Sheet, SheetContent, SheetDescription, SheetTitle } from '@/components/ui/sheet'
import { VisuallyHidden } from '@/components/ui/visually-hidden'
import { cn } from '@/lib/utils'

export interface AppShellProps {
  children: ReactNode
  topBar?: TopBarProps
  /** A persistent strip above the top bar (the break-glass session banner). */
  banner?: ReactNode
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

function ShellLayout({ children, topBar, banner, className }: AppShellProps) {
  const { collapsed, mobileOpen, setMobileOpen } = useSidebar()
  useRouteFocus()

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
        <div className="relative flex min-h-0 flex-1 flex-col overflow-hidden bg-surface md:rounded-lg md:border">
          <NavigationProgress />
          {banner}
          <TopBar {...topBar} />
          {/* `relative`: absolutely positioned descendants (sr-only text, hidden inputs)
              belong to this scroller; without it they overflow the document instead.
              While a form's Save bar sticks to the bottom (FormActions), focus scrolls
              fields clear of it (WCAG 2.4.11 focus not obscured). */}
          <main
            id="main"
            tabIndex={-1}
            className={cn(
              'relative min-h-0 flex-1 overflow-y-auto focus:outline-none',
              'has-[[data-sticky-actions=always]]:scroll-pb-20 max-sm:has-[[data-sticky-actions=phone]]:scroll-pb-20',
              // The same under a bar that sticks to the top (the proposal editor's).
              'has-[[data-sticky-top]]:scroll-pt-16',
            )}
          >
            {children}
          </main>
        </div>
      </div>
    </div>
  )
}
