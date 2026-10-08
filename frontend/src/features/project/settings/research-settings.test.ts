import { describe, expect, it } from 'vitest'

import type { ResearchSettings } from '@/api/types'

import {
  defaultItemDrafts,
  emptyItem,
  hasChecklistErrors,
  isResearchDirty,
  removedItemNote,
  savedToast,
  toItemDrafts,
  toResearchUpdate,
  validateChecklist,
} from './research-settings'

const SETTINGS: ResearchSettings = {
  step: 'before_evaluation',
  items: [
    { id: 'i-2', title: 'Teams consulted', hint: 'Who said what', required: true, position: 1 },
    { id: 'i-1', title: 'Not done elsewhere', hint: '', required: true, position: 0 },
  ],
  removed_items: [],
  default_items: [
    { title: 'Not already being done elsewhere', hint: 'Search', required: true },
    { title: 'Data protection considered', hint: '', required: false },
  ],
  ideas_in_research: 0,
}

describe('research settings form', () => {
  it('sends the checklist in order while on, and only the step while off', () => {
    const drafts = toItemDrafts(SETTINGS.items)
    expect(toResearchUpdate('before_proposal', drafts)).toEqual({
      step: 'before_proposal',
      items: [
        { id: 'i-1', title: 'Not done elsewhere', hint: '', required: true },
        { id: 'i-2', title: 'Teams consulted', hint: 'Who said what', required: true },
      ],
    })
    expect(toResearchUpdate('off', drafts)).toEqual({ step: 'off', items: [] })
  })

  it('offers the default checklist as new rows', () => {
    const drafts = defaultItemDrafts(SETTINGS.default_items)
    expect(drafts.map((d) => [d.id, d.title, d.required])).toEqual([
      [null, 'Not already being done elsewhere', true],
      [null, 'Data protection considered', false],
    ])
  })

  it('is dirty when the step or (while on) the checklist changes', () => {
    const drafts = toItemDrafts(SETTINGS.items)
    expect(isResearchDirty('before_evaluation', drafts, SETTINGS)).toBe(false)
    expect(isResearchDirty('off', drafts, SETTINGS)).toBe(true)
    const optional = drafts.map((d) => (d.id === 'i-2' ? { ...d, required: false } : d))
    expect(isResearchDirty('before_evaluation', optional, SETTINGS)).toBe(true)
    expect(isResearchDirty('off', [], { ...SETTINGS, step: 'off' })).toBe(false)
  })

  it('checks items only while the step is on: 1–10, titles 1–80, unique', () => {
    expect(hasChecklistErrors(validateChecklist('off', []))).toBe(false)
    expect(validateChecklist('before_evaluation', []).form).toBe(
      'The checklist needs at least one item.',
    )
    const clash = [
      { ...emptyItem(), title: 'Legal' },
      { ...emptyItem(), title: 'legal' },
    ]
    expect(Object.values(validateChecklist('before_proposal', clash).rows)[1]?.title).toBe(
      'Another item is called “legal”.',
    )
    const eleven = Array.from({ length: 11 }, (_, i) => ({ ...emptyItem(), title: `Item ${i}` }))
    expect(validateChecklist('before_evaluation', eleven).form).toBe(
      'The checklist has at most 10 items.',
    )
    expect(removedItemNote({ answer_count: 1 })).toBe('Answered on 1 idea')
  })
})

describe('savedToast', () => {
  it('says "Checklist saved" when only the checklist changed (UX review m4)', () => {
    expect(savedToast('before_evaluation', 'before_evaluation').title).toBe('Checklist saved')
  })

  it('names the step when it changed, and says what the board does', () => {
    expect(savedToast('off', 'before_proposal')).toEqual({
      title: 'Research step saved: before proposal',
      description: 'The board shows a Research column now.',
    })
    expect(savedToast('before_proposal', 'before_evaluation').description).toBe(
      'The board’s Research column has moved too.',
    )
    expect(savedToast('before_evaluation', 'off').title).toBe('Research step turned off')
  })
})
