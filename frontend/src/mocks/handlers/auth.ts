import { currentUser, findUser } from '@/mocks/domain'
import {
  allowOnly,
  failValidation,
  json,
  noContent,
  publicRoute,
  readJson,
  route,
} from '@/mocks/http'
import { endSession, startSession } from '@/mocks/session'

import { isUuid } from '@/mocks/handlers/common'

export const authHandlers = [
  route('get', '/auth/me', ({ user }) => currentUser(user)),

  publicRoute('get', '/auth/dev/users', ({ db }) =>
    db.users
      .filter((user) => user.is_active && !user.is_service_account)
      .sort(
        (a, b) =>
          Number(b.is_platform_admin) - Number(a.is_platform_admin) ||
          a.display_name.localeCompare(b.display_name),
      )
      .map(currentUser),
  ),

  publicRoute('post', '/auth/dev/login', async ({ request, db }) => {
    const body = await readJson(request)
    allowOnly(body, ['user_id'])
    if (!isUuid(body.user_id)) {
      failValidation([
        { loc: ['body', 'user_id'], msg: 'Input should be a valid UUID', type: 'uuid_parsing' },
      ])
    }
    const user = findUser(db, body.user_id.toLowerCase())
    if (!user?.is_active) {
      failValidation(
        [{ loc: ['body', 'user_id'], msg: 'Unknown or inactive user', type: 'user_not_found' }],
        'user_not_found',
      )
    }
    startSession(user.id)
    return json(currentUser(user))
  }),

  publicRoute('post', '/auth/logout', () => {
    endSession()
    return noContent()
  }),
]
