import { describe, expect, it } from 'vitest'

import { toIdeaFilters, validateProjectSearch } from '@/features/project/project-search'
import { validateIdeaSearch } from '@/features/idea/idea-search'
import { parseSearch, stringifySearch } from '@/lib/search-params'

describe('search params', () => {
  it('writes readable, shareable URLs and drops defaults', () => {
    expect(
      stringifySearch({
        view: 'list',
        status: ['new', 'evaluating'],
        needs_evaluators: true,
        high_disagreement: undefined,
        tag: [],
        q: '',
      }),
    ).toBe('?view=list&status=new,evaluating&needs_evaluators=1')
    expect(stringifySearch({})).toBe('')
  })

  it('round-trips through the project validator', () => {
    const url =
      '?view=board&status=new,closed,bogus&owner=me&tag=returns,b2b&high_disagreement=1&sort=-score'
    const search = validateProjectSearch(parseSearch(url))
    expect(search).toEqual({
      view: 'board',
      status: ['new', 'closed'],
      resolution: undefined,
      owner: 'me',
      tag: ['returns', 'b2b'],
      needs_evaluators: undefined,
      high_disagreement: true,
      q: undefined,
      sort: '-score',
    })
    expect(toIdeaFilters(search)).toMatchObject({ status: ['new', 'closed'], owner: 'me' })
  })

  it('ignores junk instead of failing', () => {
    expect(validateProjectSearch({ view: 'grid', owner: 'x; drop', sort: 'random' })).toMatchObject(
      {
        view: undefined,
        owner: undefined,
        sort: undefined,
      },
    )
  })

  it('accepts evaluate=1 from email links', () => {
    expect(validateIdeaSearch(parseSearch('?evaluate=1&tab=evaluations'))).toEqual({
      evaluate: true,
      tab: 'evaluations',
    })
    expect(validateIdeaSearch(parseSearch('?evaluate=0&tab=nope'))).toEqual({
      evaluate: undefined,
      tab: undefined,
    })
  })
})
