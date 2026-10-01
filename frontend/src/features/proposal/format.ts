/**
 * The section toolbar's Markdown edits (bold, italic, link, bulleted list).
 * `formatEdit` works out the replacement and the selection afterwards (pure,
 * unit-tested); `applyFormat` applies it to a textarea as typed text where the
 * browser allows (so ⌘Z undoes it), else with `setRangeText`.
 */
export type FormatKind = 'bold' | 'italic' | 'link' | 'list'

export interface FormatEdit {
  /** Replace [start, end) of the text with `insert`. */
  start: number
  end: number
  insert: string
  /** The selection afterwards. */
  selectionStart: number
  selectionEnd: number
}

const WRAP: Record<'bold' | 'italic', string> = { bold: '**', italic: '_' }

export function formatEdit(
  text: string,
  selectionStart: number,
  selectionEnd: number,
  kind: FormatKind,
): FormatEdit {
  const selected = text.slice(selectionStart, selectionEnd)
  if (kind === 'bold' || kind === 'italic') {
    const mark = WRAP[kind]
    // Already wrapped: unwrap (the toolbar toggles).
    const before = text.slice(selectionStart - mark.length, selectionStart)
    const after = text.slice(selectionEnd, selectionEnd + mark.length)
    if (before === mark && after === mark) {
      return {
        start: selectionStart - mark.length,
        end: selectionEnd + mark.length,
        insert: selected,
        selectionStart: selectionStart - mark.length,
        selectionEnd: selectionEnd - mark.length,
      }
    }
    const inner = selected || (kind === 'bold' ? 'bold text' : 'italic text')
    return {
      start: selectionStart,
      end: selectionEnd,
      insert: `${mark}${inner}${mark}`,
      selectionStart: selectionStart + mark.length,
      selectionEnd: selectionStart + mark.length + inner.length,
    }
  }
  if (kind === 'link') {
    const label = selected || 'link text'
    const insert = `[${label}](https://)`
    // Select the URL part so typing replaces it.
    const urlStart = selectionStart + label.length + 3
    return {
      start: selectionStart,
      end: selectionEnd,
      insert,
      selectionStart: selected ? urlStart : selectionStart + 1,
      selectionEnd: selected ? urlStart + 'https://'.length : selectionStart + 1 + label.length,
    }
  }
  // List: prefix every selected line (from the start of the first line) with "- ",
  // or remove the prefix when every line already has it.
  const lineStart = text.lastIndexOf('\n', selectionStart - 1) + 1
  const lineEndIndex = text.indexOf('\n', selectionEnd)
  const lineEnd = lineEndIndex === -1 ? text.length : lineEndIndex
  const lines = text.slice(lineStart, lineEnd).split('\n')
  const listed = lines.every((line) => /^\s*[-*+] /.test(line))
  const next = lines.map((line) => (listed ? line.replace(/^(\s*)[-*+] /, '$1') : `- ${line}`))
  const insert = next.join('\n')
  const delta = insert.length - (lineEnd - lineStart)
  const firstDelta = listed ? -Math.min(2, selectionStart - lineStart) : 2
  return {
    start: lineStart,
    end: lineEnd,
    insert,
    selectionStart: Math.max(lineStart, selectionStart + firstDelta),
    selectionEnd: Math.max(lineStart, selectionEnd + delta),
  }
}

/** Applies a toolbar edit to the field and returns its new value (call onChange with it). */
export function applyFormat(field: HTMLTextAreaElement, kind: FormatKind): string {
  const edit = formatEdit(field.value, field.selectionStart, field.selectionEnd, kind)
  field.focus()
  field.setSelectionRange(edit.start, edit.end)
  // `insertText` goes through the browser's undo stack; it is deprecated but has no
  // replacement for textareas. Where it isn't available, fall back to setRangeText.
  let typed = false
  try {
    /* eslint-disable @typescript-eslint/no-deprecated -- the only way to keep ⌘Z working */
    typed =
      typeof document.execCommand === 'function' &&
      document.execCommand('insertText', false, edit.insert)
    /* eslint-enable @typescript-eslint/no-deprecated */
  } catch {
    typed = false
  }
  if (!typed) field.setRangeText(edit.insert, edit.start, edit.end)
  field.setSelectionRange(edit.selectionStart, edit.selectionEnd)
  return field.value
}
