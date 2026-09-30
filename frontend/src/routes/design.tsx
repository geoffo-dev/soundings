import { createFileRoute, notFound } from '@tanstack/react-router'
import { lazy } from 'react'

import { designPageEnabled } from '@/lib/env'

/**
 * Dev-only design system page. In production builds `designPageEnabled` is a
 * constant `false` (unless VITE_ENABLE_DESIGN=true), so the route 404s and the
 * page code is tree-shaken out of the bundle.
 */
// The env check is inlined (not lib/env) so the bundler can drop the import.
const DesignPage =
  import.meta.env.DEV || import.meta.env.VITE_ENABLE_DESIGN === 'true'
    ? lazy(() => import('@/features/design/design-page'))
    : () => null

export const Route = createFileRoute('/design')({
  beforeLoad: () => {
    if (!designPageEnabled) throw notFound()
  },
  head: () => ({ meta: [{ title: 'Design system · Soundings' }] }),
  component: DesignRoute,
})

function DesignRoute() {
  return <DesignPage />
}
