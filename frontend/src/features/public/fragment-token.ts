import { useEffect, useState } from 'react'

/**
 * Tokens in public links live after `#` (`/track#<token>`, `/verify#<token>`),
 * which browsers never send to a server (contract-phase4 §1). The page reads
 * the fragment and posts the token in a JSON body; it keeps the fragment, so
 * the tracking link can be bookmarked and reloaded.
 */

export const TRACKING_TOKEN = /^[A-Za-z0-9_-]{43}$/
export const VERIFICATION_TOKEN = /^[A-Za-z0-9_.-]{16,512}$/

/** The token in a `#…` fragment if it has the right shape, else undefined. */
export function tokenFromHash(hash: string, pattern: RegExp): string | undefined {
  let value = hash.startsWith('#') ? hash.slice(1) : hash
  try {
    value = decodeURIComponent(value)
  } catch {
    return undefined
  }
  value = value.trim()
  return pattern.test(value) ? value : undefined
}

/** The fragment's token, following `hashchange` (someone pastes another link). */
export function useFragmentToken(pattern: RegExp): string | undefined {
  const [token, setToken] = useState(() =>
    typeof window === 'undefined' ? undefined : tokenFromHash(window.location.hash, pattern),
  )
  useEffect(() => {
    const update = () => setToken(tokenFromHash(window.location.hash, pattern))
    window.addEventListener('hashchange', update)
    return () => window.removeEventListener('hashchange', update)
  }, [pattern])
  return token
}
