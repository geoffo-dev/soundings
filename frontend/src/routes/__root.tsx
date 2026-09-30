import { QueryClientProvider, type QueryClient } from '@tanstack/react-query'
import { createRootRouteWithContext, HeadContent, Outlet } from '@tanstack/react-router'

import { AppCommandsProvider } from '@/components/layout/app-commands'
import { ThemeProvider } from '@/components/theme-provider'
import { Toaster } from '@/components/ui/toaster'
import { TooltipProvider } from '@/components/ui/tooltip'

export interface RouterContext {
  queryClient: QueryClient
}

export const Route = createRootRouteWithContext<RouterContext>()({
  head: () => ({ meta: [{ title: 'Soundings' }] }),
  component: RootComponent,
})

function RootComponent() {
  const { queryClient } = Route.useRouteContext()
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <TooltipProvider>
          <HeadContent />
          <AppCommandsProvider>
            <Outlet />
          </AppCommandsProvider>
          <Toaster />
        </TooltipProvider>
      </ThemeProvider>
    </QueryClientProvider>
  )
}
