import { describe, expect, it } from 'vitest'

import { suggestKey, suggestSlug, validateCreateProject } from './create-project'

describe('create project suggestions', () => {
  it('suggests a URL name from the project name', () => {
    expect(suggestSlug('Customer Innovation')).toBe('customer-innovation')
    expect(suggestSlug('  Café & Crème — 2027! ')).toBe('cafe-creme-2027')
    expect(suggestSlug('***')).toBe('')
    const long = suggestSlug('Operations and supply chain improvements for the warehouse network')
    expect(long.length).toBeLessThanOrEqual(48)
    expect(long.endsWith('-')).toBe(false)
    expect(long).toBe('operations-and-supply-chain-improvements-for-the')
  })

  it('suggests an idea key', () => {
    expect(suggestKey('Customer Innovation')).toBe('CUST')
    expect(suggestKey('Sustainability')).toBe('SUST')
    expect(suggestKey('New Product Ideas')).toBe('NPI')
    expect(suggestKey('Éco')).toBe('ECO')
    expect(suggestKey('2027 roadmap')).toBe('')
    expect(suggestKey('X')).toBe('')
  })

  it('validates like the API', () => {
    const ok = {
      name: 'Customer Innovation',
      slug: 'customer-innovation',
      key: 'CUST',
      description: '',
    }
    expect(validateCreateProject(ok)).toEqual({})
    expect(validateCreateProject({ ...ok, name: ' ' }).name).toBeDefined()
    expect(validateCreateProject({ ...ok, slug: 'Customer Innovation' }).slug).toMatch(/lower-case/)
    expect(validateCreateProject({ ...ok, slug: 'a--b' }).slug).toBeDefined()
    expect(validateCreateProject({ ...ok, slug: 'x' }).slug).toMatch(/2/)
    expect(validateCreateProject({ ...ok, key: '1ABC' }).key).toBeDefined()
    expect(validateCreateProject({ ...ok, key: 'TOOLONGX' }).key).toBeDefined()
    expect(validateCreateProject({ ...ok, key: 'C' }).key).toBeDefined()
  })
})
