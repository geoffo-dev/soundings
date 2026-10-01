import type { ProposalSectionKey } from '@/api/types'

/**
 * The fixed template's keys and titles (SPEC section 2), for the outline and
 * headings while the proposal loads. The API sends the same titles (and the
 * prompts) with every section.
 */
export const PROPOSAL_SECTIONS: readonly { key: ProposalSectionKey; title: string }[] = [
  { key: 'summary', title: 'Summary' },
  { key: 'problem', title: 'Problem' },
  { key: 'solution', title: 'Solution' },
  { key: 'market', title: 'Market & users' },
  { key: 'cost', title: 'Cost & effort' },
  { key: 'benefits', title: 'Benefits / revenue' },
  { key: 'risks', title: 'Risks' },
  { key: 'next_steps', title: 'Next steps / the ask' },
]

/** Characters per section (`SECTION_MAX_LENGTH`). */
export const SECTION_LIMIT = 20_000
/** Characters per margin comment (`COMMENT_MAX_LENGTH`). */
export const PROPOSAL_COMMENT_LIMIT = 5_000

/** The DOM id of a section (outline links and "jump to" move focus here). */
export function sectionDomId(key: ProposalSectionKey): string {
  return `proposal-section-${key}`
}

/** Words in Markdown text: runs of letters or digits, ignoring Markdown punctuation and URLs. */
export function countWords(text: string): number {
  const prose = text.replace(/\]\([^)\s]*\)/g, ']').replace(/\b(?:https?|mailto):\S+/gi, ' ')
  return prose.match(/[\p{L}\p{N}]+(?:['’-][\p{L}\p{N}]+)*/gu)?.length ?? 0
}

/** "1 word", "1,204 words". */
export function wordLabel(count: number): string {
  return `${count.toLocaleString()} word${count === 1 ? '' : 's'}`
}

/** Whether a section counts as written (the outline's tick). */
export function hasContent(text: string): boolean {
  return text.trim().length > 0
}

export interface DiffLine {
  kind: 'same' | 'theirs' | 'yours'
  text: string
}

/**
 * A line diff (longest common subsequence) between their version and yours,
 * for the conflict prompt: lines only in theirs, only in yours, or in both.
 * Sections are short (≤ 20,000 characters), so O(n·m) is fine; past 4,000,000
 * cells it falls back to "everything changed".
 */
export function diffLines(theirs: string, yours: string): DiffLine[] {
  const a = theirs.split('\n')
  const b = yours.split('\n')
  if (a.length * b.length > 4_000_000) {
    return [
      ...a.map((text) => ({ kind: 'theirs' as const, text })),
      ...b.map((text) => ({ kind: 'yours' as const, text })),
    ]
  }
  const width = b.length + 1
  const lcs = new Uint32Array((a.length + 1) * width)
  for (let i = a.length - 1; i >= 0; i--) {
    for (let j = b.length - 1; j >= 0; j--) {
      lcs[i * width + j] =
        a[i] === b[j]
          ? (lcs[(i + 1) * width + j + 1] ?? 0) + 1
          : Math.max(lcs[(i + 1) * width + j] ?? 0, lcs[i * width + j + 1] ?? 0)
    }
  }
  const out: DiffLine[] = []
  let i = 0
  let j = 0
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      out.push({ kind: 'same', text: a[i] ?? '' })
      i++
      j++
    } else if ((lcs[(i + 1) * width + j] ?? 0) >= (lcs[i * width + j + 1] ?? 0)) {
      out.push({ kind: 'theirs', text: a[i] ?? '' })
      i++
    } else {
      out.push({ kind: 'yours', text: b[j] ?? '' })
      j++
    }
  }
  while (i < a.length) out.push({ kind: 'theirs', text: a[i++] ?? '' })
  while (j < b.length) out.push({ kind: 'yours', text: b[j++] ?? '' })
  return out
}
