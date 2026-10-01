import { describe, expect, it } from 'vitest'

import { defaultStatuses, effectiveStatuses, validateEmailSearch } from './email-search'

describe('the outbox filter (contract-phase3 §3.10)', () => {
  it('opens on what needs attention: failed, with what is still queued', () => {
    expect(defaultStatuses({ failed: 3, queued: 1 }, false)).toEqual(['failed', 'queued'])
    expect(defaultStatuses({ failed: 3, queued: 0 }, false)).toEqual(['failed'])
    // Mail waiting too long, nothing failed yet: the queue.
    expect(defaultStatuses({ failed: 0, queued: 4 }, true)).toEqual(['queued'])
    // All well: everything.
    expect(defaultStatuses({ failed: 0, queued: 2 }, false)).toEqual([])
  })

  it('the URL wins over the default; "all" means no filter', () => {
    expect(effectiveStatuses(undefined, ['failed'])).toEqual(['failed'])
    expect(effectiveStatuses(['all'], ['failed'])).toEqual([])
    expect(effectiveStatuses(['sent'], ['failed'])).toEqual(['sent'])
    expect(validateEmailSearch({ status: 'failed,all' })).toEqual({
      status: ['all'],
      type: undefined,
    })
  })
})
