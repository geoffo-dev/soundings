import '@fontsource-variable/inter'
import '@/styles/index.css'

import { RouterProvider } from '@tanstack/react-router'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import { restoreRememberedBranding } from '@/lib/branding'
import { router } from '@/router'

async function enableMocks() {
  // Inline env check (not lib/env) so production builds tree-shake MSW away.
  if (import.meta.env.VITE_API_MOCKS !== 'true') return
  const { startMockWorker } = await import('@/mocks/browser')
  await startMockWorker()
}

// The instance's branding from the last visit, before anything renders (no flash).
restoreRememberedBranding()

const container = document.getElementById('root')
if (!container) throw new Error('Missing #root element')

void enableMocks().then(() => {
  createRoot(container).render(
    <StrictMode>
      <RouterProvider router={router} />
    </StrictMode>,
  )
})
