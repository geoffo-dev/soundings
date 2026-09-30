import { describe, expect, it } from 'vitest'

import type { RubricCriterion } from '@/api/types'

import {
  emptyCriterion,
  isRubricDirty,
  moveItem,
  parseWeight,
  serverRubricErrors,
  toDrafts,
  toRubricUpdate,
  validateRubric,
  weightShares,
  type CriterionDraft,
} from './rubric'

const criterion = (position: number, name: string, extra: Partial<RubricCriterion> = {}) => ({
  id: `00000000-0000-4000-8000-00000000000${position}`,
  position,
  name,
  description: `${name} description`,
  weight: 1,
  inverted: false,
  guidance: {},
  ...extra,
})

const RUBRIC: RubricCriterion[] = [
  criterion(1, 'Feasibility'),
  criterion(0, 'Value', { weight: 2, guidance: { '1': 'None', '5': 'Huge' } }),
  criterion(2, 'Effort', { inverted: true }),
]

const named = (drafts: CriterionDraft[], name: string) => drafts.find((d) => d.name === name)

describe('rubric drafts', () => {
  it('orders by position and round-trips unchanged', () => {
    const drafts = toDrafts(RUBRIC)
    expect(drafts.map((d) => d.name)).toEqual(['Value', 'Feasibility', 'Effort'])
    expect(isRubricDirty(drafts, RUBRIC)).toBe(false)
    expect(toRubricUpdate(drafts).criteria[0]).toEqual({
      id: RUBRIC[1]?.id,
      name: 'Value',
      description: 'Value description',
      weight: 2,
      inverted: false,
      guidance: { '1': 'None', '5': 'Huge' },
    })
  })

  it('notices edits, reordering and additions', () => {
    const drafts = toDrafts(RUBRIC)
    expect(isRubricDirty(moveItem(drafts, 0, 2), RUBRIC)).toBe(true)
    expect(isRubricDirty([...drafts, emptyCriterion()], RUBRIC)).toBe(true)
    const renamed = drafts.map((d) => (d.name === 'Effort' ? { ...d, name: 'Cost' } : d))
    expect(isRubricDirty(renamed, RUBRIC)).toBe(true)
  })

  it('sends new criteria without an id and trims text', () => {
    const added = { ...emptyCriterion(), name: '  Risk ', weight: '0.5', guidance: { '3': ' ' } }
    const body = toRubricUpdate([...toDrafts(RUBRIC), added])
    expect(body.criteria.at(-1)).toEqual({
      id: null,
      name: 'Risk',
      description: '',
      weight: 0.5,
      inverted: false,
      guidance: {},
    })
  })
})

describe('rubric validation', () => {
  it('accepts the saved rubric', () => {
    const result = validateRubric(toDrafts(RUBRIC))
    expect(result).toEqual({ rows: {}, form: undefined })
  })

  it('needs 3 to 6 criteria', () => {
    const drafts = toDrafts(RUBRIC)
    expect(validateRubric(drafts.slice(0, 2)).form).toMatch(/at least 3/)
    const seven = [
      ...drafts,
      ...Array.from({ length: 4 }, () => ({ ...emptyCriterion(), name: String(Math.random()) })),
    ]
    expect(validateRubric(seven).form).toMatch(/at most 6/)
  })

  it('checks names: required, short, unique ignoring case', () => {
    const drafts = toDrafts(RUBRIC)
    const blank = drafts.map((d) => (d.name === 'Effort' ? { ...d, name: '  ' } : d))
    expect(validateRubric(blank).rows[named(drafts, 'Effort')?.key ?? '']?.name).toMatch(/name/)
    const duplicate = drafts.map((d) => (d.name === 'Effort' ? { ...d, name: 'value ' } : d))
    const errors = validateRubric(duplicate)
    // Both rows of the clash are marked, whichever one you are editing.
    expect(errors.rows[named(drafts, 'Effort')?.key ?? '']?.name).toBe(
      'Another criterion is called “value”.',
    )
    expect(errors.rows[named(drafts, 'Value')?.key ?? '']?.name).toBe(
      'Another criterion is called “Value”.',
    )
    expect(errors.rows[named(drafts, 'Feasibility')?.key ?? '']).toBeUndefined()
    const long = drafts.map((d) => (d.name === 'Effort' ? { ...d, name: 'x'.repeat(41) } : d))
    expect(validateRubric(long).rows[named(drafts, 'Effort')?.key ?? '']?.name).toMatch(/40/)
  })

  it('checks weights: 0.01 to 10 with at most two decimals', () => {
    expect(parseWeight('1')).toBe(1)
    expect(parseWeight('0.25')).toBe(0.25)
    expect(parseWeight('.5')).toBe(0.5)
    expect(parseWeight('2,5')).toBe(2.5)
    expect(parseWeight('10')).toBe(10)
    for (const bad of ['0', '0.001', '10.01', '-1', 'abc', '', '1e2']) {
      expect(parseWeight(bad)).toBeNull()
    }
    const drafts = toDrafts(RUBRIC).map((d) => (d.name === 'Value' ? { ...d, weight: '11' } : d))
    expect(validateRubric(drafts).rows[drafts[0]?.key ?? '']?.weight).toMatch(/0.01 to 10/)
  })

  it('checks description and guidance lengths', () => {
    const drafts = toDrafts(RUBRIC).map((d) =>
      d.name === 'Value'
        ? { ...d, description: 'x'.repeat(201), guidance: { '5': 'y'.repeat(201) } }
        : d,
    )
    const row = validateRubric(drafts).rows[drafts[0]?.key ?? '']
    expect(row?.description).toBeDefined()
    expect(row?.['guidance.5']).toBeDefined()
  })

  it('shows each weight as a share of the aggregate', () => {
    const shares = weightShares(toDrafts(RUBRIC))
    expect([...shares.values()]).toEqual([50, 25, 25])
    const broken = toDrafts(RUBRIC).map((d) => ({ ...d, weight: 'x' }))
    expect(weightShares(broken).size).toBe(0)
  })

  it('maps server 422s onto the right row and field', () => {
    const drafts = toDrafts(RUBRIC)
    const errors = serverRubricErrors(drafts, [
      { loc: ['body', 'criteria', 2, 'weight'], msg: 'Too heavy' },
      { loc: ['body', 'criteria', 0, 'guidance', '5'], msg: 'Too long' },
      { loc: ['body', 'criteria'], msg: 'A rubric has 3 to 6 criteria' },
    ])
    expect(errors.rows[drafts[2]?.key ?? '']).toEqual({ weight: 'Too heavy' })
    expect(errors.rows[drafts[0]?.key ?? '']).toEqual({ 'guidance.5': 'Too long' })
    expect(errors.form).toBe('A rubric has 3 to 6 criteria')
  })

  it('moves rows and ignores moves off the ends', () => {
    expect(moveItem(['a', 'b', 'c'], 0, 2)).toEqual(['b', 'c', 'a'])
    expect(moveItem(['a', 'b', 'c'], 2, 1)).toEqual(['a', 'c', 'b'])
    expect(moveItem(['a', 'b', 'c'], 0, -1)).toEqual(['a', 'b', 'c'])
    expect(moveItem(['a', 'b', 'c'], 2, 3)).toEqual(['a', 'b', 'c'])
  })
})
