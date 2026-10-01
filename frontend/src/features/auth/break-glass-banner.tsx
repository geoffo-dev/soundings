import { ShieldAlert } from 'lucide-react'

import { Button } from '@/components/ui/button'

import { isBreakGlassSession, useCurrentUser } from './current-user'
import { useSignOut } from './use-sign-out'

/**
 * A persistent strip at the top of the app in break-glass sessions
 * (contract-phase2 §3.8): the emergency account is a platform admin and every
 * action is audited as such, so it should never be forgotten in a tab.
 */
export function BreakGlassBanner() {
  const user = useCurrentUser()
  const signOut = useSignOut()
  if (!isBreakGlassSession(user)) return null
  return (
    <div
      role="status"
      className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b bg-warning-subtle px-4 py-2 text-sm text-primary"
    >
      <ShieldAlert aria-hidden="true" className="size-4 shrink-0 text-warning" />
      <p className="min-w-0 flex-1">
        <span className="font-medium">Signed in with the break-glass account.</span>{' '}
        <span className="text-secondary">
          Every action is recorded in the audit log. Sign out when you’re done.
        </span>
      </p>
      <Button size="sm" variant="outline" onClick={signOut}>
        Sign out
      </Button>
    </div>
  )
}
