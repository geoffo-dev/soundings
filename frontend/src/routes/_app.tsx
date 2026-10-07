import { createFileRoute, Outlet, useRouter } from '@tanstack/react-router'
import { useEffect } from 'react'

import { AppShell } from '@/components/layout/app-shell'
import { AppShellPending } from '@/components/layout/app-shell-pending'
import { BreakGlassBanner } from '@/features/auth/break-glass-banner'
import { requireUser } from '@/features/auth/session'
import { NewIdeaDialog } from '@/features/new-idea/new-idea-dialog'
import { EmailBanner } from '@/features/notifications/email-banner'
import { CreateProjectDialog } from '@/features/project/create-project-dialog'

/**
 * Pathless layout for every signed-in screen: the auth guard (redirects to
 * /login?next=…), the app shell, and the app-wide dialogs (lib/dialogs.ts).
 * Children read the user with useCurrentUser().
 */
export const Route = createFileRoute('/_app')({
  beforeLoad: async ({ context, location }) => ({
    user: await requireUser(context.queryClient, location),
  }),
  pendingComponent: AppShellPending,
  component: AppLayout,
})

/**
 * Nearly every visit opens an idea: once the first screen is up and the browser is
 * idle, fetch the idea page's code (the evaluate sheet with it), so opening one, or
 * pressing E, doesn't wait for a chunk (perf review B9).
 */
function usePreloadIdeaPage() {
  const router = useRouter()
  useEffect(() => {
    const preload = () => {
      void router.loadRouteChunk(router.routesById['/_app/ideas/$ideaKey'])?.catch(() => undefined)
    }
    if (typeof window.requestIdleCallback === 'function') {
      const id = window.requestIdleCallback(preload, { timeout: 4000 })
      return () => window.cancelIdleCallback(id)
    }
    const timer = window.setTimeout(preload, 1500)
    return () => window.clearTimeout(timer)
  }, [router])
}

function AppLayout() {
  usePreloadIdeaPage()
  return (
    <AppShell
      banner={
        <>
          <BreakGlassBanner />
          <EmailBanner />
        </>
      }
    >
      <Outlet />
      <NewIdeaDialog />
      <CreateProjectDialog />
    </AppShell>
  )
}
