import { Bot, KeyRound, ShieldCheck } from 'lucide-react'

import type { AdminUserSummary } from '@/api/types'
import { Badge } from '@/components/ui/badge'

/** Platform admin, system accounts and deactivated people, in one quiet row of badges. */
export function UserBadges({
  user,
  showActive = false,
}: {
  user: AdminUserSummary
  /** Also say "Active" (the detail sheet; the list leaves it implicit). */
  showActive?: boolean
}) {
  return (
    <span className="inline-flex flex-wrap items-center gap-1">
      {!user.is_active ? (
        <Badge variant="outline">Deactivated</Badge>
      ) : (
        showActive && <Badge variant="success">Active</Badge>
      )}
      {user.is_platform_admin && (
        <Badge variant="info">
          <ShieldCheck aria-hidden="true" />
          Platform admin
        </Badge>
      )}
      {user.is_break_glass && (
        <Badge variant="warning">
          <KeyRound aria-hidden="true" />
          Break-glass
        </Badge>
      )}
      {user.is_service_account && (
        <Badge variant="neutral">
          <Bot aria-hidden="true" />
          Agent
        </Badge>
      )}
    </span>
  )
}

/** What someone is, beside their name in the Users list: platform admin, break-glass. */
export function UserRoleBadges({ user }: { user: AdminUserSummary }) {
  if (!user.is_platform_admin && !user.is_break_glass) return null
  return (
    <span className="inline-flex shrink-0 items-center gap-1">
      {user.is_platform_admin && (
        <Badge variant="info">
          <ShieldCheck aria-hidden="true" />
          Platform admin
        </Badge>
      )}
      {user.is_break_glass && (
        <Badge variant="warning">
          <KeyRound aria-hidden="true" />
          Break-glass
        </Badge>
      )}
    </span>
  )
}

/** System accounts (agents, the break-glass admin) keep their email and admin rights. */
export function isSystemAccount(user: AdminUserSummary): boolean {
  return user.is_service_account || user.is_break_glass
}

/** "Manual" and/or "Synced": how a membership came about (both can be true). */
export function ProvenanceBadges({ manual, synced }: { manual: boolean; synced: boolean }) {
  return (
    <span className="inline-flex items-center gap-1">
      {manual && (
        <Badge variant="neutral" title="Added by an admin; sign-in sync never changes it">
          Manual
        </Badge>
      )}
      {synced && (
        <Badge variant="info" title="Added by sign-in sync from the identity provider">
          Synced
        </Badge>
      )}
    </span>
  )
}
