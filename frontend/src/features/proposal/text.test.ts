import { describe, expect, it } from 'vitest'

import { countWords, diffLines, hasContent, wordLabel } from './text'

describe('countWords', () => {
  it('counts words, not Markdown punctuation', () => {
    expect(countWords('')).toBe(0)
    expect(countWords('**Bold** _italic_ and [a link](https://example.com)')).toBe(5)
    expect(countWords('see https://example.com/a-b now')).toBe(2)
    expect(countWords('- one\n- two\n\n## Three')).toBe(3)
    expect(countWords("don't re-order 10% ok")).toBe(4)
    expect(countWords('Größe café naïve')).toBe(3)
  })

  it('labels the count', () => {
    expect(wordLabel(1)).toBe('1 word')
    expect(wordLabel(0)).toBe('0 words')
    expect(wordLabel(1204)).toMatch(/^1.204 words$/)
  })

  it('treats whitespace-only text as empty', () => {
    expect(hasContent('  \n\t')).toBe(false)
    expect(hasContent('    indented code')).toBe(true)
  })
})

describe('diffLines', () => {
  it('keeps common lines and marks each side’s own lines', () => {
    expect(diffLines('a\nb\nc', 'a\nB\nc\nd')).toEqual([
      { kind: 'same', text: 'a' },
      { kind: 'theirs', text: 'b' },
      { kind: 'yours', text: 'B' },
      { kind: 'same', text: 'c' },
      { kind: 'yours', text: 'd' },
    ])
  })

  it('handles empty sides', () => {
    expect(diffLines('', 'new')).toEqual([
      { kind: 'theirs', text: '' },
      { kind: 'yours', text: 'new' },
    ])
    expect(diffLines('same', 'same')).toEqual([{ kind: 'same', text: 'same' }])
  })
})
