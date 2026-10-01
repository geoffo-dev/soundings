import type { EmailConfig, EmailStatus, EmailType, SmtpSecurity } from '@/api/types'

/**
 * Words for Admin → Email (contract-phase3 §3.10): email types and statuses,
 * the security modes, the schedule, and what to check for a given error. The
 * API's `last_error` is already a fixed phrase ("SMTP 535: authentication
 * failed", "connection refused"); it is shown as plain text, never as HTML.
 */

export const EMAIL_TYPE_LABEL: Record<EmailType, string> = {
  owner_assigned: 'Made owner',
  evaluator_invited: 'Evaluation invitation',
  evaluation_reminder: 'Evaluation reminder',
  evaluations_complete: 'All evaluations in',
  status_changed: 'Status change',
  comment: 'New comment',
  mention: '@mention',
  digest: 'Daily digest',
  test: 'Test email',
  submission_received: 'Submission received',
  submission_status_changed: 'Submission update',
}

export type StatusTone = 'success' | 'neutral' | 'info' | 'danger' | 'muted'

export const EMAIL_STATUS: Record<EmailStatus, { label: string; tone: StatusTone }> = {
  sent: { label: 'Sent', tone: 'success' },
  queued: { label: 'Queued', tone: 'neutral' },
  sending: { label: 'Sending', tone: 'info' },
  failed: { label: 'Failed', tone: 'danger' },
  cancelled: { label: 'Not sent', tone: 'muted' },
}

export const SECURITY: Record<SmtpSecurity, { label: string; description: string }> = {
  none: {
    label: 'None (plain SMTP)',
    description: 'Unencrypted: only for a relay inside the cluster or a test server.',
  },
  starttls: {
    label: 'STARTTLS',
    description: 'Upgrades to TLS after connecting; the certificate and host name are checked.',
  },
  tls: {
    label: 'TLS',
    description: 'Encrypted from the start (usually port 465); the certificate is checked.',
  },
}

/** "08:00 (Europe/London)". */
export function scheduleTime(config: Pick<EmailConfig, 'digest_hour' | 'timezone'>): string {
  return `${String(config.digest_hour).padStart(2, '0')}:00 (${config.timezone})`
}

/** "2 days before the due date and on the day" from `[2, 0]`; "Off" for none. */
export function reminderDaysText(days: readonly number[]): string {
  if (days.length === 0) return 'Off'
  const parts = [...days]
    .sort((a, b) => b - a)
    .map((day) => (day === 0 ? 'on the due date' : `${day} ${day === 1 ? 'day' : 'days'} before`))
  const text =
    parts.length === 1
      ? (parts[0] ?? '')
      : `${parts.slice(0, -1).join(', ')} and ${parts.at(-1) ?? ''}`
  return text.charAt(0).toUpperCase() + text.slice(1)
}

/**
 * What to check for an error phrase (the API's fixed `last_error` phrases,
 * contract-phase3 §3.9). Null when there's nothing more useful to say.
 */
export function errorHint(lastError: string | null): string | null {
  if (!lastError) return null
  const text = lastError.toLowerCase()
  if (text.includes('authentication') || /smtp 53[0458]/.test(text)) {
    return 'Check the username and password in the SMTP Secret (smtp.existingSecret).'
  }
  if (text.includes('certificate')) {
    return 'The server’s certificate isn’t trusted: set the CA bundle (smtp.caBundle.configMap) or check the host name.'
  }
  if (text.includes('tls') || text.includes('starttls')) {
    return 'Check the security mode and port (STARTTLS usually 587, TLS 465).'
  }
  if (text.includes('connection') || text.includes('timed out') || text.includes('disconnected')) {
    return 'Soundings can’t reach the server: check the host, port, network policy and firewall.'
  }
  if (text.includes('recipient')) return 'The server refused that address.'
  if (text.includes('sender')) return 'The server refused the From address (smtp.from).'
  if (text.includes('unusable address')) return 'The address isn’t one plain email address.'
  return null
}
