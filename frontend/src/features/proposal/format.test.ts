import { describe, expect, it } from 'vitest'

import { applyFormat, formatEdit } from './format'

function apply(text: string, start: number, end: number, kind: Parameters<typeof formatEdit>[3]) {
  const edit = formatEdit(text, start, end, kind)
  const next = text.slice(0, edit.start) + edit.insert + text.slice(edit.end)
  return { text: next, selected: next.slice(edit.selectionStart, edit.selectionEnd) }
}

describe('formatEdit', () => {
  it('wraps the selection in bold and italic, and unwraps it again', () => {
    expect(apply('make this bold', 5, 9, 'bold')).toEqual({
      text: 'make **this** bold',
      selected: 'this',
    })
    expect(apply('make **this** bold', 7, 11, 'bold')).toEqual({
      text: 'make this bold',
      selected: 'this',
    })
    expect(apply('a word', 2, 6, 'italic')).toEqual({ text: 'a _word_', selected: 'word' })
  })

  it('inserts placeholder text when nothing is selected', () => {
    expect(apply('', 0, 0, 'bold')).toEqual({ text: '**bold text**', selected: 'bold text' })
  })

  it('turns the selection into a link and selects the URL to type over', () => {
    expect(apply('see docs', 4, 8, 'link')).toEqual({
      text: 'see [docs](https://)',
      selected: 'https://',
    })
    expect(apply('', 0, 0, 'link')).toEqual({
      text: '[link text](https://)',
      selected: 'link text',
    })
  })

  it('bullets every selected line, and removes the bullets when all have them', () => {
    expect(apply('one\ntwo\nthree', 0, 7, 'list').text).toBe('- one\n- two\nthree')
    expect(apply('- one\n- two', 2, 11, 'list').text).toBe('one\ntwo')
    // From the middle of a line: the whole line.
    expect(apply('intro\nitem', 8, 8, 'list').text).toBe('intro\n- item')
  })
})

describe('applyFormat', () => {
  it('edits the field (setRangeText where insertText is unavailable) and returns the value', () => {
    const field = document.createElement('textarea')
    document.body.append(field)
    field.value = 'make this bold'
    field.setSelectionRange(5, 9)
    expect(applyFormat(field, 'bold')).toBe('make **this** bold')
    expect(field.value.slice(field.selectionStart, field.selectionEnd)).toBe('this')
    field.remove()
  })
})
