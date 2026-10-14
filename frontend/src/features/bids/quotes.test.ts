import { describe, expect, it } from 'vitest'

import { findQuote, readableText } from './quotes'

describe('finding an AI quote in a document’s text (UX review m13)', () => {
  it('finds it across line breaks and extra spaces, ignoring case', () => {
    const text = 'Boxes are packed by hand\non two   shifts; we would add a third.'
    const at = findQuote(text, 'packed by hand on two shifts')
    expect(at).not.toBeNull()
    const [start, end] = at ?? [0, 0]
    expect(text.slice(start, end)).toBe('packed by hand\non two   shifts')
    expect(findQuote(text, 'BOXES ARE')).toEqual([0, 9])
  })

  it('says when it isn’t there', () => {
    expect(findQuote('We follow Cyber Essentials.', 'ISO 27001 certified')).toBeNull()
    expect(findQuote('anything', '   ')).toBeNull()
  })
})

describe('a PDF’s text without its hard line breaks (polish p6)', () => {
  it('joins wrapped lines and keeps paragraphs, lists and headings', () => {
    const text =
      'Method statement\n' +
      'We will deliver the boxes from our warehouse in Leeds, packing by\n' +
      'hand on two shifts.\n' +
      '\n' +
      '- Week 1: set up\n' +
      '- Week 2: first run'
    expect(readableText(text, 'pdf')).toBe(
      'Method statement\n' +
        'We will deliver the boxes from our warehouse in Leeds, packing by hand on two shifts.\n' +
        '\n' +
        '- Week 1: set up\n' +
        '- Week 2: first run',
    )
  })

  it('leaves other types as they are', () => {
    expect(readableText('a,b\nc,d', 'csv')).toBe('a,b\nc,d')
  })
})
