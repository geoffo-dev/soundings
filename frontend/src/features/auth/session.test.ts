import { describe, expect, it } from 'vitest'

import { safeNextPath } from '@/features/auth/session'

describe('safeNextPath', () => {
  it('keeps same-site paths with their search and hash', () => {
    expect(safeNextPath('/ideas/CUST-12')).toBe('/ideas/CUST-12')
    expect(safeNextPath('/p/customer-innovation?view=list&owner=me#top')).toBe(
      '/p/customer-innovation?view=list&owner=me#top',
    )
  })

  it.each([
    ['not a string', 42],
    ['empty', ''],
    ['relative', 'ideas/CUST-12'],
    ['absolute URL', 'https://example.com/'],
    ['protocol-relative', '//example.com'],
    ['backslash, read as //', '/\\example.com'],
    ['backslash later on', '/ideas\\..\\..\\example.com'],
    ['tab inside the host part', '/\t/example.com'],
    ['newline', '/ideas/CUST-12\nx'],
    ['NUL', '/ideas/\u0000'],
    ['the login page', '/login?next=/'],
    ['an API path', '/api/v1/auth/logout/redirect'],
    ['an encoded API path', '/%61pi/v1/auth/me'],
  ])('sends %s to /', (_name, next) => {
    expect(safeNextPath(next)).toBe('/')
  })
})
