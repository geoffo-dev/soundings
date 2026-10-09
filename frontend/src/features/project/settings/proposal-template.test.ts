import { describe, expect, it } from 'vitest'

import type { ProposalTemplate } from '@/api/types'

import {
  emptySection,
  hasTemplateErrors,
  isTemplateDirty,
  moveSection,
  removedSectionNote,
  restoredSection,
  serverTemplateErrors,
  toSectionDrafts,
  toTemplateUpdate,
  validateTemplate,
} from './proposal-template'

const TEMPLATE: ProposalTemplate = {
  sections: [
    { key: 'problem', title: 'Problem', hint: 'Who has it?', position: 1, proposal_count: 2 },
    { key: 'summary', title: 'Summary', hint: '', position: 0, proposal_count: 3 },
  ],
  removed_sections: [
    {
      key: 'market',
      title: 'Market & users',
      hint: 'Who buys it?',
      position: 1,
      removed_at: '2026-10-01T10:00:00Z',
      proposal_count: 1,
    },
  ],
}

describe('proposal template form', () => {
  it('keeps keys (never shown) and order; new sections go without a key', () => {
    const drafts = toSectionDrafts(TEMPLATE.sections)
    expect(drafts.map((d) => d.key)).toEqual(['summary', 'problem'])
    const added = { ...emptySection(), title: 'Effort & rollout' }
    const update = toTemplateUpdate([...moveSection(drafts, 0, 1), added])
    expect(update.sections).toEqual([
      { key: 'problem', title: 'Problem', hint: 'Who has it?' },
      { key: 'summary', title: 'Summary', hint: '' },
      { title: 'Effort & rollout', hint: '' },
    ])
  })

  it('is dirty only when something would change, order included', () => {
    const drafts = toSectionDrafts(TEMPLATE.sections)
    expect(isTemplateDirty(drafts, TEMPLATE)).toBe(false)
    expect(isTemplateDirty(moveSection(drafts, 0, 1), TEMPLATE)).toBe(true)
    expect(
      isTemplateDirty(
        drafts.map((d) => (d.key === 'summary' ? { ...d, title: 'Overview' } : d)),
        TEMPLATE,
      ),
    ).toBe(true)
  })

  it('checks titles, hints and the 1–12 limit', () => {
    const drafts = toSectionDrafts(TEMPLATE.sections)
    expect(hasTemplateErrors(validateTemplate(drafts))).toBe(false)
    const clash = drafts.map((d) => ({ ...d, title: 'problem' }))
    expect(validateTemplate(clash).rows.problem?.title).toBe('Another section is called “problem”.')
    const long = [{ ...emptySection(), title: 'x'.repeat(61), hint: 'y'.repeat(201) }]
    const errors = validateTemplate(long)
    expect(Object.values(errors.rows)[0]).toEqual({
      title: 'At most 60 characters.',
      hint: 'Keep it to one line (200 characters).',
    })
    expect(validateTemplate([]).form).toBe('A proposal needs at least one section.')
    const thirteen = Array.from({ length: 13 }, (_, i) => ({ ...emptySection(), title: `S${i}` }))
    expect(validateTemplate(thirteen).form).toBe('A proposal has at most 12 sections.')
  })

  it('restores a removed section with its key, and words why it was kept', () => {
    const removed = TEMPLATE.removed_sections[0]
    if (!removed) throw new Error('fixture')
    expect(restoredSection(removed)).toMatchObject({ key: 'market', title: 'Market & users' })
    expect(removedSectionNote(removed)).toBe('Text in 1 proposal')
    expect(removedSectionNote({ proposal_count: 0 })).toBe('Kept for its comments and suggestions')
  })

  it('maps server field errors to rows', () => {
    const drafts = toSectionDrafts(TEMPLATE.sections)
    const errors = serverTemplateErrors(drafts, [
      { loc: ['body', 'sections', 1, 'title'], msg: 'Too long' },
      { loc: ['body', 'sections', 0, 'key'], msg: 'Unknown section' },
    ])
    expect(errors.rows.problem?.title).toBe('Too long')
    expect(errors.form).toBe('Unknown section')
  })
})
