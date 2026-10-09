import { describe, expect, it } from 'vitest'

import type { IdeaSummary, ResearchAssignment } from '@/api/types'
import { showsResearcher } from '@/features/project/idea-meta'

import { assignmentText, researcherName } from './research-assignment'

const person = (id: string, display_name: string) => ({
  id,
  display_name,
  avatar_url: null,
  initials: display_name.slice(0, 2).toUpperCase(),
})
const SVEN = person('sven', 'Sven Lindqvist')
const BOB = person('bob', 'Bob Brown')

const assignment = (patch: Partial<ResearchAssignment> = {}): ResearchAssignment => ({
  researcher: null,
  researcher_in_project: true,
  assigned_at: null,
  due_at: null,
  overdue: false,
  ...patch,
})

describe('who does the research, in words (contract-phase8b §10)', () => {
  it('nobody assigned: the owner, or you as owner', () => {
    expect(researcherName(assignment(), SVEN, 'me')).toBe('Sven Lindqvist (owner)')
    expect(researcherName(assignment(), SVEN, 'sven')).toBe('You (owner)')
    expect(researcherName(assignment(), null, 'me')).toBe('The owner, once there is one')
  })

  it('a researcher: their name, or You; the owner named explicitly stays "(owner)"', () => {
    expect(researcherName(assignment({ researcher: BOB }), SVEN, 'me')).toBe('Bob Brown')
    expect(researcherName(assignment({ researcher: BOB }), SVEN, 'bob')).toBe('You')
    expect(researcherName(assignment({ researcher: SVEN }), SVEN, 'me')).toBe(
      'Sven Lindqvist (owner)',
    )
  })

  it('the line says outside the project and the due date, overdue in words', () => {
    const due = '2026-10-09T16:00:00Z'
    expect(
      assignmentText(
        assignment({ researcher: BOB, researcher_in_project: false, due_at: due }),
        SVEN,
        'me',
      ),
    ).toMatch(/^Research: Bob Brown · not in this project · due /)
    expect(assignmentText(assignment({ due_at: due, overdue: true }), SVEN, 'me')).toMatch(
      /^Research: Sven Lindqvist \(owner\) · overdue, was due /,
    )
    expect(assignmentText(assignment(), SVEN, 'me')).toBe('Research: Sven Lindqvist (owner)')
  })
})

describe('the researcher’s avatar on board cards', () => {
  const card = (patch: Partial<Pick<IdeaSummary, 'status' | 'researcher' | 'owner'>>) => ({
    status: 'research' as const,
    researcher: BOB,
    owner: SVEN,
    ...patch,
  })

  it('shows in Research when someone other than the owner was asked', () => {
    expect(showsResearcher(card({}))).toBe(true)
    expect(showsResearcher(card({ researcher: SVEN }))).toBe(false)
    expect(showsResearcher(card({ researcher: null }))).toBe(false)
    expect(showsResearcher(card({ status: 'new' }))).toBe(false)
    expect(showsResearcher(card({ owner: null }))).toBe(true)
  })
})
