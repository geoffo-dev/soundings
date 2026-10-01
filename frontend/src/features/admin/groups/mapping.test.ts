import { describe, expect, it } from 'vitest'

import type { MappingTestGroup, MappingTestResult } from '@/api/types'

import {
  mappingHeadline,
  mappingRows,
  normaliseIdpValue,
  parseClaims,
  summariseMappingTest,
} from './mapping'

const group = (
  id: string,
  name: string,
  effect: MappingTestGroup['effect'],
  extra: Partial<MappingTestGroup> = {},
): MappingTestGroup => ({
  group: { id, name },
  sync_mode: 'managed',
  matched_values: effect === 'add' || effect === 'keep' ? [name.toLowerCase()] : [],
  effect,
  manual: false,
  ...extra,
})

const result = (overrides: Partial<MappingTestResult> = {}): MappingTestResult => ({
  groups_claim: 'groups',
  claim_found: true,
  values: ['innovation/members', 'tools/members'],
  ignored_count: 0,
  groups: [],
  project_roles: [],
  ...overrides,
})

describe('normaliseIdpValue', () => {
  it('matches the server rule: trim, strip slashes at both ends, lower-case', () => {
    expect(normaliseIdpValue(' /Innovation/Admins ')).toBe('innovation/admins')
    expect(normaliseIdpValue('//tools/members/')).toBe('tools/members')
    expect(normaliseIdpValue('/ Ops /')).toBe('ops')
    expect(normaliseIdpValue(' / ')).toBe('')
    expect(normaliseIdpValue('0b5c-Entra-ID')).toBe('0b5c-entra-id')
  })
})

describe('mapping test presentation', () => {
  it('orders rows like a diff: joins, leaves, stays — by name within each', () => {
    const rows = mappingRows(
      result({
        groups: [
          group('g4', 'Viewers', 'keep', { sync_mode: 'additive', matched_values: [] }),
          group('g3', 'Tools members', 'add'),
          group('g2', 'Innovation admins', 'remove'),
          group('g1', 'Innovation members', 'add', { manual: true }),
        ],
      }),
      'g3',
    )
    expect(rows.map((row) => `${row.symbol} ${row.label} ${row.group.name}`)).toEqual([
      '+ Joins Innovation members',
      '+ Joins Tools members',
      '− Leaves Innovation admins',
      '= Stays Viewers',
    ])
    expect(rows.map((row) => row.tone)).toEqual(['success', 'success', 'danger', 'neutral'])
    expect(rows.find((row) => row.highlighted)?.group.name).toBe('Tools members')
  })

  it('explains each effect in a sentence', () => {
    const notes = mappingRows(
      result({
        groups: [
          group('a', 'A', 'add', { matched_values: ['tools/members'] }),
          group('b', 'B', 'add', { manual: true, matched_values: ['b'] }),
          group('c', 'C', 'remove'),
          group('d', 'D', 'remove', { manual: true }),
          group('e', 'E', 'keep', { matched_values: ['e'] }),
          group('f', 'F', 'keep', { sync_mode: 'additive', matched_values: [] }),
        ],
      }),
    ).map((row) => row.note)
    expect(notes).toEqual([
      'Matches tools/members.',
      'Matches b. Already added by hand; becomes synced too.',
      'No longer matches, so they leave this managed group.',
      'No longer matches. Stays a member: they were also added by hand.',
      'Matches e. Already a synced member.',
      'No longer matches, but additive groups never remove anyone at sign-in.',
    ])
  })

  it('summarises the claim: off, missing, empty, found', () => {
    expect(summariseMappingTest(result({ groups_claim: null, claim_found: false })).title).toBe(
      'Group sync is off',
    )
    const missing = summariseMappingTest(
      result({ claim_found: false, values: [], groups: [group('x', 'X', 'remove')] }),
    )
    expect(missing).toMatchObject({ tone: 'warning', title: 'No “groups” claim in these claims' })
    expect(missing.detail).toMatch(/leave every managed group/)
    expect(summariseMappingTest(result({ values: [], ignored_count: 2 }))).toEqual({
      tone: 'neutral',
      title: 'The “groups” claim has no usable values',
      detail: 'Nobody would join a group. 2 entries were ignored (not text, or empty).',
    })
    expect(summariseMappingTest(result({ ignored_count: 1 }))).toEqual({
      tone: 'info',
      title: 'Found 2 values in “groups”',
      detail: '1 entry was ignored (not text, or empty).',
    })
  })

  it('says what happens in one line', () => {
    const res = result({
      groups: [group('a', 'A', 'add'), group('b', 'B', 'add'), group('c', 'C', 'remove')],
    })
    expect(mappingHeadline(res, true)).toBe('This person joins 2 groups and leaves 1 group')
    expect(mappingHeadline(result(), false)).toBe('Someone with these claims would join no groups')
  })
})

describe('parseClaims', () => {
  it('accepts a JSON object and explains anything else', () => {
    expect(parseClaims('{"groups": ["/a"]}')).toEqual({ ok: true, claims: { groups: ['/a'] } })
    expect(parseClaims('  ')).toMatchObject({ ok: false })
    const message = (raw: string) => {
      const parsed = parseClaims(raw)
      return parsed.ok ? null : parsed.message
    }
    expect(message('["a"]')).toMatch(/object/)
    expect(message('{groups: [}')).toMatch(/valid JSON/)
    expect(message('eyJhbGciOi.eyJzdWIiOi.c2ln')).toMatch(/encoded token/)
  })
})
