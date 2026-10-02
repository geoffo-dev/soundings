import { describe, expect, it } from 'vitest'

import { publicFormChanges } from './public-form-settings'

const saved = {
  enabled: true,
  moderation_required: true,
  require_email_verification: false,
  intro_md: 'Tell us how to make returns easier.',
}

describe('publicFormChanges', () => {
  it('sends nothing when nothing changed (whitespace around the intro included)', () => {
    expect(publicFormChanges(saved, saved)).toEqual({})
    expect(publicFormChanges({ ...saved, intro_md: `  ${saved.intro_md}\n` }, saved)).toEqual({})
  })

  it('sends only the fields that changed, so another admin’s edit survives', () => {
    expect(publicFormChanges({ ...saved, moderation_required: false }, saved)).toEqual({
      moderation_required: false,
    })
    expect(
      publicFormChanges(
        { ...saved, enabled: false, require_email_verification: true, intro_md: ' New intro ' },
        saved,
      ),
    ).toEqual({ enabled: false, require_email_verification: true, intro_md: 'New intro' })
  })

  it('can clear the intro', () => {
    expect(publicFormChanges({ ...saved, intro_md: '   ' }, saved)).toEqual({ intro_md: '' })
  })
})
