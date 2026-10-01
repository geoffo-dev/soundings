/**
 * @mentions in comments (contract-phase3 §3.8): the token
 * `@[Display Name](user:<uuid>)`, inserted by the mention picker. The server
 * rewrites labels to the person's current name and notifies the people it
 * names; anything else (`@ada`) is plain text. The SPA renders tokens as name
 * chips (never as `user:` links) and shows them as `@Name` in plain text.
 *
 * Mirrors `app.schemas.comments` (MENTION_PATTERN, MAX_MENTIONS, mention_token).
 */

const UUID_SOURCE = '[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}'

/** One mention token; global, so use it with `matchAll` / `replace`. */
export const MENTION_PATTERN = new RegExp(
  String.raw`@\[([^\[\]\r\n]{1,100})\]\(user:(${UUID_SOURCE})\)`,
  'g',
)

/** Distinct people one comment may mention (more: 422 `too_many_mentions`). */
export const MAX_MENTIONS = 20

/** A `user:` link target as react-markdown sees it (the `@` is the text before it). */
export const MENTION_HREF = new RegExp(`^user:(${UUID_SOURCE})$`)

export interface Mention {
  /** Index of the "@". */
  start: number
  /** Index after the closing ")". */
  end: number
  label: string
  userId: string
}

/** Every mention token in `text`, in order. */
export function parseMentions(text: string): Mention[] {
  return [...text.matchAll(MENTION_PATTERN)].map((match) => ({
    start: match.index,
    end: match.index + match[0].length,
    label: match[1] ?? '',
    userId: (match[2] ?? '').toLowerCase(),
  }))
}

/** The distinct users `text` mentions, in order of first appearance (lower-case ids). */
export function mentionedUserIds(text: string): string[] {
  return [...new Set(parseMentions(text).map((mention) => mention.userId))]
}

/** A display name as a token label: brackets and line breaks removed, spaces collapsed, ≤ 100. */
export function mentionLabel(displayName: string): string {
  const label = displayName
    .replace(/[[\]\r\n]+/g, ' ')
    .split(/\s+/)
    .filter(Boolean)
    .join(' ')
    .slice(0, 100)
    .trim()
  return label || 'user'
}

export function mentionToken(userId: string, displayName: string): string {
  return `@[${mentionLabel(displayName)}](user:${userId})`
}

/** Tokens shown as plain `@Name` (excerpts, previews, accessible text). */
export function mentionsToText(text: string): string {
  return text.replace(MENTION_PATTERN, (_token, label: string) => `@${label}`)
}

/** Longest query the picker follows after "@" (names have spaces, so it allows some). */
const MAX_QUERY = 40
/** Characters a mention may follow: start of text, whitespace or opening punctuation. */
const BEFORE_MENTION = /[\s([{"'“‘]/

export interface MentionQuery {
  /** Index of the "@". */
  start: number
  /** What was typed after "@" up to the caret. */
  query: string
}

/**
 * The mention being typed at `caret`, if any: an "@" at the start of the text
 * or after a space or opening bracket, followed by up to 40 characters on the
 * same line with no "@" or brackets (so a finished token or an email address
 * never re-opens the picker), and no double space.
 */
export function activeMentionQuery(text: string, caret: number): MentionQuery | null {
  const before = text.slice(0, caret)
  const at = before.lastIndexOf('@')
  if (at < 0) return null
  const query = before.slice(at + 1)
  if (query.length > MAX_QUERY) return null
  if (/[@[\]()\r\n]/.test(query) || /\s{2}/.test(query) || /^\s/.test(query)) return null
  const previous = at === 0 ? '' : (before[at - 1] ?? '')
  if (previous && !BEFORE_MENTION.test(previous)) return null
  return { start: at, query }
}

/**
 * Replaces the typed "@query" (from `start` to `caret`) with the person's
 * token and a space; returns the new text and where the caret goes.
 */
export function insertMention(
  text: string,
  { start, caret }: { start: number; caret: number },
  person: { id: string; display_name: string },
): { text: string; caret: number } {
  const token = mentionToken(person.id, person.display_name)
  const after = text.slice(caret)
  const spacer = /^\s/.test(after) ? '' : ' '
  const next = `${text.slice(0, start)}${token}${spacer}${after}`
  return { text: next, caret: start + token.length + spacer.length }
}
