import type { MouseEvent } from 'react'

import { flushPendingCommits } from '@/api/undo'
import { clearDrafts } from '@/lib/drafts'

import { safeNextPath } from './session'

/**
 * Single sign-on and sign-out are **browser navigations**, never fetches
 * (contract-phase2 §1): the API answers with redirects to and from the IdP, sets
 * the HttpOnly session cookie itself, and the SPA never sees a token.
 */
export const SSO_LOGIN_PATH = '/api/v1/auth/login'
export const LOGOUT_REDIRECT_PATH = '/api/v1/auth/logout/redirect'

/** Inline (not lib/env) so production builds drop the mock IdP. */
const MOCKS = import.meta.env.VITE_API_MOCKS === 'true'

/** `GET /auth/login?next=…`: where the "Sign in with SSO" link points. */
export function ssoLoginHref(next?: string): string {
  const target = safeNextPath(next)
  return target === '/' ? SSO_LOGIN_PATH : `${SSO_LOGIN_PATH}?next=${encodeURIComponent(target)}`
}

/**
 * Click handler of the SSO link. Real builds let the browser follow the link;
 * `dev:mock` (MSW never sees navigations) runs the stand-in IdP of mocks/sso.ts.
 */
export function followSsoLink(event: MouseEvent<HTMLAnchorElement>, next?: string): void {
  if (!MOCKS) return
  event.preventDefault()
  void import('@/mocks/sso').then(({ mockSsoSignIn }) => {
    mockSsoSignIn(safeNextPath(next))
  })
}

let signedOut = false

/**
 * "Sign out" (contract-phase2 §3.9): sends deferred deletes while the session
 * still works, then posts a plain HTML form to `POST /auth/logout/redirect`,
 * which ends the session and redirects (303) to the IdP's end-session endpoint
 * (SSO) or to /login?signed_out=1. Unsent drafts go with the session once the
 * page is really left (not if an unsaved-changes prompt keeps you here).
 */
export async function signOutWithRedirect(): Promise<void> {
  await flushPendingCommits({ keepalive: false })
  window.addEventListener('pagehide', () => clearDrafts(), { once: true })
  if (!signedOut) {
    signedOut = true
    // Back after signing out may restore this page from the bfcache: reload it, so
    // the auth guard sends you to /login instead of showing the old page.
    window.addEventListener('pageshow', (event) => {
      if (event.persisted) window.location.reload()
    })
  }
  if (MOCKS) {
    const { mockLogoutRedirect } = await import('@/mocks/sso')
    mockLogoutRedirect()
    return
  }
  const form = document.createElement('form')
  form.method = 'post'
  form.action = LOGOUT_REDIRECT_PATH
  form.hidden = true
  document.body.append(form)
  form.submit()
}
