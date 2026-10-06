import { Clock, Moon } from 'lucide-react'
import { Fragment } from 'react'

import type { AdminApiKey, ApiKey, ApiKeyScope, ApiKeyState } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { RelativeTime, useNow } from '@/components/ui/relative-time'
import { WithTooltip } from '@/components/ui/tooltip'
import { formatDateTime, formatShortDate } from '@/lib/dates'
import { cn } from '@/lib/utils'

import { accessLabel, expiresSoon, presetOf, SCOPE_COPY } from './key-rules'

/**
 * The scopes as quiet chips, in canonical order. All four are one "Full access"
 * chip (the create dialog's preset of that name), so rows keep one line.
 */
export function ScopeBadges({
  scopes,
  className,
}: {
  scopes: readonly ApiKeyScope[]
  className?: string
}) {
  const full = presetOf(scopes) === 'full'
  return (
    <span className={cn('inline-flex flex-wrap items-center gap-1', className)}>
      <span className="sr-only">Scopes: </span>
      {full ? (
        <Badge variant="outline">
          Full access
          <span className="sr-only">
            {' '}
            ({scopes.map((scope) => SCOPE_COPY[scope].label).join(', ')})
          </span>
        </Badge>
      ) : (
        scopes.map((scope) => (
          <Badge key={scope} variant="outline">
            {SCOPE_COPY[scope].label}
          </Badge>
        ))
      )}
    </span>
  )
}

/**
 * What the key can do in plain words, for a list: "Read and evaluate", then
 * "Also through AI assistants". Keys that can change anything read stronger
 * than read-only ones. The scope names follow for assistive tech and on hover.
 */
export function KeyAccess({
  scopes,
  muted = false,
}: {
  scopes: readonly ApiKeyScope[]
  /** An expired key: everything quiet. */
  muted?: boolean
}) {
  const { label, assistants, changes } = accessLabel(scopes)
  const names = scopes.map((scope) => SCOPE_COPY[scope].label).join(', ')
  return (
    <WithTooltip content={`Scopes: ${names}`}>
      <span className="flex min-w-0 flex-col text-sm">
        <span
          className={cn(
            muted ? 'text-muted' : changes ? 'font-medium text-primary' : 'text-secondary',
          )}
        >
          {label}
        </span>
        {assistants && <span className="text-xs text-muted">Also through AI assistants</span>}
        <span className="sr-only">. Scopes: {names}</span>
      </span>
    </WithTooltip>
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

function plural(count: number, one: string, many: string): string {
  return `${String(count)} ${count === 1 ? one : many}`
}

/**
 * "All projects", the names it is restricted to, or a warning when none is
 * left; then "+1 project you can no longer open" for restricted projects the
 * owner has lost access to (the key reaches none of them).
 */
export function KeyProjects({
  apiKey,
}: {
  apiKey: Pick<ApiKey, 'restricted' | 'projects' | 'unavailable_project_count'>
}) {
  if (!apiKey.restricted) return <span className="text-sm text-secondary">All projects</span>
  const lost = apiKey.unavailable_project_count
  return (
    <span className="flex min-w-0 flex-col text-sm">
      {apiKey.projects.length === 0 ? (
        <span className="text-warning">No projects left: it reaches nothing</span>
      ) : (
        <span className="text-secondary">
          {apiKey.projects.map((project) => project.name).join(', ')}
        </span>
      )}
      {lost > 0 && (
        <span className="text-xs text-muted">
          +{plural(lost, 'project you can no longer open', 'projects you can no longer open')}
        </span>
      )}
    </span>
  )
}

/**
 * Admin view of a key's projects: every restricted project that still exists;
 * the ones its owner can no longer open are struck through and named as such
 * (the key no longer reaches them).
 */
export function AdminKeyProjects({
  apiKey,
}: {
  apiKey: Pick<AdminApiKey, 'restricted' | 'projects' | 'unavailable_project_count'>
}) {
  if (!apiKey.restricted) return <span className="text-sm text-secondary">All projects</span>
  if (apiKey.projects.length === 0) {
    return <span className="text-sm text-warning">No projects left: it reaches nothing</span>
  }
  const reachable = apiKey.projects.length - apiKey.unavailable_project_count
  return (
    <span className="flex min-w-0 flex-col text-sm">
      <span className="text-secondary">
        {apiKey.projects.map((project, index) => (
          <Fragment key={project.id}>
            {index > 0 && ', '}
            {project.owner_can_view ? (
              <span>{project.name}</span>
            ) : (
              <WithTooltip content="The owner can no longer open this project, so the key doesn’t reach it.">
                <span className="text-muted line-through">
                  {project.name}
                  <span className="sr-only"> (the owner can no longer open it)</span>
                </span>
              </WithTooltip>
            )}
          </Fragment>
        ))}
      </span>
      {apiKey.unavailable_project_count > 0 && (
        <span className="text-xs text-warning">
          {reachable === 0
            ? 'Reaches nothing'
            : `Owner can’t open ${String(apiKey.unavailable_project_count)}`}
        </span>
      )}
    </span>
  )
}

/**
 * "Never", the expiry date, "in 2 days" in a warning tone within a week of
 * it, or "Expired" with the date it stopped.
 */
export function KeyExpiry({ apiKey }: { apiKey: Pick<ApiKey, 'expires_at' | 'state'> }) {
  const now = useNow()
  if (!apiKey.expires_at) return <span className="text-sm text-muted">Never</span>
  if (apiKey.state !== 'expired' && expiresSoon(apiKey.expires_at, now)) {
    return (
      <span className="text-sm font-medium text-warning">
        <RelativeTime date={apiKey.expires_at} />
      </span>
    )
  }
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
