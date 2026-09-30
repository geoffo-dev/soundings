import { createFileRoute, Outlet } from '@tanstack/react-router'

import { AppShell } from '@/components/layout/app-shell'

/** Pathless layout: every signed-in screen renders inside the app shell. */
export const Route = createFileRoute('/_app')({
  component: () => (
    <AppShell>
      <Outlet />
    </AppShell>
  ),
})
