import { useCallback } from 'react'

import { signOutWithRedirect } from './sso'

/**
 * Signs out from the user menu or the palette: a full-page form post that ends
 * the session (and the IdP session, for SSO) and lands on /login?signed_out=1.
 */
export function useSignOut(): () => void {
  return useCallback(() => {
    void signOutWithRedirect()
  }, [])
}
