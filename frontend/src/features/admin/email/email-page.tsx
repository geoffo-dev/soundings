import { useLocation } from '@tanstack/react-router'
import { Lock, LockOpen, Mail } from 'lucide-react'
import { useEffect, useState, type ReactNode } from 'react'

import { useEmailConfig } from '@/api/admin-email'
import { useNotificationSummary } from '@/api/notifications'
import type { EmailConfig, EmailStatus } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Callout } from '@/components/ui/callout'
import { EmptyState } from '@/components/ui/empty-state'
import { RelativeTime, useNow } from '@/components/ui/relative-time'
import { Skeleton, SkeletonGroup } from '@/components/ui/skeleton'
import { CopyButton } from '@/features/admin/copy-button'
import { AdminPageHeader, AdminSection } from '@/features/admin/settings-frame'

import { reminderDaysText, scheduleTime, SECURITY } from './email-copy'
import { defaultStatuses, effectiveStatuses, type EmailSearch } from './email-search'
import { OutboxSection } from './outbox-section'
import { TestEmailSection } from './test-email'

/**
 * Admin settings → Email (contract-phase3 §3.10, wireframe 07), in the order
 * an admin needs it: whether email works, the outbox with retry (the banner
 * links straight to it, `#outbox`), a test email, the SMTP settings in effect
 * (read-only: Helm values `smtp.*`, the credentials from a Secret and never
 * shown) and the schedule. Without SMTP, only how to set it up.
 */
export function EmailPage({
  search,
  onSearchChange,
}: {
  search: EmailSearch
  onSearchChange: (patch: Partial<EmailSearch>) => void
}) {
  const query = useEmailConfig()
  return (
    <>
      <AdminPageHeader
        title="Email"
        description={
          <>
            Set in the Helm values (<Code>smtp.*</Code>); read-only here.
          </>
        }
      />
      {query.data ? (
        <EmailDetails config={query.data} search={search} onSearchChange={onSearchChange} />
      ) : query.isError ? (
        <EmptyState
          role="alert"
          size="compact"
          className="rounded-lg border"
          icon={<Mail />}
          title="Couldn’t load the email settings"
          description="Check your connection and try again."
          action={
            <Button variant="secondary" onClick={() => void query.refetch()}>
              Try again
            </Button>
          }
        />
      ) : (
        <SkeletonGroup label="Loading the email settings" className="flex flex-col gap-8">
          <Skeleton className="h-16 w-full" />
          {[0, 1].map((i) => (
            <div key={i} className="flex flex-col gap-2.5">
              <Skeleton className="h-4 w-32" />
              <Skeleton className="h-4 w-full max-w-lg" />
              <Skeleton className="h-4 w-full max-w-md" />
            </div>
          ))}
        </SkeletonGroup>
      )}
    </>
  )
}

function Code({ children }: { children: ReactNode }) {
  return <code className="font-mono text-secondary">{children}</code>
}

/** How long mail may wait before the page (and the admin banner) call it stuck. */
const STUCK_MS = 15 * 60_000

function EmailDetails({
  config,
  search,
  onSearchChange,
}: {
  config: EmailConfig
  search: EmailSearch
  onSearchChange: (patch: Partial<EmailSearch>) => void
}) {
  const now = useNow()
  const { outbox, configured } = config
  const stuck =
    outbox.oldest_queued_at !== null && Date.parse(outbox.oldest_queued_at) < now - STUCK_MS
  // The default filter is chosen once, as the page opens (what needs attention), so the
  // list doesn't jump to "All" under the admin's cursor when Retry empties "Failed".
  const [defaults] = useState<EmailStatus[]>(() => defaultStatuses(outbox, stuck))
  const status = effectiveStatuses(search.status, defaults)
  const [testQueued, setTestQueued] = useState(false)
  useScrollToSection(configured)

  // Without SMTP only what helps: how to set it up (no test form, outbox or server).
  return (
    <div className="flex flex-col gap-10">
      <StatusCallout config={config} stuck={stuck} testQueued={testQueued} />
      {!configured && <SetupChecklist />}
      {configured && (
        <OutboxSection
          stats={outbox}
          status={status}
          type={search.type ?? []}
          onChange={onSearchChange}
        />
      )}
      {configured && <TestEmailSection onStillQueued={setTestQueued} />}
      {configured && <ServerSettings config={config} />}
      <Schedule config={config} />
    </div>
  )
}

/**
 * `/settings/email#outbox` (the admin banner) and the other sections' ids:
 * the section is only there once the settings have loaded, so scroll to it
 * then, and move focus to its heading for keyboard and screen reader users.
 */
function useScrollToSection(ready: boolean) {
  const hash = useLocation({ select: (location) => location.hash })
  useEffect(() => {
    if (!ready || !hash) return
    const section = document.getElementById(hash)
    const heading = document.getElementById(`${hash}-heading`)
    if (section?.tagName !== 'SECTION') return
    section.scrollIntoView({ block: 'start' })
    if (heading) {
      heading.tabIndex = -1
      heading.focus({ preventScroll: true })
    }
  }, [hash, ready])
}

function StatusCallout({
  config,
  stuck,
  testQueued,
}: {
  config: EmailConfig
  /** Mail has waited more than 15 minutes. */
  stuck: boolean
  /** A test email sent from this page is still waiting for the worker. */
  testQueued: boolean
}) {
  const summary = useNotificationSummary()
  const { outbox } = config
  if (!config.configured) {
    return (
      <Callout tone="warning" title="Email isn’t set up">
        Soundings works without it: people get in-app notifications only. Nothing is queued while
        it’s off.
      </Callout>
    )
  }
  if (testQueued && !stuck && !summary.data?.email_trouble) {
    return (
      <Callout role="status" tone="warning" title="Email may not be going out">
        Your test email is still waiting to be sent: is the worker running?
      </Callout>
    )
  }
  if (summary.data?.email_trouble || stuck) {
    return (
      <Callout role="status" tone="warning" title="Some emails aren’t going out">
        {stuck && outbox.oldest_queued_at ? (
          <>
            {outbox.queued.toLocaleString()} queued, the oldest since{' '}
            <RelativeTime date={outbox.oldest_queued_at} />: is the worker running, and can it reach{' '}
            <Code>{config.host}</Code>?{' '}
          </>
        ) : null}
        {outbox.failed > 0 &&
          `${outbox.failed.toLocaleString()} failed: retry them below once the cause is fixed.`}
      </Callout>
    )
  }
  return (
    <Callout tone="success" title="Email is on">
      {outbox.sent_last_24h.toLocaleString()} sent in the last 24 hours
      {outbox.last_sent_at ? (
        <>
          , the last <RelativeTime date={outbox.last_sent_at} />
        </>
      ) : null}
      .
    </Callout>
  )
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <dt className="text-sm text-muted sm:leading-8">{label}</dt>
      <dd className="flex min-h-8 min-w-0 flex-wrap items-center gap-x-2 text-sm text-primary">
        {children}
      </dd>
    </>
  )
}

/** Credentials come from the Secret (`smtp.existingSecret`) and are never sent to the browser. */
function Secret({ set, masked, unset }: { set: boolean; masked?: boolean; unset: string }) {
  return set ? (
    <span className="inline-flex items-center gap-1.5 text-secondary">
      <Lock aria-hidden="true" className="size-3.5 text-muted" />
      {masked && (
        <span aria-hidden="true" className="tracking-widest">
          ••••••••
        </span>
      )}
      Set (never shown)
    </span>
  ) : (
    <span className="inline-flex items-center gap-1.5 text-secondary">
      <LockOpen aria-hidden="true" className="size-3.5 text-muted" />
      {unset}
    </span>
  )
}

function ServerSettings({ config }: { config: EmailConfig }) {
  const security = SECURITY[config.security]
  const server = `${config.host ?? ''}:${config.port}`
  return (
    <AdminSection id="server" title="Server" description="What the worker uses to send email.">
      <dl className="grid grid-cols-1 gap-x-6 gap-y-1 sm:grid-cols-[10rem_minmax(0,1fr)]">
        <Row label="Server">
          <code className="min-w-0 truncate font-mono" title={server}>
            {server}
          </code>
          <CopyButton value={server} label="server" />
        </Row>
        <Row label="Security">
          <span className="font-medium">{security.label}</span>
          <span className="text-muted">{security.description}</span>
        </Row>
        <Row label="Username">
          <Secret set={config.username_set} unset="Not set: no sign-in" />
        </Row>
        <Row label="Password">
          <Secret set={config.password_set} masked unset="Not set" />
        </Row>
        <Row label="From">
          <span className="min-w-0 truncate">
            {config.from_name} &lt;{config.from_address ?? 'not set'}&gt;
          </span>
        </Row>
        <Row label="Reply-to">
          {config.reply_to ? (
            <span className="min-w-0 truncate">{config.reply_to}</span>
          ) : (
            <span className="text-secondary">None: replies go to the sender address</span>
          )}
        </Row>
        <Row label="CA bundle">
          {config.ca_bundle ? (
            <code className="min-w-0 truncate font-mono" title={config.ca_bundle}>
              {config.ca_bundle}
            </code>
          ) : (
            <span className="text-secondary">System trust store</span>
          )}
        </Row>
        <Row label="Timeout">
          <span className="tabular-nums">{config.timeout_seconds} s</span>
          <span className="text-muted">per connection and command</span>
        </Row>
        <Row label="Links in emails">
          <code className="min-w-0 truncate font-mono" title={config.links_base_url}>
            {config.links_base_url}
          </code>
        </Row>
      </dl>
    </AdminSection>
  )
}

function Schedule({ config }: { config: EmailConfig }) {
  return (
    <AdminSection
      id="schedule"
      title="Digests and reminders"
      description={
        <>
          {!config.configured && 'They start once email is on. '}
          Instance settings (<Code>SOUNDINGS_TIMEZONE</Code>, <Code>SOUNDINGS_DIGEST_HOUR</Code>,{' '}
          <Code>SOUNDINGS_REMINDER_DAYS</Code>).
        </>
      }
    >
      <dl className="grid grid-cols-1 gap-x-6 gap-y-1 sm:grid-cols-[10rem_minmax(0,1fr)]">
        <Row label="Daily digest">{`Every day at ${scheduleTime(config)}`}</Row>
        <Row label="Evaluation reminders">
          {config.reminder_days.length > 0
            ? `${reminderDaysText(config.reminder_days)}, at ${scheduleTime(config)}`
            : 'Off'}
        </Row>
      </dl>
    </AdminSection>
  )
}

function SetupChecklist() {
  const steps: { title: string; body: ReactNode }[] = [
    {
      title: 'Point Soundings at an SMTP server',
      body: (
        <>
          Set <Code>smtp.host</Code>, <Code>smtp.port</Code> and <Code>smtp.security</Code> (
          <Code>starttls</Code> by default; <Code>tls</Code> for port 465).
        </>
      ),
    },
    {
      title: 'Choose the sender',
      body: (
        <>
          <Code>smtp.from</Code> (required) and optionally <Code>smtp.fromName</Code> and{' '}
          <Code>smtp.replyTo</Code>.
        </>
      ),
    },
    {
      title: 'Add credentials and upgrade',
      body: (
        <>
          A Secret with <Code>username</Code> and <Code>password</Code> in{' '}
          <Code>smtp.existingSecret</Code> (and <Code>smtp.caBundle.configMap</Code> for a private
          CA), then <Code>helm upgrade</Code>. Come back here and send a test email.
        </>
      ),
    },
  ]
  return (
    <AdminSection
      id="setup"
      title="Set up email"
      description="Three steps in the Helm values. Until then, notifications are in-app only."
    >
      <ol className="flex flex-col divide-y divide-subtle rounded-lg border">
        {steps.map((step, index) => (
          <li key={step.title} className="flex items-start gap-3 px-4 py-3">
            <span
              aria-hidden="true"
              className="mt-px inline-flex size-5 shrink-0 items-center justify-center rounded-full bg-subtle text-xs font-medium text-secondary tabular-nums"
            >
              {index + 1}
            </span>
            <div className="flex min-w-0 flex-1 flex-col gap-0.5">
              <span className="text-sm font-medium text-primary">
                <span className="sr-only">Step {index + 1}: </span>
                {step.title}
              </span>
              <p className="text-sm text-muted">{step.body}</p>
            </div>
          </li>
        ))}
      </ol>
    </AdminSection>
  )
}
