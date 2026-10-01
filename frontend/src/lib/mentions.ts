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

const EXACT_MENTION = new RegExp(`^${MENTION_PATTERN.source}$`)

/** `text` as one whole mention token (the server's spelling exactly), or null. */
export function exactMention(text: string): { label: string; userId: string } | null {
  const match = EXACT_MENTION.exec(text)
  return match ? { label: match[1] ?? '', userId: (match[2] ?? '').toLowerCase() } : null
}

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

/* ------------------------------------------------------------------ */
/* The composer: "@Name" on screen, tokens underneath                  */
/* ------------------------------------------------------------------ */

/** A mention as the composer shows it: "@Label" at `[start, end)` of the shown text. */
export interface ShownMention {
  start: number
  end: number
  label: string
  userId: string
}

/**
 * What the comment box shows: tokens as "@Label" (nobody sees or breaks a
 * UUID), plus where each mention is, so the stored text can be rebuilt.
 */
export interface MentionDraft {
  text: string
  mentions: ShownMention[]
}

/** The stored text (with tokens) as the comment box shows it. */
export function toShown(stored: string): MentionDraft {
  let text = ''
  let from = 0
  const mentions: ShownMention[] = []
  for (const mention of parseMentions(stored)) {
    text += stored.slice(from, mention.start)
    const shown = `@${mention.label}`
    mentions.push({
      start: text.length,
      end: text.length + shown.length,
      label: mention.label,
      userId: mention.userId,
    })
    text += shown
    from = mention.end
  }
  return { text: text + stored.slice(from), mentions }
}

/** Back to the stored text: each mention as its token, everything else as typed. */
export function toStored({ text, mentions }: MentionDraft): string {
  let out = ''
  let from = 0
  for (const mention of mentions) {
    if (mention.start < from || text.slice(mention.start, mention.end) !== `@${mention.label}`) {
      continue // Defensive: a mention that no longer matches its text stays plain text.
    }
    out += `${text.slice(from, mention.start)}@[${mention.label}](user:${mention.userId})`
    from = mention.end
  }
  return out + text.slice(from)
}

function commonPrefix(a: string, b: string): number {
  const max = Math.min(a.length, b.length)
  let i = 0
  while (i < max && a.charCodeAt(i) === b.charCodeAt(i)) i += 1
  return i
}

function commonSuffix(a: string, b: string): number {
  const max = Math.min(a.length, b.length)
  let i = 0
  while (i < max && a.charCodeAt(a.length - 1 - i) === b.charCodeAt(b.length - 1 - i)) i += 1
  return i
}

/**
 * After the shown text changed to `next` (typing, deleting, pasting; `caret`
 * is where the caret is now): mentions the edit didn't touch keep their place
 * (shifted), and one it changed becomes plain text, so typing inside
 * "@Ada Lovelace" never keeps a mention that no longer says who it is.
 */
export function applyShownEdit(draft: MentionDraft, next: string, caret: number): MentionDraft {
  const previous = draft.text
  if (next === previous) return draft
  // Everything after the caret is what was there before the edit (when that holds;
  // otherwise, the longest common ending).
  const afterCaret = caret >= 0 && caret <= next.length ? next.slice(caret) : null
  const tail =
    afterCaret !== null && previous.endsWith(afterCaret)
      ? afterCaret.length
      : commonSuffix(previous, next)
  const editEnd = previous.length - tail
  const editStart = Math.min(commonPrefix(previous, next), editEnd, next.length - tail)
  const shift = next.length - previous.length
  const mentions: ShownMention[] = []
  for (const mention of draft.mentions) {
    if (mention.end <= editStart) mentions.push(mention)
    else if (mention.start >= editEnd) {
      mentions.push({ ...mention, start: mention.start + shift, end: mention.end + shift })
    }
  }
  return { text: next, mentions }
}

/** The mention whose "@Label" ends at (`side: 'end'`) or starts at `index`, if any. */
export function mentionAt(
  draft: MentionDraft,
  index: number,
  side: 'start' | 'end',
): ShownMention | undefined {
  return draft.mentions.find((mention) => mention[side] === index)
}

/** Removes one mention entirely (Backspace right after it, Delete right before it). */
export function removeMention(
  draft: MentionDraft,
  mention: ShownMention,
): { draft: MentionDraft; caret: number } {
  const length = mention.end - mention.start
  return {
    draft: {
      text: draft.text.slice(0, mention.start) + draft.text.slice(mention.end),
      mentions: draft.mentions
        .filter((other) => other !== mention)
        .map((other) =>
          other.start >= mention.end
            ? { ...other, start: other.start - length, end: other.end - length }
            : other,
        ),
    },
    caret: mention.start,
  }
}

/**
 * The mention being typed in the comment box: like `activeMentionQuery`, but
 * never an existing mention's own "@" (the caret right after "@Ada Lovelace").
 */
export function activeShownQuery(draft: MentionDraft, caret: number): MentionQuery | null {
  const query = activeMentionQuery(draft.text, caret)
  if (!query) return null
  const inMention = draft.mentions.some(
    (mention) => query.start >= mention.start && query.start < mention.end,
  )
  return inMention ? null : query
}

/**
 * Replaces the typed "@query" (from `start` to `caret`) with "@Name" and a
 * space; returns the new draft and where the caret goes.
 */
export function insertMention(
  draft: MentionDraft,
  { start, caret }: { start: number; caret: number },
  person: { id: string; display_name: string },
): { draft: MentionDraft; caret: number } {
  const label = mentionLabel(person.display_name)
  const shown = `@${label}`
  const after = draft.text.slice(caret)
  const spacer = /^\s/.test(after) ? '' : ' '
  const text = `${draft.text.slice(0, start)}${shown}${spacer}${after}`
  const shift = shown.length + spacer.length - (caret - start)
  const mentions: ShownMention[] = []
  for (const mention of draft.mentions) {
    if (mention.end <= start) mentions.push(mention)
    else if (mention.start >= caret) {
      mentions.push({ ...mention, start: mention.start + shift, end: mention.end + shift })
    }
  }
  mentions.push({ start, end: start + shown.length, label, userId: person.id.toLowerCase() })
  mentions.sort((a, b) => a.start - b.start)
  return { draft: { text, mentions }, caret: start + shown.length + spacer.length }
}
