import { afterEach, describe, expect, it } from 'vitest'

import {
  EMPTY_DRAFT,
  readDraft,
  readLastProject,
  writeDraft,
  writeLastProject,
} from '@/features/new-idea/draft'
import { clearDrafts, draftKey } from '@/lib/drafts'

const BOB = 'user-bob'
const CAROL = 'user-carol'

afterEach(() => {
  localStorage.clear()
  sessionStorage.clear()
})

describe('drafts', () => {
  it('keeps a New idea draft per user', () => {
    writeDraft(BOB, { ...EMPTY_DRAFT, title: 'Bob: confidential plan' })
    writeLastProject(BOB, 'customer-innovation')

    expect(readDraft(BOB).title).toBe('Bob: confidential plan')
    expect(readDraft(CAROL)).toEqual(EMPTY_DRAFT)
    expect(readLastProject(CAROL)).toBeUndefined()
  })

  it('clears every draft when the session ends, including old unscoped keys', () => {
    writeDraft(BOB, { ...EMPTY_DRAFT, title: 'Bob: confidential plan' })
    writeLastProject(BOB, 'customer-innovation')
    sessionStorage.setItem(draftKey(BOB, 'comment:CUST-12'), 'Half a comment')
    localStorage.setItem('soundings-new-idea-draft', '{"title":"from before"}')
    sessionStorage.setItem('soundings-comment-draft:CUST-3', 'old comment')
    localStorage.setItem('soundings-theme', 'dark')

    clearDrafts()

    expect(readDraft(BOB)).toEqual(EMPTY_DRAFT)
    expect(readLastProject(BOB)).toBeUndefined()
    expect(sessionStorage.length).toBe(0)
    expect(localStorage.getItem('soundings-new-idea-draft')).toBeNull()
    // Preferences that aren't drafts stay.
    expect(localStorage.getItem('soundings-theme')).toBe('dark')
  })
})
