import { describe, expect, it } from 'vitest'

import { cleanFilename, guessMustHave } from './upload-names'

const MUST_HAVES = [
  { id: 'tender', text: 'Signed form of tender', kind: 'document' as const },
  { id: 'insurance', text: 'Insurance certificate', kind: 'document' as const },
  { id: 'pricing', text: 'Pricing schedule', kind: 'document' as const },
  { id: 'terms', text: 'Accepts our standard terms', kind: 'confirmation' as const },
]

const guess = (name: string, missing: string[] = []) =>
  guessMustHave(name, MUST_HAVES, new Set(missing))?.id ?? null

describe('guessing the must-have a file answers (UX review M2)', () => {
  it('links files named after a document must-have', () => {
    expect(guess('Form of tender.pdf')).toBe('tender')
    expect(guess('northwind-form-of-tender.pdf')).toBe('tender')
    expect(guess('Tender_SIGNED.pdf')).toBe('tender')
    expect(guess('Insurance certificate.pdf')).toBe('insurance')
    expect(guess('insurance.pdf')).toBe('insurance')
    expect(guess('2026 pricing.xlsx')).toBe('pricing')
    expect(guess('price-breakdown.xlsx')).toBe('pricing')
  })

  it('leaves files that answer no must-have, or answer two as well, alone', () => {
    expect(guess('Technical proposal.docx')).toBeNull()
    expect(guess('certificate.pdf')).toBeNull()
    expect(guess('schedule.pdf')).toBeNull()
    expect(guess('signed.pdf')).toBeNull()
    expect(guess('.pdf')).toBeNull()
    // Confirmations take no file.
    expect(guess('standard terms.pdf')).toBeNull()
  })

  it('breaks a tie towards a must-have that is still missing', () => {
    const two = [
      { id: 'a', text: 'Insurance certificate', kind: 'document' as const },
      { id: 'b', text: 'Insurance schedule', kind: 'document' as const },
    ]
    expect(guessMustHave('insurance.pdf', two)).toBeNull()
    expect(guessMustHave('insurance.pdf', two, new Set(['b']))?.id).toBe('b')
  })
})

describe('cleaning a file name before it is sent (UX review m5)', () => {
  it('drops folders, control, direction and zero-width characters and leading dots', () => {
    expect(cleanFilename('..\\..\\evil.pdf')).toBe('evil.pdf')
    expect(cleanFilename('a/b/c.docx')).toBe('c.docx')
    expect(cleanFilename(`invoice${String.fromCharCode(7)}.pdf`)).toBe('invoice.pdf')
    expect(cleanFilename(`report${String.fromCharCode(0x202e)}fdp.exe`)).toBe('reportfdp.exe')
    expect(cleanFilename(`zero${String.fromCharCode(0x200b)}width.txt`)).toBe('zerowidth.txt')
    expect(cleanFilename('...hidden.txt')).toBe('hidden.txt')
    expect(cleanFilename('Form of tender.pdf')).toBe('Form of tender.pdf')
  })

  it('never sends an empty name', () => {
    expect(cleanFilename('')).toBe('document')
    expect(cleanFilename('..\\')).toBe('document')
    expect(cleanFilename(String.fromCharCode(0x202e))).toBe('document')
  })
})
