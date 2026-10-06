import { describe, expect, it } from 'vitest'

import { visibleText } from './visible-text'

describe('visibleText (agent text)', () => {
  it('drops direction overrides, isolates, zero-width and tag characters', () => {
    expect(visibleText('a‮b⁦c​d\u{E0041}\u{E0042}e﻿')).toBe('abcde')
  })

  it('keeps what scripts and emoji need, and line breaks', () => {
    const family = '\u{1F468}‍\u{1F469}‍\u{1F467}'
    expect(visibleText(`${family} می‌خواهم\nnext\tline ❤️`)).toBe(
      `${family} می‌خواهم\nnext\tline ❤️`,
    )
  })
})
