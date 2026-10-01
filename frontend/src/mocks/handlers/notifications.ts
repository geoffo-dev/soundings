import type { NotificationMode, NotificationType } from '@/api/types'
import { findIdea, isValidIdeaRef, canViewIdea, paginate } from '@/mocks/domain'
import {
  allowOnly,
  failValidation,
  noContent,
  notFound,
  publicRoute,
  queryBool,
  queryLimit,
  readJson,
  route,
} from '@/mocks/http'
import {
  inbox,
  notificationItem,
  notificationPreferences,
  notificationSummary,
  NOTIFICATION_TYPES,
  readUnsubscribeToken,
  runMockWorker,
  scopeTypes,
  setPreference,
  unsubscribeInfo,
} from '@/mocks/notifications'

import { uuidParam } from '@/mocks/handlers/common'

const MODES: NotificationMode[] = ['immediate', 'digest', 'off']
const TOKEN = /^[A-Za-z0-9_.-]{16,512}$/

/** `?token=`: 422 when missing or malformed (charset, 16–512 characters). */
function tokenParam(url: URL): string {
  const token = url.searchParams.get('token')
  if (token === null) {
    failValidation([{ loc: ['query', 'token'], msg: 'Field required', type: 'missing' }])
  }
  if (!TOKEN.test(token)) {
    failValidation([
      {
        loc: ['query', 'token'],
        msg: 'Invalid unsubscribe token',
        type: 'string_pattern_mismatch',
      },
    ])
  }
  return token
}

/**
 * The inbox, email preferences and unsubscribe links (contract-phase3 §2):
 * signed in for the inbox and preferences; no session (and no CSRF) for the
 * unsubscribe page, whose signed token is the authority.
 */
export const notificationHandlers = [
  route('get', '/me/notifications', ({ url, db, user }) => {
    const unread = queryBool(url, 'unread')
    const limit = queryLimit(url, 30, 100)
    const rows = inbox(db, user, unread)
    const { page, next_cursor } = paginate(
      rows,
      url.searchParams.get('cursor'),
      limit,
      `notifications:${user.id}:${unread ? 'unread' : 'all'}`,
    )
    return {
      items: page.flatMap((n) => notificationItem(db, n, user) ?? []),
      next_cursor,
    }
  }),

  route('get', '/me/notifications/summary', ({ db, user }) => {
    runMockWorker(db)
    return notificationSummary(db, user)
  }),

  route('post', '/me/notifications/read-all', ({ url, db, user }) => {
    const ref = url.searchParams.get('idea')
    let ideaId: string | null = null
    if (ref) {
      if (!isValidIdeaRef(ref)) {
        failValidation([
          {
            loc: ['query', 'idea'],
            msg: 'Invalid idea id or key',
            type: 'string_pattern_mismatch',
          },
        ])
      }
      const idea = findIdea(db, ref)
      if (!idea || !canViewIdea(db, idea, user)) notFound('Idea not found.')
      ideaId = idea.id
    }
    const now = new Date().toISOString()
    for (const n of db.notifications) {
      if (n.user_id !== user.id || n.read_at !== null) continue
      if (ideaId && n.idea_id !== ideaId) continue
      n.read_at = now
    }
    return notificationSummary(db, user)
  }),

  route('post', '/me/notifications/:notificationId/read', (ctx) => {
    const id = uuidParam(ctx, 'notificationId')
    const n = ctx.db.notifications.find((row) => row.id === id && row.user_id === ctx.user.id)
    const idea = n && ctx.db.ideas.find((i) => i.id === n.idea_id)
    if (!n || !idea || !canViewIdea(ctx.db, idea, ctx.user)) notFound('Notification not found.')
    n.read_at ??= new Date().toISOString()
    return noContent()
  }),

  route('get', '/me/notification-preferences', ({ db, user }) => notificationPreferences(db, user)),

  route('patch', '/me/notification-preferences', async ({ request, db, user }) => {
    const body = await readJson(request)
    allowOnly(body, NOTIFICATION_TYPES)
    const changes: [NotificationType, NotificationMode][] = []
    for (const type of NOTIFICATION_TYPES) {
      const value = body[type]
      if (value === undefined || value === null) continue
      if (!MODES.includes(value as NotificationMode)) {
        failValidation([
          {
            loc: ['body', type],
            msg: "Input should be 'immediate', 'digest' or 'off'",
            type: 'enum',
          },
        ])
      }
      changes.push([type, value as NotificationMode])
    }
    for (const [type, mode] of changes) setPreference(db, user.id, type, mode)
    return notificationPreferences(db, user)
  }),

  publicRoute('get', '/unsubscribe', ({ url, db }) => {
    const token = tokenParam(url)
    const found = readUnsubscribeToken(db, token)
    if (!found) notFound('This link is not valid.')
    return unsubscribeInfo(db, found.user, found.scope, scopeTypes(db, found.user, found.scope))
  }),

  publicRoute('post', '/unsubscribe', ({ url, db }) => {
    const token = tokenParam(url)
    const all = queryBool(url, 'all')
    const found = readUnsubscribeToken(db, token)
    if (!found) notFound('This link is not valid.')
    const scope = all ? 'all' : found.scope
    const types = scopeTypes(db, found.user, scope)
    for (const type of types) setPreference(db, found.user.id, type, 'off')
    return unsubscribeInfo(db, found.user, scope, types)
  }),
]
