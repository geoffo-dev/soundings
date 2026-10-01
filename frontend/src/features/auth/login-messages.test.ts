import { describe, expect, it } from 'vitest'

import {
  isLoginErrorCode,
  LOGIN_ERROR_CODES,
  loginErrorMessage,
  loginMessage,
  SESSION_ENDED_MESSAGE,
  SIGNED_OUT_MESSAGE,
} from '@/features/auth/login-messages'

describe('sign-in messages (contract-phase2 §4.2)', () => {
  it('has calm copy with a next step for every documented code', () => {
    const titles = new Set<string>()
    for (const code of LOGIN_ERROR_CODES) {
      const message = loginErrorMessage(code)
      expect(message.title).toBeTruthy()
      expect(message.description).toMatch(/\.$/)
      // Never the raw code, never shouting.
      expect(message.title).not.toContain(code)
      expect(message.title).not.toMatch(/!/)
      titles.add(message.title)
    }
    expect(titles.size).toBe(LOGIN_ERROR_CODES.length)
  })

  it.each([
    ['sso_unavailable', 'Single sign-on isn’t available right now'],
    ['too_many_attempts', 'Too many sign-in attempts from your network'],
    ['login_expired', 'That sign-in took too long or was already used'],
    ['login_cancelled', 'Sign-in was cancelled'],
    ['sso_failed', 'We couldn’t verify your sign-in'],
    ['no_account', 'You don’t have a Soundings account yet'],
    ['account_disabled', 'Your account is deactivated'],
    ['identity_conflict', 'Your account needs an administrator to finish linking it'],
  ])('%s → “%s”', (code, title) => {
    expect(loginErrorMessage(code).title).toBe(title)
  })

  it('treats a cancelled sign-in as a notice, not an alarm', () => {
    expect(loginErrorMessage('login_cancelled')).toMatchObject({ role: 'status', tone: 'info' })
    expect(loginErrorMessage('sso_failed')).toMatchObject({ role: 'alert', tone: 'danger' })
  })

  it('never echoes an unknown code', () => {
    const message = loginErrorMessage('<img src=x onerror=alert(1)>')
    expect(message.title).toBe('Something went wrong signing you in')
    expect(JSON.stringify(message)).not.toMatch(/img|onerror/)
    expect(isLoginErrorCode('toString')).toBe(false)
    expect(isLoginErrorCode('no_account')).toBe(true)
  })

  it('shows one message: an error wins over signed out and expired', () => {
    expect(loginMessage({})).toBeNull()
    expect(loginMessage({ signed_out: true })).toBe(SIGNED_OUT_MESSAGE)
    expect(loginMessage({ expired: true })).toBe(SESSION_ENDED_MESSAGE)
    expect(loginMessage({ expired: true, signed_out: true })).toBe(SESSION_ENDED_MESSAGE)
    expect(loginMessage({ error: 'no_account', signed_out: true })?.title).toBe(
      'You don’t have a Soundings account yet',
    )
  })
})
