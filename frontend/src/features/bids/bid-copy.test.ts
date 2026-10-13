import { describe, expect, it } from 'vitest'

import {
  extractionText,
  formatPoints,
  formatPrice,
  formatSize,
  mustHaveSummary,
  progressText,
  uploadProblem,
} from './bid-copy'
import { normalisePrice } from './bid-form-dialog'

describe('bid words', () => {
  it('summarises must-haves, flagging missing and not met ones', () => {
    expect(mustHaveSummary({ met: 0, not_met: 0, missing: 0, unchecked: 0 })).toEqual({
      text: 'No must-haves',
      flagged: false,
    })
    expect(mustHaveSummary({ met: 4, not_met: 0, missing: 0, unchecked: 0 })).toEqual({
      text: 'All 4 met',
      flagged: false,
    })
    expect(mustHaveSummary({ met: 2, not_met: 0, missing: 1, unchecked: 1 })).toEqual({
      text: '1 missing · 1 to check',
      flagged: true,
    })
    expect(mustHaveSummary({ met: 3, not_met: 0, missing: 0, unchecked: 1 }).flagged).toBe(false)
  })

  it('words the extraction state, by type', () => {
    const base = { error: null, chars: null, truncated: false, page_count: 0 }
    expect(extractionText({ ...base, state: 'pending' }, 'pdf')).toBe('Reading the text…')
    expect(extractionText({ ...base, state: 'done', chars: 12_345, page_count: 1 }, 'pdf')).toBe(
      '12,345 characters of text',
    )
    expect(extractionText({ ...base, state: 'no_text' }, 'png')).toBe('An image: no text to read')
    expect(extractionText({ ...base, state: 'failed', error: 'encrypted' }, 'pdf')).toBe(
      'Couldn’t read the text: the file is password-protected',
    )
  })

  it('formats sizes, prices, points and progress', () => {
    expect(formatSize(900)).toBe('900 B')
    expect(formatSize(48 * 1024)).toBe('48 KB')
    expect(formatSize(2.5 * 1024 * 1024)).toBe('2.5 MB')
    expect(formatPrice('120000.00', 'GBP')).toBe('£120,000.00')
    expect(formatPrice(null, 'GBP')).toBe('—')
    expect(formatPoints(87.25)).toBe('87.3')
    expect(formatPoints(null)).toBe('—')
    expect(progressText({ submitted: 8, total: 10 })).toBe('8 of 10 assessed')
    expect(progressText({ submitted: 0, total: 0 })).toBe('No assessors yet')
  })

  it('refuses empty and oversized files before sending them', () => {
    const max = 25 * 1024 * 1024
    expect(uploadProblem(new File([], 'empty.txt'), max)).toBe('empty.txt is empty.')
    const big = { name: 'big.pdf', size: max + 1 } as File
    expect(uploadProblem(big, max)).toBe('big.pdf is 25.0 MB: files can be at most 25 MB.')
    expect(uploadProblem(new File(['x'], 'ok.txt'), max)).toBeNull()
  })

  it('reads a typed price', () => {
    expect(normalisePrice('120,000')).toBe('120000.00')
    expect(normalisePrice('£96000.5')).toBe('96000.50')
    expect(normalisePrice('0')).toBeNull()
    expect(normalisePrice('12.345')).toBeNull()
    expect(normalisePrice('abc')).toBeNull()
  })
})
