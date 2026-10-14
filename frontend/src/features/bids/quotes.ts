/**
 * Where an AI quote sits in a document's text (UX review m13): runs of whitespace count
 * as one space and case is ignored, as the server checks quotes. Returns the quote's
 * start and end in `text` (to mark it), or null.
 */
export function findQuote(text: string, quote: string): [number, number] | null {
  const wanted = fold(quote.trim().replace(/\s+/g, ' '))
  if (!wanted) return null
  let folded = ''
  const at: number[] = []
  let space = false
  for (let i = 0; i < text.length; i++) {
    const ch = text.charAt(i)
    if (/\s/.test(ch)) {
      if (!space && folded.length > 0) {
        folded += ' '
        at.push(i)
      }
      space = true
    } else {
      folded += fold(ch)
      at.push(i)
      space = false
    }
  }
  const start = folded.indexOf(wanted)
  if (start < 0) return null
  const first = at[start]
  const last = at[start + wanted.length - 1]
  if (first === undefined || last === undefined) return null
  return [first, last + 1]
}

/** Lower case, one character for one (a few letters lower-case to two: kept as they are). */
function fold(text: string): string {
  let out = ''
  for (const ch of text) {
    const lower = ch.toLowerCase()
    out += lower.length === ch.length ? lower : ch
  }
  return out
}

const BULLET = /^\s*([•‣◦▪\-*–]|\d{1,3}[.)]|[a-z][.)])\s/

/**
 * A PDF's text with its hard line breaks inside paragraphs joined (polish p6): PDFs keep
 * the page's line ends, which read as a ragged column. A line joins the next when it is
 * long and doesn't end a sentence, or the next one starts in lower case; blank lines,
 * list items and short lines (headings) stay as they are. Other types are left alone.
 */
export function readableText(text: string, type: string): string {
  if (type !== 'pdf') return text
  return text
    .split(/\n[ \t]*\n/)
    .map((paragraph) => {
      const lines = paragraph.split('\n')
      let out = lines[0] ?? ''
      for (let i = 1; i < lines.length; i++) {
        const previous = lines[i - 1]?.trimEnd() ?? ''
        const line = lines[i] ?? ''
        const join =
          !BULLET.test(line) &&
          previous.length > 0 &&
          (/^\s*\p{Ll}/u.test(line) || (previous.length >= 40 && !/[.:;!?)]$/.test(previous)))
        out += join ? ` ${line.trimStart()}` : `\n${line}`
      }
      return out
    })
    .join('\n\n')
}
