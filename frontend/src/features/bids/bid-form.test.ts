import { describe, expect, it } from 'vitest'

import { bidFormProblems, normalisePrice, plainFieldErrors } from './bid-form-dialog'

const values = {
  bidder: 'Northwind Data Ltd',
  contactName: '',
  contactEmail: '',
  price: '',
  notes: '',
  hasPrice: true,
}

describe('the bid form says what is wrong from what is typed now (UX review M1)', () => {
  it('accepts a complete bid', () => {
    expect(bidFormProblems(values)).toEqual({})
    expect(
      bidFormProblems({ ...values, contactEmail: 'bids@northwind.example', price: '120,000' }),
    ).toEqual({})
  })

  it('flags a bad email and a bad price, and stops once they are fixed', () => {
    expect(bidFormProblems({ ...values, contactEmail: 'not an email' }).contact_email).toMatch(
      /email address/,
    )
    expect(bidFormProblems({ ...values, contactEmail: 'a@b' }).contact_email).toBeUndefined()
    expect(bidFormProblems({ ...values, price: '-5' }).price).toMatch(/above 0/)
    expect(bidFormProblems({ ...values, price: '120000.50' }).price).toBeUndefined()
    // No price question: the price isn't checked.
    expect(bidFormProblems({ ...values, price: 'abc', hasPrice: false }).price).toBeUndefined()
  })

  it('needs a bidder in one line of at most 120 characters', () => {
    expect(bidFormProblems({ ...values, bidder: '  ' }).bidder).toBe('Enter who sent the bid.')
    expect(bidFormProblems({ ...values, bidder: 'x'.repeat(121) }).bidder).toMatch(/120/)
    expect(bidFormProblems({ ...values, bidder: 'Two\nlines' }).bidder).toMatch(/One line/)
  })

  it('words the server’s validator messages plainly and drops fields it doesn’t show', () => {
    expect(
      plainFieldErrors({
        contact_email: "String should match pattern '^[^@\\s]+@[^@\\s]+$'",
        price: 'Input should be greater than 0',
        something_else: 'Field required',
      }),
    ).toEqual({
      contact_email: 'An email address, like name@example.com.',
      price: 'A price above 0, like 120000 or 120000.50.',
    })
  })

  it('normalises prices as typed', () => {
    expect(normalisePrice('£120,000')).toBe('120000.00')
    expect(normalisePrice('0')).toBeNull()
  })
})
