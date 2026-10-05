import { Clock, Moon } from 'lucide-react'

import type { ApiKey, ApiKeyScope, ApiKeyState } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { RelativeTime } from '@/components/ui/relative-time'
import { WithTooltip } from '@/components/ui/tooltip'
import { formatDateTime, formatShortDate } from '@/lib/dates'
import { cn } from '@/lib/utils'

import { SCOPE_COPY } from './key-rules'

/** The scopes as quiet chips, in canonical order. */
export function ScopeBadges({
  scopes,
  className,
}: {
  scopes: readonly ApiKeyScope[]
  className?: string
}) {
  return (
    <span className={cn('inline-flex flex-wrap items-center gap-1', className)}>
      <span className="sr-only">Scopes: </span>
      {scopes.map((scope) => (
        <Badge key={scope} variant="outline">
          {SCOPE_COPY[scope].label}
        </Badge>
      ))}
    </span>
  )
}

/**
 * "Expired" or "Dormant" (active keys need no badge). Dormant: a person's key
 * paused because they haven't signed in for 30 days (contract-phase5 §3.1).
 */
export function KeyStateBadge({
  state,
  audience = 'owner',
}: {
  state: ApiKeyState
  /** `owner`: your own key ("you"); `admin`: anyone's ("the owner"). */
  audience?: 'owner' | 'admin'
}) {
  if (state === 'expired') {
    return (
      <Badge variant="warning">
        <Clock aria-hidden="true" />
        Expired
      </Badge>
    )
  }
  if (state === 'dormant') {
    const why =
      audience === 'admin'
        ? 'The owner hasn’t signed in for 30 days. It works again when they do.'
        : 'You haven’t signed in for 30 days. It works again now that you have.'
    return (
      <WithTooltip content={why}>
        <Badge variant="neutral">
          <Moon aria-hidden="true" />
          Dormant
          <span className="sr-only">: {why}</span>
        </Badge>
      </WithTooltip>
    )
  }
  return null
}

/** "All projects", the names it is restricted to, or a warning when none is left. */
export function KeyProjects({ apiKey }: { apiKey: Pick<ApiKey, 'restricted' | 'projects'> }) {
  if (!apiKey.restricted) return <span className="text-sm text-secondary">All projects</span>
  if (apiKey.projects.length === 0) {
    return <span className="text-sm text-warning">No projects left: it reaches nothing</span>
  }
  return (
    <span className="text-sm text-secondary">
      {apiKey.projects.map((project) => project.name).join(', ')}
    </span>
  )
}

/** "Never", the expiry date, or "Expired" with the date it stopped. */
export function KeyExpiry({ apiKey }: { apiKey: Pick<ApiKey, 'expires_at' | 'state'> }) {
  if (!apiKey.expires_at) return <span className="text-sm text-muted">Never</span>
  const date = (
    <WithTooltip content={formatDateTime(apiKey.expires_at)}>
      <time dateTime={apiKey.expires_at} className="tabular-nums">
        {formatShortDate(apiKey.expires_at)}
      </time>
    </WithTooltip>
  )
  return apiKey.state === 'expired' ? (
    <span className="inline-flex flex-wrap items-center gap-1.5 text-sm text-muted">
      <KeyStateBadge state="expired" />
      {date}
    </span>
  ) : (
    <span className="text-sm text-secondary">{date}</span>
  )
}

/** "Never used" or "2 hours ago". */
export function KeyLastUsed({ at }: { at: string | null }) {
  if (!at) return <span className="text-sm text-muted">Never used</span>
  return <RelativeTime date={at} className="text-sm text-secondary" />
}
