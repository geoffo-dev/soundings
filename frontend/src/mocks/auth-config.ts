/**
 * The mock instance's sign-in configuration (contract-phase2 §3.1, §3.10), set
 * with localStorage knobs so every login page variant can be shown and tested:
 *
 *   soundings-mock-auth          comma list of `sso`, `dev_login`, `break_glass`
 *                                (default `sso,dev_login`; `none` = nothing configured).
 *                                Break-glass is only available while SSO is off, as in
 *                                the real app.
 *   soundings-mock-sso-user      fixture user the mock IdP signs in as (default `alice`).
 *   soundings-mock-sso-error     a sign-in error code: the mock IdP round trip ends at
 *                                /login?error=<code> instead (e.g. `no_account`).
 *   soundings-mock-sso-discovery `ok` (default), `unreachable`, `invalid` or
 *                                `issuer_mismatch` for Admin → Sign-in.
 *
 * The break-glass credentials of the mock are `break-glass` / `correct horse battery staple`.
 */
import type { MockAuthMethod } from './session'

export const MOCK_AUTH_STORAGE_KEY = 'soundings-mock-auth'
export const MOCK_SSO_USER_STORAGE_KEY = 'soundings-mock-sso-user'
export const MOCK_SSO_ERROR_STORAGE_KEY = 'soundings-mock-sso-error'
export const MOCK_SSO_DISCOVERY_STORAGE_KEY = 'soundings-mock-sso-discovery'

export const MOCK_ISSUER = 'http://localhost:8080/realms/soundings'
export const MOCK_BREAK_GLASS_USERNAME = 'break-glass'
export const MOCK_BREAK_GLASS_PASSWORD = 'correct horse battery staple'

export interface MockAuthConfig {
  sso: boolean
  dev_login: boolean
  /** Enabled with credentials set (the Secret); available only while SSO is off. */
  break_glass_enabled: boolean
  break_glass: boolean
}

export function readSetting(key: string): string | null {
  try {
    return typeof localStorage === 'undefined' ? null : localStorage.getItem(key)
  } catch {
    return null
  }
}

export function mockAuthConfig(): MockAuthConfig {
  const raw = readSetting(MOCK_AUTH_STORAGE_KEY) ?? 'sso,dev_login'
  const methods = new Set(
    raw
      .split(',')
      .map((part) => part.trim())
      .filter(Boolean),
  )
  const sso = methods.has('sso')
  const breakGlassEnabled = methods.has('break_glass')
  return {
    sso,
    dev_login: methods.has('dev_login'),
    break_glass_enabled: breakGlassEnabled,
    break_glass: breakGlassEnabled && !sso,
  }
}

/** Sessions follow their method's availability (contract-phase2 §3.9). */
export function methodAvailable(method: MockAuthMethod, config = mockAuthConfig()): boolean {
  if (method === 'sso') return config.sso
  if (method === 'break_glass') return config.break_glass
  return config.dev_login
}

export type MockDiscoveryStatus = 'ok' | 'unreachable' | 'invalid' | 'issuer_mismatch'

export function mockDiscoveryStatus(): MockDiscoveryStatus {
  const value = readSetting(MOCK_SSO_DISCOVERY_STORAGE_KEY)
  return value === 'unreachable' || value === 'invalid' || value === 'issuer_mismatch'
    ? value
    : 'ok'
}
