import { describe, expect, it } from 'vitest'

import { ApiError } from '@/api/errors'

import { newRow, sameIds, serverRowErrors, validateExternalIds } from './external-ids'

describe('external IDs', () => {
  it('ignores rows without an ID and trims the rest', () => {
    const rows = [newRow('employee_no', ' E1042 '), newRow('gitlab', ''), newRow('', '')]
    expect(validateExternalIds(rows)).toEqual({
      errors: {},
      ids: [{ kind: 'employee_no', value: 'E1042' }],
    })
  })

  it('checks kinds like the API: pattern and one per kind', () => {
    const bad = newRow('Employee No', 'E1')
    const first = newRow('gitlab', 'a')
    const twice = newRow('gitlab', 'b')
    const missing = newRow('', 'x')
    const { errors } = validateExternalIds([bad, first, twice, missing])
    expect(errors[bad.key]?.kind).toMatch(/Lower-case/)
    expect(errors[first.key]).toBeUndefined()
    expect(errors[twice.key]?.kind).toBe('One ID per kind')
    expect(errors[missing.key]?.kind).toMatch(/Enter a kind/)
  })

  it('maps a 422 on external_ids[i] to the i-th row with an ID', () => {
    const rows = [newRow('employee_no', ''), newRow('employee_no', 'E1'), newRow('gitlab', 'x')]
    const error = new ApiError({
      status: 422,
      code: 'validation_error',
      title: 'Invalid',
      problem: {
        errors: [{ loc: ['body', 'external_ids', 1, 'value'], msg: 'Too long', type: 'x' }],
      },
    })
    expect(serverRowErrors(error, rows)).toEqual({ [rows[2]?.key ?? '']: { value: 'Too long' } })
  })

  it('compares with the saved IDs regardless of order', () => {
    const saved = [
      { kind: 'gitlab', value: 'x' },
      { kind: 'employee_no', value: 'E1' },
    ]
    expect(sameIds([newRow('employee_no', 'E1'), newRow('gitlab', 'x')], saved)).toBe(true)
    expect(sameIds([newRow('employee_no', 'E2'), newRow('gitlab', 'x')], saved)).toBe(false)
  })
})
