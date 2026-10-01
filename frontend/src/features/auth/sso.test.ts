import { describe, expect, it } from 'vitest'

import {
  breakGlassLanding,
  breakGlassProblem,
  waitDescription,
} from '@/features/auth/break-glass-form'
import { offersDifferentAccount, ssoLoginHref } from '@/features/auth/sso'
import { ApiError } from '@/api/errors'

describe('ssoLoginHref', () => {
  it('starts the SSO flow and carries a safe next path', () => {
    expect(ssoLoginHref()).toBe('/api/v1/auth/login')
    expect(ssoLoginHref('/')).toBe('/api/v1/auth/login')
    expect(ssoLoginHref('/p/internal-tools?view=list&owner=me')).toBe(
      '/api/v1/auth/login?next=%2Fp%2Finternal-tools%3Fview%3Dlist%26owner%3Dme',
    )
  })

  it('asks the IdP for its account picker when switching accounts', () => {
    expect(ssoLoginHref(undefined, 'select_account')).toBe(
      '/api/v1/auth/login?prompt=select_account',
    )
    expect(ssoLoginHref('/ideas/CUST-1', 'select_account')).toBe(
      '/api/v1/auth/login?next=%2Fideas%2FCUST-1&prompt=select_account',
    )
    expect(ssoLoginHref('//evil.example.com', 'login')).toBe('/api/v1/auth/login?prompt=login')
  })

  it('offers a different account only when the IdP signed in someone unusable', () => {
    expect(offersDifferentAccount('no_account')).toBe(true)
    expect(offersDifferentAccount('identity_conflict')).toBe(true)
    for (const other of [undefined, '', 'sso_failed', 'account_disabled', 'login_cancelled']) {
      expect(offersDifferentAccount(other)).toBe(false)
    }
  })

  it.each([
    ['protocol-relative', '//evil.example.com'],
    ['backslash', '/\\evil.example.com'],
    ['absolute URL', 'https://evil.example.com/'],
    ['the login page', '/login?error=no_account'],
    ['a newline', '/ideas/CUST-1\r\nSet-Cookie: x'],
  ])('drops an unsafe next (%s)', (_name, next) => {
    expect(ssoLoginHref(next)).toBe('/api/v1/auth/login')
  })
})

describe('break-glass form copy', () => {
  it('words the wait after too many attempts', () => {
    expect(waitDescription(10)).toBe('a few seconds')
    expect(waitDescription(70)).toBe('about a minute')
    expect(waitDescription(14 * 60 + 20)).toBe('about 14 minutes')
  })

  it.each([
    [401, 'invalid_credentials', 'That username and password don’t match'],
    [403, 'account_disabled', 'The break-glass account is deactivated'],
    [404, 'not_found', 'Break-glass sign-in is off'],
    [500, 'internal_error', 'Something went wrong on our side'],
  ])('%i %s → “%s”', (status, code, title) => {
    expect(breakGlassProblem(new ApiError({ status, code, title: 'x' })).title).toBe(title)
  })

  it('says how long to wait from Retry-After', () => {
    const error = new ApiError({
      status: 429,
      code: 'too_many_attempts',
      title: 'Too Many Requests',
      retryAfterSeconds: 600,
    })
    expect(breakGlassProblem(error).description).toContain('about 10 minutes')
  })
})

describe('breakGlassLanding', () => {
  it('lands on the sign-in settings unless sent from a page', () => {
    expect(breakGlassLanding(undefined)).toBe('/settings/sso')
    expect(breakGlassLanding('/')).toBe('/settings/sso')
    expect(breakGlassLanding('//evil.example.com')).toBe('/settings/sso')
    expect(breakGlassLanding('/settings/users?q=lena')).toBe('/settings/users?q=lena')
  })
})
