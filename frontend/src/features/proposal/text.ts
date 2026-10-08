import type { ProposalSectionKey } from '@/api/types'

/** Characters per section (`SECTION_MAX_LENGTH`). */
export const SECTION_LIMIT = 20_000
/** Characters per margin comment (`COMMENT_MAX_LENGTH`). */
export const PROPOSAL_COMMENT_LIMIT = 5_000

/** The editor bar's "Markdown · saves as you type" (every section's text points to it). */
export const MARKDOWN_HINT_ID = 'proposal-markdown-hint'

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

/**
 * One line of plain text from Markdown, for excerpts (a resolved thread's
 * line): links and images become their text, and emphasis, code, heading,
 * quote and list markers go, so `**2.4 million**` reads "2.4 million".
 */
export function markdownExcerpt(markdown: string): string {
  return markdown
    .replace(/!?\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/^\s{0,3}(?:#{1,6}\s+|>\s?|[-*+]\s+(?:\[[ xX]\]\s+)?|\d+[.)]\s+)/gm, '')
    .replace(/(`{1,3}|\*{1,3}|_{1,3}|~~)(\S(?:.*?\S)?)\1/g, '$2')
    .replace(/`+/g, '')
    .replace(/\s+/g, ' ')
    .trim()
}

/** A run of a changed line: `changed` words are the ones the other side doesn't have. */
export interface DiffPart {
  text: string
  changed: boolean
}

export type SuggestionLine =
  | {
      kind: 'same' | 'removed' | 'added'
      text: string
      /**
       * A removed line and the added line that replaces it, word by word: what
       * stayed and what changed (only when they share words; otherwise the whole
       * line is the change).
       */
      parts?: DiffPart[]
    }
  /** Unchanged lines left out between changes. */
  | { kind: 'skip'; count: number }

/** Past this many token pairs a line pair is shown changed as a whole (lines are short). */
const WORD_DIFF_CELLS = 250_000

/**
 * Words (and the spaces between them) of a removed line and the added line
 * that replaces it, each marked changed when the other line doesn't have it at
 * that place (longest common subsequence of tokens). Undefined when the lines
 * share no word: the whole line changed.
 */
export function wordDiff(
  removed: string,
  added: string,
): { removed: DiffPart[]; added: DiffPart[] } | undefined {
  const a = removed.split(/(\s+)/).filter(Boolean)
  const b = added.split(/(\s+)/).filter(Boolean)
  if (a.length === 0 || b.length === 0 || a.length * b.length > WORD_DIFF_CELLS) return undefined
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
  const keptA = new Array<boolean>(a.length).fill(false)
  const keptB = new Array<boolean>(b.length).fill(false)
  let i = 0
  let j = 0
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      keptA[i++] = true
      keptB[j++] = true
    } else if ((lcs[(i + 1) * width + j] ?? 0) >= (lcs[i * width + j + 1] ?? 0)) i++
    else j++
  }
  // Only spaces in common: nothing worth pointing at word by word.
  if (!a.some((token, index) => keptA[index] && token.trim() !== '')) return undefined
  const parts = (tokens: string[], kept: boolean[]): DiffPart[] => {
    const out: DiffPart[] = []
    tokens.forEach((text, index) => {
      // A space between two changed words belongs to the change (one highlight, not two).
      const changed =
        !kept[index] || (text.trim() === '' && !kept[index - 1] && !kept[index + 1] && index > 0)
      const last = out.at(-1)
      if (last?.changed === changed) last.text += text
      else out.push({ text, changed })
    })
    return out
  }
  return { removed: parts(a, keptA), added: parts(b, keptB) }
}

/**
 * In each run of changed lines, the n-th removed line pairs with the n-th
 * added line (an edited paragraph), and both get their word-level `parts`.
 */
function pairWords(lines: Extract<SuggestionLine, { text: string }>[]): void {
  let index = 0
  while (index < lines.length) {
    if (lines[index]?.kind === 'same') {
      index++
      continue
    }
    const removed: number[] = []
    const added: number[] = []
    while (index < lines.length && lines[index]?.kind !== 'same') {
      if (lines[index]?.kind === 'removed') removed.push(index)
      else added.push(index)
      index++
    }
    for (let n = 0; n < Math.min(removed.length, added.length); n++) {
      const before = lines[removed[n] ?? -1]
      const after = lines[added[n] ?? -1]
      if (!before || !after || !before.text.trim() || !after.text.trim()) continue
      const words = wordDiff(before.text, after.text)
      if (!words) continue
      before.parts = words.removed
      after.parts = words.added
    }
  }
}

/**
 * A suggestion against the section's text as a unified diff (contract-phase5
 * §3.4 "a preview of the proposed text against the current text"): removed
 * and added lines with `context` unchanged lines around each change; longer
 * unchanged runs become one `skip`. Nothing changed: an empty list.
 */
export function suggestionDiff(current: string, suggested: string, context = 2): SuggestionLine[] {
  // An empty section: every suggested line is new (no phantom removed blank line).
  if (current === '') return suggested.split('\n').map((text) => ({ kind: 'added' as const, text }))
  const lines: Extract<SuggestionLine, { text: string }>[] = diffLines(current, suggested).map(
    (line) => ({
      kind:
        line.kind === 'theirs'
          ? ('removed' as const)
          : line.kind === 'yours'
            ? ('added' as const)
            : ('same' as const),
      text: line.text,
    }),
  )
  if (!lines.some((line) => line.kind !== 'same')) return []
  pairWords(lines)
  const keep = lines.map((line) => line.kind !== 'same')
  lines.forEach((line, index) => {
    if (line.kind === 'same') return
    for (
      let i = Math.max(0, index - context);
      i <= Math.min(lines.length - 1, index + context);
      i++
    ) {
      keep[i] = true
    }
  })
  const out: SuggestionLine[] = []
  let skipped = 0
  lines.forEach((line, index) => {
    if (keep[index]) {
      if (skipped) out.push({ kind: 'skip', count: skipped })
      skipped = 0
      out.push(line)
    } else skipped++
  })
  if (skipped) out.push({ kind: 'skip', count: skipped })
  return out
}
