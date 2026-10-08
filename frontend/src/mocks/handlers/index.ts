import type { RequestHandler } from 'msw'

import { activityHandlers } from './activity'
import { adminHandlers } from './admin'
import { adminEmailHandlers } from './admin-email'
import { aiHandlers } from './ai'
import { apiKeyHandlers } from './api-keys'
import { authHandlers } from './auth'
import { brandingHandlers } from './branding'
import { evaluationHandlers } from './evaluations'
import { groupHandlers } from './groups'
import { ideaHandlers } from './ideas'
import { notificationHandlers } from './notifications'
import { projectHandlers } from './projects'
import { proposalHandlers } from './proposals'
import { publicHandlers } from './public'
import { researchHandlers } from './research'
import { submissionHandlers } from './submissions'
import { suggestionHandlers } from './suggestions'
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
  ...adminEmailHandlers,
  ...notificationHandlers,
  // Phase 4 (contract-phase4)
  ...proposalHandlers,
  ...publicHandlers,
  ...submissionHandlers,
  ...brandingHandlers,
  // Phase 5 (contract-phase5)
  ...apiKeyHandlers,
  ...suggestionHandlers,
  // Phase 6 (contract-phase6)
  ...aiHandlers,
  // Phase 8 (contract-phase8)
  ...researchHandlers,
]
