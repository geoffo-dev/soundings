import { setupWorker } from 'msw/browser'

import { handlers } from '@/mocks/handlers'

export const worker = setupWorker(...handlers)

/** Started from main.tsx when VITE_API_MOCKS === "true" (npm run dev:mock). */
export async function startMockWorker(): Promise<void> {
  await worker.start({
    // Unmocked requests (Vite assets, fonts) go to the network untouched.
    onUnhandledRequest: 'bypass',
    quiet: true,
  })
}
