import type { BidCallMustHave } from '@/api/types'

/*
 * Uploads' names (UX review M2, m5): a file's name is cleaned before it is sent, and the
 * document must-have it most likely answers is guessed from it, so a file links as it
 * lands ("Insurance certificate.pdf" → Insurance certificate). The guess is shown on the
 * file's row and changed there in one step; it never decides a result by itself (a person
 * still rejects).
 */

// Control characters (C0, C1), direction controls and zero-width characters.
// eslint-disable-next-line no-control-regex
const UNSAFE = /[\u0000-\u001f\u007f-\u009f\u061c\u200b-\u200f\u2028-\u202e\u2060-\u2069\ufeff]/g

/**
 * The name sent with an upload: no control, direction or zero-width characters, no folder
 * part ("..\\..\\x.pdf" → "x.pdf"), no leading dots; "document" when nothing is left.
 * The server makes its own safe name too (contract-phase10 §6.1); this one only spares
 * people a refusal for a name they can't see.
 */
export function cleanFilename(name: string): string {
  const visible = name.replace(UNSAFE, '')
  const last = visible.split(/[\\/]/).pop() ?? ''
  const trimmed = last.trim().replace(/^\.+/, '').trim()
  return trimmed || 'document'
}

/** Words that say little on their own ("Signed form of tender" is about the tender). */
const WEAK = new Set([
  'signed',
  'form',
  'copy',
  'certificate',
  'schedule',
  'statement',
  'document',
  'proof',
  'letter',
  'policy',
  'final',
  'draft',
])
const STOP = new Set([
  'the',
  'and',
  'of',
  'for',
  'our',
  'your',
  'with',
  'to',
  'a',
  'an',
  'in',
  'on',
])

function words(text: string): string[] {
  return text
    .toLowerCase()
    .split(/[^\p{L}\p{N}]+/u)
    .filter((word) => word.length >= 3 && !STOP.has(word) && !/^\d+$/.test(word))
}

function similar(a: string, b: string): boolean {
  if (a === b) return true
  const shorter = Math.min(a.length, b.length)
  if (shorter < 4) return false
  let common = 0
  while (common < shorter && a[common] === b[common]) common += 1
  return common >= 4 && common >= shorter - 2
}

/**
 * The document must-have a file name points to: its words against each must-have's
 * (strong words count 2, weak ones 1; at least 2 to count), the best unique score winning,
 * ties going to a must-have still missing. Null when nothing fits or two fit as well.
 */
export function guessMustHave<T extends Pick<BidCallMustHave, 'id' | 'text' | 'kind'>>(
  filename: string,
  mustHaves: readonly T[],
  missing: ReadonlySet<string> = new Set(),
): T | null {
  const name = words(filename.replace(/\.[a-z0-9]{2,5}$/i, ''))
  if (name.length === 0) return null
  const scored = mustHaves
    .filter((m) => m.kind === 'document')
    .map((m) => ({
      must: m,
      score: words(m.text).reduce(
        (sum, word) => sum + (name.some((n) => similar(n, word)) ? (WEAK.has(word) ? 1 : 2) : 0),
        0,
      ),
      missing: missing.has(m.id),
    }))
    .filter((s) => s.score >= 2)
    .sort((a, b) => b.score - a.score || Number(b.missing) - Number(a.missing))
  const [best, next] = scored
  if (!best) return null
  if (next?.score === best.score && next.missing === best.missing) return null
  return best.must
}
