import { Link, useLocation } from '@tanstack/react-router'
import { MailWarning, MailX, X } from 'lucide-react'
import { useState } from 'react'

import { useNotificationSummary } from '@/api/notifications'
import { Button } from '@/components/ui/button'
import { useCurrentUser } from '@/features/auth/current-user'
import { cn } from '@/lib/utils'

type BannerKind = 'not_configured' | 'trouble'

const STORAGE_PREFIX = 'soundings-banner-dismissed:'

function readDismissed(kind: BannerKind): boolean {
  try {
    return sessionStorage.getItem(STORAGE_PREFIX + kind) === '1'
  } catch {
    return false
  }
}

function writeDismissed(kind: BannerKind) {
  try {
    sessionStorage.setItem(STORAGE_PREFIX + kind, '1')
  } catch {
    // Storage unavailable: dismissed until the page reloads.
  }
}

const COPY: Record<BannerKind, { title: string; body: string; action: string }> = {
  not_configured: {
    title: 'Email isn’t set up:',
    body: 'people only get in-app notifications.',
    action: 'Set up email',
  },
  trouble: {
    title: 'Some emails aren’t going out.',
    body: 'Soundings keeps retrying; check the outbox.',
    action: 'Open Email settings',
  },
}

/**
 * For platform admins only (contract-phase3 §3.1): a calm strip at the top of
 * the app when email isn't configured (in-app notifications only) or isn't
 * flowing (`email_trouble`: a failure in the last day, or mail queued for over
 * 15 minutes). Dismissible for the session; the trouble banner clears itself
 * once mail flows again. Not shown on the Email settings page itself.
 */
export function EmailBanner() {
  const me = useCurrentUser()
  const summary = useNotificationSummary({ enabled: me.is_platform_admin })
  const pathname = useLocation({ select: (location) => location.pathname })
  const [dismissed, setDismissed] = useState<Record<BannerKind, boolean>>(() => ({
    not_configured: readDismissed('not_configured'),
    trouble: readDismissed('trouble'),
  }))
  if (!me.is_platform_admin || !summary.data || pathname.startsWith('/settings/email')) return null
  const kind: BannerKind | null = !summary.data.email_available
    ? 'not_configured'
    : summary.data.email_trouble
      ? 'trouble'
      : null
  if (!kind || dismissed[kind]) return null
  const copy = COPY[kind]
  const Icon = kind === 'trouble' ? MailWarning : MailX

  return (
    <div
      role="status"
      data-testid="email-banner"
      className={cn(
        'flex items-center gap-x-3 gap-y-1 border-b px-4 py-2 text-sm text-primary',
        kind === 'trouble' ? 'bg-warning-subtle' : 'bg-subtle',
      )}
    >
      <Icon
        aria-hidden="true"
        className={cn('size-4 shrink-0', kind === 'trouble' ? 'text-warning' : 'text-muted')}
      />
      <p className="min-w-0 flex-1">
        <span className="font-medium">{copy.title}</span>{' '}
        <span className="text-secondary">{copy.body}</span>{' '}
        <Link
          to="/settings/email"
          className="font-medium whitespace-nowrap text-accent underline-offset-4 hover:underline"
        >
          {copy.action}
        </Link>
      </p>
      <Button
        variant="ghost"
        size="icon-sm"
        aria-label="Dismiss for this session"
        onClick={() => {
          writeDismissed(kind)
          setDismissed((current) => ({ ...current, [kind]: true }))
        }}
      >
        <X />
      </Button>
    </div>
  )
}
