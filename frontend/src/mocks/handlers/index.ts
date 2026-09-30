import type { RequestHandler } from 'msw'

/**
 * All MSW handlers. Each feature owns a file in this folder exporting an array,
 * e.g. `export const ideaHandlers = [http.get('/api/v1/ideas', …)]`, and adds it
 * here. Handlers should return data shaped by the generated OpenAPI types
 * (`components['schemas'][…]`) so mocks break when the contract changes.
 */
export const handlers: RequestHandler[] = [
  // ...projectHandlers,
  // ...ideaHandlers,
]
