import { useQueryClient } from '@tanstack/react-query'
import { Send } from 'lucide-react'
import { useEffect, useState, type SyntheticEvent } from 'react'

import { TEST_POLL_LIMIT_MS, useOutboxEmail, useSendTestEmail } from '@/api/admin-email'
import { queryKeys } from '@/api/keys'
import { hasErrorCode, isApiError, type ApiError } from '@/api/errors'
import type { OutboxEmail } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Callout } from '@/components/ui/callout'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Spinner } from '@/components/ui/spinner'
import { AdminSection } from '@/features/admin/settings-frame'
import { useCurrentUser } from '@/features/auth/current-user'

import { errorHint } from './email-copy'

function minutes(seconds: number): string {
  const value = Math.max(1, Math.ceil(seconds / 60))
  return `${value} ${value === 1 ? 'minute' : 'minutes'}`
}

/**
 * Send a test email (contract-phase3 §3.10): it goes through the outbox and
 * the worker like any other email, with one attempt; the page then checks its
 * row every 2 seconds for up to 30: sent, the error, or "still queued".
 */
export function TestEmailSection({ configured }: { configured: boolean }) {
  const me = useCurrentUser()
  const send = useSendTestEmail()
  const [to, setTo] = useState('')
  const [sentId, setSentId] = useState<string | undefined>(undefined)

  const submit = (event: SyntheticEvent) => {
    event.preventDefault()
    if (send.isPending) return
    setSentId(undefined)
    send.mutate(to.trim() || null, { onSuccess: (email) => setSentId(email.id) })
  }

  const error = send.error
  const fieldError = isApiError(error) && error.status === 422 ? addressError(error, to) : undefined

  return (
    <AdminSection
      id="test-email"
      title="Send a test email"
      description="Checks the whole path: the worker, the server, TLS, the sign-in and the sender address."
    >
      <form onSubmit={submit} noValidate className="flex flex-col gap-3">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-start">
          <Field
            label="Send to"
            description={`Leave empty to send it to yourself (${me.email}).`}
            error={fieldError}
            className="min-w-0 flex-1 sm:max-w-md"
          >
            <Input
              type="email"
              inputMode="email"
              autoComplete="off"
              spellCheck={false}
              placeholder={me.email}
              value={to}
              maxLength={254}
              disabled={!configured}
              onChange={(event) => setTo(event.target.value)}
            />
          </Field>
          <Button
            type="submit"
            variant="primary"
            loading={send.isPending}
            disabled={!configured}
            className="sm:mt-6"
          >
            <Send />
            Send test email
          </Button>
        </div>
        {!configured && (
          <p className="text-sm text-muted">Set up email first (above), then try it here.</p>
        )}
        {error && !fieldError && <SendError error={error} />}
        {sentId && <TestResult emailId={sentId} />}
      </form>
    </AdminSection>
  )
}

/** Our own words for a 422 on `to` (the server's message is for developers). */
function addressError(error: ApiError, to: string): string {
  const message = (error.fieldErrors.to ?? '').toLowerCase()
  if (message.includes('.invalid')) return 'Addresses under .invalid can’t receive email.'
  if (!to.trim()) return 'Your own address can’t receive email: enter another one.'
  return 'Enter one email address, such as ops@example.com (no names or lists).'
}

function SendError({ error }: { error: Error }) {
  if (hasErrorCode(error, 'too_many_attempts')) {
    const wait = isApiError(error) ? error.retryAfterSeconds : undefined
    return (
      <Callout role="alert" tone="warning" title="That’s a lot of test emails">
        At most 5 every 10 minutes.{wait ? ` Try again in ${minutes(wait)}.` : ' Try again soon.'}
      </Callout>
    )
  }
  if (hasErrorCode(error, 'smtp_not_configured')) {
    return (
      <Callout role="alert" tone="warning" title="Email isn’t set up">
        Set smtp.host and smtp.from in the Helm values, then upgrade the release.
      </Callout>
    )
  }
  return (
    <Callout role="alert" tone="danger" title="Couldn’t queue the test email">
      Check your connection and try again.
    </Callout>
  )
}

/** Follows the queued test email until it is sent, fails, or 30 seconds pass. */
function TestResult({ emailId }: { emailId: string }) {
  const queryClient = useQueryClient()
  const [timedOut, setTimedOut] = useState(false)
  const email = useOutboxEmail(emailId, { poll: !timedOut })
  const settled = email.data && !['queued', 'sending'].includes(email.data.status)

  // Sent or failed: the counters and the outbox below have changed.
  useEffect(() => {
    if (!settled) return
    void queryClient.invalidateQueries({ queryKey: queryKeys.admin.emailConfig() })
    void queryClient.invalidateQueries({ queryKey: queryKeys.admin.outboxes() })
    void queryClient.invalidateQueries({ queryKey: queryKeys.notifications.summary() })
  }, [settled, queryClient])

  useEffect(() => {
    const timer = window.setTimeout(() => setTimedOut(true), TEST_POLL_LIMIT_MS)
    return () => window.clearTimeout(timer)
  }, [])

  const data = email.data
  const waiting = !data || data.status === 'queued' || data.status === 'sending'
  if (waiting && !timedOut) {
    return (
      <p role="status" className="flex items-center gap-2 text-sm text-secondary">
        <Spinner className="text-muted" />
        {data?.status === 'sending' ? 'Sending…' : 'Queued, waiting for the worker…'}
      </p>
    )
  }
  if (waiting) {
    return (
      <Callout role="status" tone="warning" title="Still queued: is the worker running?">
        Nothing has picked it up in 30 seconds. Check that the worker deployment is up and can reach
        the database; the email goes out as soon as it is.
      </Callout>
    )
  }
  return <TestOutcome email={data} />
}

function TestOutcome({ email }: { email: OutboxEmail }) {
  const to = email.recipient?.display_name ?? email.address_hint ?? 'the address'
  if (email.status === 'sent') {
    return (
      <Callout role="status" tone="success" title={`Sent to ${to}`}>
        The server accepted it. If it doesn’t arrive, check the spam folder and the sender address’s
        SPF and DKIM records.
      </Callout>
    )
  }
  const hint = errorHint(email.last_error)
  return (
    <Callout
      role="alert"
      tone="danger"
      title={email.status === 'cancelled' ? 'Not sent' : 'The test email failed'}
    >
      <span className="font-medium text-primary">{email.last_error ?? 'No reason given'}</span>
      {hint && <span className="block">{hint}</span>}
    </Callout>
  )
}
