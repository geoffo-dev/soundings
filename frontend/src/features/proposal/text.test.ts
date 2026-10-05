import { describe, expect, it } from 'vitest'

import {
  countWords,
  diffLines,
  hasContent,
  markdownExcerpt,
  suggestionDiff,
  wordLabel,
} from './text'

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

describe('markdownExcerpt', () => {
  it('reads as plain text', () => {
    expect(markdownExcerpt('Is **2.4 million** right?')).toBe('Is 2.4 million right?')
    expect(
      markdownExcerpt('See [the report](https://example.org) and ![chart](https://x/y.png)'),
    ).toBe('See the report and chart')
    expect(markdownExcerpt('## Heading\n\n> quoted _text_\n- one\n- two\n1. three')).toBe(
      'Heading quoted text one two three',
    )
    expect(markdownExcerpt('Use `code` and ~~old~~ new')).toBe('Use code and old new')
    expect(markdownExcerpt('Ask @[Ada Lovelace](user:5f0c) about it')).toBe(
      'Ask @Ada Lovelace about it',
    )
    expect(markdownExcerpt('2 * 3 * 4')).toBe('2 * 3 * 4')
  })
})

describe('suggestionDiff', () => {
  it('marks removed and added lines with a little context', () => {
    const current = ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'].join('\n')
    const suggested = ['a', 'b', 'c', 'd', 'E', 'f', 'g', 'h'].join('\n')
    expect(suggestionDiff(current, suggested, 1)).toEqual([
      { kind: 'skip', count: 3 },
      { kind: 'same', text: 'd' },
      { kind: 'removed', text: 'e' },
      { kind: 'added', text: 'E' },
      { kind: 'same', text: 'f' },
      { kind: 'skip', count: 2 },
    ])
  })

  it('shows an empty section’s suggestion as additions only, and nothing when equal', () => {
    expect(suggestionDiff('', 'New text\n\nMore')).toEqual([
      { kind: 'added', text: 'New text' },
      { kind: 'added', text: '' },
      { kind: 'added', text: 'More' },
    ])
    expect(suggestionDiff('Same', 'Same')).toEqual([])
  })
})
