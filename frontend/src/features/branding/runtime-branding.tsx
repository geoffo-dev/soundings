import { useEffect, useLayoutEffect } from 'react'

import { useEffectiveBranding } from '@/api/branding'
import type { EffectiveBranding } from '@/api/types'
import { setBrandingOverride, setGlobalBranding } from '@/lib/branding'

/**
 * Applies the instance's branding (GET /branding) to the whole SPA: colours
 * and font through CSS variables, the favicon and the app name in the title
 * (contract-phase4 §3.10). Mounted once in the root route; the remembered copy
 * was already applied before the first render (main.tsx), so nothing flashes.
 */
export function RuntimeBranding() {
  const { data } = useEffectiveBranding()
  useEffect(() => {
    if (data) setGlobalBranding(data)
  }, [data])
  return null
}

/**
 * A public page shows its project's effective branding while it is mounted
 * (the form, /track and /verify), then the global branding comes back.
 */
export function useBrandingOverride(branding: EffectiveBranding | undefined | null): void {
  useLayoutEffect(() => {
    if (!branding) return
    setBrandingOverride(branding)
    return () => setBrandingOverride(null)
  }, [branding])
}
