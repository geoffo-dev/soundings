import type { LoginErrorCode } from '@/api/types'

/**
 * What the sign-in page says after a redirect back to it (contract-phase2 §4.2):
 * `/login?error=<code>`, `/login?signed_out=1`, or `/login?expired=1` after the
 * session ended mid-use. One calm sentence and the next step; details are in
 * the audit log only. The raw `error` value is never shown.
 */
export interface LoginMessage {
  tone: 'info' | 'success' | 'warning' | 'danger'
  title: string
  description?: string
  /** `alert` for problems (announced at once), `status` for calm notices. */
  role: 'alert' | 'status'
}

export const LOGIN_ERROR_CODES = [
  'sso_unavailable',
  'too_many_attempts',
  'login_expired',
  'login_cancelled',
  'sso_failed',
  'no_account',
  'account_disabled',
  'identity_conflict',
] as const satisfies readonly LoginErrorCode[]

const ERROR_MESSAGES: Record<LoginErrorCode, LoginMessage> = {
  sso_unavailable: {
    tone: 'warning',
    role: 'alert',
    title: 'Single sign-on isn’t available right now',
    description: 'Try again in a few minutes. If it keeps happening, tell your administrator.',
  },
  too_many_attempts: {
    tone: 'warning',
    role: 'alert',
    title: 'Too many sign-in attempts from your network',
    description: 'Wait a minute, then try again.',
  },
  login_expired: {
    tone: 'info',
    role: 'alert',
    title: 'That sign-in took too long or was already used',
    description: 'Start again: it only takes a moment.',
  },
  login_cancelled: {
    tone: 'info',
    role: 'status',
    title: 'Sign-in was cancelled',
    description: 'Sign in again whenever you’re ready.',
  },
  sso_failed: {
    tone: 'danger',
    role: 'alert',
    title: 'We couldn’t verify your sign-in',
    description: 'Try again. If it keeps happening, contact your administrator.',
  },
  no_account: {
    tone: 'warning',
    role: 'alert',
    title: 'You don’t have a Soundings account yet',
    // Signing in again reuses the identity provider's session: the page offers
    // "Use a different account" below (prompt=select_account).
    description:
      'Ask an administrator to add you, then sign in again. Signed in with the wrong account? Use a different account.',
  },
  account_disabled: {
    tone: 'danger',
    role: 'alert',
    title: 'Your account is deactivated',
    description: 'If you think this is a mistake, contact your administrator.',
  },
  identity_conflict: {
    tone: 'warning',
    role: 'alert',
    title: 'Your account needs an administrator to finish linking it',
    description:
      'Contact your administrator and tell them your sign-in couldn’t be linked to your account, or use a different account.',
  },
}

/** An error code we don't know (a newer server, or an edited URL): never echo it. */
const UNKNOWN_ERROR: LoginMessage = {
  tone: 'danger',
  role: 'alert',
  title: 'Something went wrong signing you in',
  description: 'Try again. If it keeps happening, contact your administrator.',
}

export const SIGNED_OUT_MESSAGE: LoginMessage = {
  tone: 'success',
  role: 'status',
  title: 'You’re signed out.',
}

export const SESSION_ENDED_MESSAGE: LoginMessage = {
  tone: 'info',
  role: 'status',
  title: 'Your session has ended',
  description: 'Sign in again to carry on where you left off.',
}

export function isLoginErrorCode(value: unknown): value is LoginErrorCode {
  return (LOGIN_ERROR_CODES as readonly unknown[]).includes(value)
}

export function loginErrorMessage(code: string): LoginMessage {
  return isLoginErrorCode(code) ? ERROR_MESSAGES[code] : UNKNOWN_ERROR
}

/** The one message the page shows for its search params (an error wins). */
export function loginMessage(search: {
  error?: string
  signed_out?: boolean
  expired?: boolean
}): LoginMessage | null {
  if (search.error) return loginErrorMessage(search.error)
  if (search.expired) return SESSION_ENDED_MESSAGE
  if (search.signed_out) return SIGNED_OUT_MESSAGE
  return null
}
