import { describe, expect, it } from 'vitest'

import { cn, hashString, initials } from '@/lib/utils'

describe('cn', () => {
  it('keeps font size and text colour together', () => {
    expect(cn('text-sm text-muted', 'text-primary')).toBe('text-sm text-primary')
    expect(cn('text-sm text-muted', 'text-base')).toBe('text-muted text-base')
  })

  it('merges custom shadows', () => {
    expect(cn('shadow-overlay', 'shadow-dialog')).toBe('shadow-dialog')
  })
})

describe('initials / hashString', () => {
  it('derives initials', () => {
    expect(initials('Ada Lovelace')).toBe('AL')
    expect(initials('  grace  ')).toBe('G')
    expect(initials('Jean Claude van Damme')).toBe('JD')
  })

  it('hashes deterministically', () => {
    expect(hashString('Ada')).toBe(hashString('Ada'))
    expect(hashString('Ada')).not.toBe(hashString('Grace'))
  })
})
