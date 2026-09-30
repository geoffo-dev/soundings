import { setupServer } from 'msw/node'

import { handlers } from '@/mocks/handlers'

/**
 * MSW for vitest. In a test file:
 *   beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
 *   afterEach(() => server.resetHandlers())
 *   afterAll(() => server.close())
 * and override per test with server.use(http.get(...)).
 */
export const server = setupServer(...handlers)
