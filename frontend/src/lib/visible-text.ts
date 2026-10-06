/**
 * Agent text without invisible characters (code review M2, the rendering side of
 * backend `app/mcp/text.py`). An agent's Markdown is untrusted: a right-to-left
 * override, a bidi isolate or a zero-width character can make a link's host read as
 * another site's ("(elpmaxe.live.google.com)"), or hide words. The same set as the
 * backend's `HIDDEN`: controls but tab and line breaks, format characters but ZWNJ and
 * ZWJ (scripts and emoji need them), variation selectors but VS15/VS16, the tag block.
 */
// Each listed character is removed on its own, combining ones (U+034F, the variation
// selectors) included: that is the point, not a misread grapheme.
const HIDDEN = new RegExp(
  // eslint-disable-next-line no-misleading-character-class -- see above
  '[' +
    '\\u0000-\\u0008\\u000B\\u000C\\u000E-\\u001F\\u007F-\\u009F' + // controls but tab, LF, CR
    '\\u00AD' + // soft hyphen
    '\\u034F' + // combining grapheme joiner
    '\\u0600-\\u0605\\u061C\\u06DD\\u070F\\u0890\\u0891\\u08E2' + // Arabic, Syriac format marks
    '\\u115F\\u1160\\u3164\\uFFA0' + // Hangul fillers
    '\\u180E' + // Mongolian vowel separator
    '\\u200B\\u200E\\u200F' + // zero-width space, LRM, RLM
    '\\u202A-\\u202E' + // bidi embeddings and overrides
    '\\u2060-\\u2064\\u2066-\\u206F' + // word joiner, invisible operators, bidi isolates…
    '\\uFE00-\\uFE0D' + // variation selectors 1–14
    '\\uFEFF' + // zero-width no-break space
    '\\uFFF9-\\uFFFB' + // interlinear annotation
    '\\u{110BD}\\u{110CD}' + // Kaithi number signs
    '\\u{13430}-\\u{1343F}' + // Egyptian hieroglyph format controls
    '\\u{1BCA0}-\\u{1BCA3}' + // shorthand format controls
    '\\u{1D173}-\\u{1D17A}' + // musical symbol format controls
    '\\u{E0000}-\\u{E007F}' + // the tag block
    '\\u{E0100}-\\u{E01EF}' + // variation selectors 17–256
    '\\uD800-\\uDFFF' + // lone surrogates (a pair is one code point here)
    ']+',
  'gu',
)

/** `text` without the characters that show nothing (or reorder what is around them). */
export function visibleText(text: string): string {
  return text.replace(HIDDEN, '')
}
