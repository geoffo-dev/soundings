import { describe, expect, it } from 'vitest'

import type { ProjectAccessEntry, RoleSource } from '@/api/types'
import { describeSources, peopleCount, wouldLeaveNoAdmin } from '@/features/project/settings/access'

const group = (id: string, name: string) => ({ id, name })
const direct = (role: RoleSource['role']): RoleSource => ({ kind: 'direct', role, group: null })
const viaGroup = (role: RoleSource['role'], id: string, name: string): RoleSource => ({
  kind: 'group',
  role,
  group: group(id, name),
})

function entry(id: string, sources: RoleSource[]): ProjectAccessEntry {
  return {
    user: { id, display_name: id, avatar_url: null, initials: id.slice(0, 2).toUpperCase() },
    email: `${id}@example.com`,
    role: 'admin',
    sources,
  }
}

describe('describeSources', () => {
  it('says where a role comes from', () => {
    expect(describeSources([direct('member')], 'member')).toBe('Direct')
    expect(describeSources([viaGroup('member', 'g1', 'Tools members')], 'member')).toBe(
      'via Tools members',
    )
  })

  it('names lower roles that the highest one outranks', () => {
    expect(
      describeSources([direct('viewer'), viaGroup('admin', 'g1', 'Innovation admins')], 'admin'),
    ).toBe('Direct (viewer) · via Innovation admins')
  })
})

describe('wouldLeaveNoAdmin (c11 in the client)', () => {
  it('locks the only direct admin', () => {
    const admins = [entry('alice', [direct('admin'), viaGroup('member', 'g1', 'Tools')])]
    expect(wouldLeaveNoAdmin(admins, { kind: 'direct', userId: 'alice' })).toBe(true)
  })

  it('frees a direct admin who is also admin through a group', () => {
    const admins = [entry('alice', [direct('admin'), viaGroup('admin', 'g1', 'Admins')])]
    expect(wouldLeaveNoAdmin(admins, { kind: 'direct', userId: 'alice' })).toBe(false)
    expect(wouldLeaveNoAdmin(admins, { kind: 'group', groupId: 'g1' })).toBe(false)
  })

  it('locks the only admin group', () => {
    const admins = [
      entry('kofi', [viaGroup('admin', 'g1', 'Admins')]),
      entry('lena', [viaGroup('admin', 'g1', 'Admins')]),
    ]
    expect(wouldLeaveNoAdmin(admins, { kind: 'group', groupId: 'g1' })).toBe(true)
    expect(wouldLeaveNoAdmin(admins, { kind: 'group', groupId: 'g2' })).toBe(false)
  })

  it('counts people', () => {
    expect(peopleCount(1)).toBe('1 person')
    expect(peopleCount(1200)).toBe('1,200 people')
  })
})
