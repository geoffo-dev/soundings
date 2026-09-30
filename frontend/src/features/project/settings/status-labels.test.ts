import { describe, expect, it } from 'vitest'

import { DEFAULT_LABELS, labelChanges } from './status-labels'

describe('status label changes', () => {
  const saved = { ...DEFAULT_LABELS, new: 'Triage', accepted: 'Adopted' }

  it('sends only what changed', () => {
    expect(labelChanges(saved, saved)).toEqual({})
    expect(labelChanges({ ...saved, proposal: ' Business case ' }, saved)).toEqual({
      proposal: 'Business case',
    })
  })

  it('resets with null when a label is emptied or set back to its default', () => {
    expect(labelChanges({ ...saved, new: '' }, saved)).toEqual({ new: null })
    expect(labelChanges({ ...saved, accepted: 'Accepted' }, saved)).toEqual({ accepted: null })
    expect(labelChanges({ ...DEFAULT_LABELS }, saved)).toEqual({ new: null, accepted: null })
  })
})
