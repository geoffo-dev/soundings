import { describe, expect, it } from 'vitest'

import { ApiError } from '@/api/errors'

import { tokenFromHash, TRACKING_TOKEN, VERIFICATION_TOKEN } from './fragment-token'
import {
  EMPTY_PUBLIC_FORM,
  isEmailAddress,
  nearLimit,
  submitProblem,
  toSubmission,
  validatePublicForm,
} from './submit-form'

const OPEN = { asks_for_email: true, email_required: false }
const REQUIRED = { asks_for_email: true, email_required: true }
const NO_EMAIL = { asks_for_email: false, email_required: false }
const form = (patch = {}) => ({ ...EMPTY_PUBLIC_FORM, title: 'Idea', summary: 'Why', ...patch })

describe('validatePublicForm', () => {
  it('needs only a title and a summary', () => {
    expect(validatePublicForm(EMPTY_PUBLIC_FORM, OPEN)).toEqual({
      title: expect.any(String),
      summary: expect.any(String),
    })
    expect(validatePublicForm(form(), OPEN)).toEqual({})
    expect(validatePublicForm(form({ title: '   ' }), OPEN).title).toBeDefined()
  })

  it('checks the limits the API enforces', () => {
    expect(validatePublicForm(form({ title: 'x'.repeat(201) }), OPEN).title).toMatch(/200/)
    expect(validatePublicForm(form({ summary: 'x'.repeat(501) }), OPEN).summary).toMatch(/500/)
    expect(validatePublicForm(form({ description: 'x'.repeat(10_001) }), OPEN).description).toBe(
      'Use at most 10,000 characters.',
    )
    expect(validatePublicForm(form({ name: 'x'.repeat(81) }), OPEN).name).toMatch(/80/)
  })

  it('asks for an email address only when the project requires one', () => {
    expect(validatePublicForm(form(), REQUIRED).email).toMatch(/confirm/)
    expect(validatePublicForm(form({ email: 'jo@example.org' }), REQUIRED)).toEqual({})
    expect(validatePublicForm(form({ email: 'not an address' }), OPEN).email).toMatch(/like/)
  })

  it('needs an address for updates, unless the instance has no email at all', () => {
    expect(validatePublicForm(form({ wantsUpdates: true }), OPEN).email).toMatch(/updates/)
    expect(validatePublicForm(form({ wantsUpdates: true }), NO_EMAIL)).toEqual({})
  })
})

describe('isEmailAddress', () => {
  it('takes one plain address, like the API', () => {
    expect(isEmailAddress('jo.marsh+ideas@example.org')).toBe(true)
    expect(isEmailAddress('Jo <jo@example.org>')).toBe(false)
    expect(isEmailAddress('jo@example.org, eve@example.org')).toBe(false)
    expect(isEmailAddress('jo@localhost')).toBe(false)
    expect(isEmailAddress('jo@test.invalid')).toBe(false)
  })
})

describe('toSubmission', () => {
  it('trims, drops blanks and sends the honeypot as website', () => {
    expect(
      toSubmission(
        form({ title: ' Idea ', name: '  ', email: ' jo@example.org ', wantsUpdates: true }),
        OPEN,
        'payload',
      ),
    ).toEqual({
      title: 'Idea',
      summary: 'Why',
      description_md: '',
      name: null,
      email: 'jo@example.org',
      wants_updates: true,
      altcha: 'payload',
      website: '',
    })
    expect(toSubmission(form({ honeypot: 'http://spam' }), OPEN, 'p').website).toBe('http://spam')
  })

  it('sends neither address nor opt-in when the instance has no email', () => {
    const body = toSubmission(form({ email: 'jo@example.org', wantsUpdates: true }), NO_EMAIL, 'p')
    expect(body.email).toBeNull()
    expect(body.wants_updates).toBe(false)
  })

  it('never asks for updates without an address', () => {
    expect(toSubmission(form({ wantsUpdates: true }), OPEN, 'p').wants_updates).toBe(false)
  })
})

describe('submitProblem', () => {
  const error = (status: number, code: string, errors?: { loc: (string | number)[]; msg: string }[]) =>
    new ApiError({
      status,
      code,
      title: code,
      problem: errors ? { errors: errors.map((e) => ({ ...e, type: 'value_error' })) } : undefined,
    })

  it('words rate limits, failed challenges and unavailable forms', () => {
    expect(submitProblem(error(429, 'too_many_attempts'))).toEqual({ kind: 'rate_limited' })
    expect(submitProblem(error(422, 'challenge_failed'))).toEqual({ kind: 'challenge' })
    expect(submitProblem(error(404, 'not_found'))).toEqual({ kind: 'unavailable' })
    expect(submitProblem(error(0, 'network_error'))).toEqual({ kind: 'network' })
    expect(submitProblem(new Error('boom'))).toEqual({ kind: 'other' })
  })

  it('puts the API’s field errors on the form’s fields', () => {
    expect(
      submitProblem(
        error(422, 'validation_error', [
          { loc: ['body', 'description_md'], msg: 'String should have at most 10000 characters' },
          { loc: ['body', 'wants_updates'], msg: 'Value error, wants_updates needs an email' },
        ]),
      ),
    ).toEqual({
      kind: 'fields',
      errors: {
        description: 'String should have at most 10000 characters.',
        email: 'Wants_updates needs an email.',
      },
    })
    expect(submitProblem(error(422, 'email_required'))).toEqual({
      kind: 'fields',
      errors: { email: expect.any(String) },
    })
    // A malformed ALTCHA payload is a verification problem, not a field.
    expect(
      submitProblem(error(422, 'validation_error', [{ loc: ['body', 'altcha'], msg: 'bad' }])),
    ).toEqual({ kind: 'challenge' })
  })
})

describe('nearLimit', () => {
  it('shows a count only near the limit', () => {
    expect(nearLimit('x'.repeat(10), 200)).toBeUndefined()
    expect(nearLimit('x'.repeat(170), 200)).toBe('170/200 characters')
  })
})

describe('tokenFromHash', () => {
  const token = 'A'.repeat(43)
  it('reads a well-formed token from the fragment only', () => {
    expect(tokenFromHash(`#${token}`, TRACKING_TOKEN)).toBe(token)
    expect(tokenFromHash(`#${token}x`, TRACKING_TOKEN)).toBeUndefined()
    expect(tokenFromHash('#', TRACKING_TOKEN)).toBeUndefined()
    expect(tokenFromHash('#%E0%A4%A', TRACKING_TOKEN)).toBeUndefined()
    expect(tokenFromHash('#<script>alert(1)</script>', VERIFICATION_TOKEN)).toBeUndefined()
    expect(tokenFromHash('#eyJ2IjoxfQ.c2ln-_abc', VERIFICATION_TOKEN)).toBe('eyJ2IjoxfQ.c2ln-_abc')
  })
})
