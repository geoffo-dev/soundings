import { createFileRoute, Outlet } from '@tanstack/react-router'

import { AppShell } from '@/components/layout/app-shell'
import { AppShellPending } from '@/components/layout/app-shell-pending'
import { requireUser } from '@/features/auth/session'
import { NewIdeaDialog } from '@/features/new-idea/new-idea-dialog'
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

function AppLayout() {
  return (
    <AppShell>
      <Outlet />
      <NewIdeaDialog />
      <CreateProjectDialog />
    </AppShell>
  )
}
