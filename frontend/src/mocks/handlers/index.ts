import type { RequestHandler } from 'msw'

import { activityHandlers } from './activity'
import { adminHandlers } from './admin'
import { authHandlers } from './auth'
import { evaluationHandlers } from './evaluations'
import { groupHandlers } from './groups'
import { ideaHandlers } from './ideas'
import { projectHandlers } from './projects'
import { userHandlers } from './users'
import { workHandlers } from './work'

/**
 * Every operation in the OpenAPI contract, backed by the in-memory database in
 * `../db.ts` and the rules in `../domain.ts`. `handlers.test.ts` fails when an
 * operation_id has no handler. Override one in a test with `server.use(...)`.
 */
export const handlers: RequestHandler[] = [
  ...authHandlers,
  ...userHandlers,
  ...projectHandlers,
  ...ideaHandlers,
  ...evaluationHandlers,
  ...activityHandlers,
  ...workHandlers,
  ...groupHandlers,
  ...adminHandlers,
]
