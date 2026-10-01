import { describe, expect, it } from 'vitest'

import { normaliseFilters } from '@/api/keys'
import { parseSearch, stringifySearch } from '@/lib/search-params'

import {
  activeFilters,
  clearFilters,
  hasActiveFilters,
  nextSort,
  parseSort,
  sortDirectionFor,
  sortLabel,
  sortMenuOptions,
  toIdeaFilters,
  toggleValue,
  validateProjectSearch,
  withView,
  type ProjectSearch,
} from './project-search'

const ALICE = '10000000-0000-4000-8000-000000000002'

/** URL → state → URL, as the router does it. */
const roundTrip = (url: string) => stringifySearch({ ...validateProjectSearch(parseSearch(url)) })

describe('filters ⇄ URL', () => {
  it('reads every filter from a readable URL', () => {
    const search = validateProjectSearch(
      parseSearch(
        `?view=list&status=new,evaluating&owner=${ALICE}&tag=returns,b2b&needs_evaluators=1&high_disagreement=1&q=qr%20code&sort=-score`,
      ),
    )
    expect(search).toEqual({
      view: 'list',
      status: ['new', 'evaluating'],
      resolution: undefined,
      owner: ALICE,
      tag: ['returns', 'b2b'],
      needs_evaluators: true,
      high_disagreement: true,
      q: 'qr code',
      sort: '-score',
    })
  })

  it('writes the same URL back (shareable views)', () => {
    expect(roundTrip('?view=list&status=new,evaluating&owner=me&needs_evaluators=1')).toBe(
      '?view=list&status=new,evaluating&owner=me&needs_evaluators=1',
    )
    expect(roundTrip('?tag=returns&q=locker&sort=title')).toBe('?tag=returns&q=locker&sort=title')
  })

  it('leaves defaults out of the URL', () => {
    expect(roundTrip('?sort=-updated')).toBe('')
    expect(roundTrip('?needs_evaluators=0&high_disagreement=no&q=%20%20')).toBe('')
    expect(stringifySearch({ ...clearFilters({ view: 'board', owner: 'me', q: 'x' }) })).toBe(
      '?view=board',
    )
  })

  it('ignores junk values instead of failing', () => {
    expect(
      validateProjectSearch({
        view: 'kanban',
        status: 'new,nope',
        owner: 'bob',
        sort: 'random',
        needs_evaluators: 'maybe',
      }),
    ).toMatchObject({
      view: undefined,
      status: ['new'],
      owner: undefined,
      sort: undefined,
      needs_evaluators: undefined,
    })
  })

  it('caps tags at ten, as the API does', () => {
    const tags = Array.from({ length: 12 }, (_, i) => `t${i}`).join(',')
    expect(validateProjectSearch({ tag: tags }).tag).toHaveLength(10)
  })

  it('maps the URL state to API filters that share a cache entry', () => {
    const a = toIdeaFilters(validateProjectSearch(parseSearch('?status=new,closed&tag=b,a')))
    const b = toIdeaFilters(validateProjectSearch(parseSearch('?tag=a,b&status=closed,new')))
    expect(normaliseFilters(a)).toEqual(normaliseFilters(b))
    expect(normaliseFilters(a)).toEqual({ status: ['closed', 'new'], tag: ['a', 'b'] })
  })
})

describe('active filters per view', () => {
  const search: ProjectSearch = { status: ['new'], owner: 'me', view: 'board', sort: 'title' }

  it('counts status only in the List (the Board has a column per status)', () => {
    expect(activeFilters(search, 'list')).toEqual(['status', 'owner'])
    expect(activeFilters(search, 'board')).toEqual(['owner'])
    expect(hasActiveFilters({ status: ['new'] }, 'board')).toBe(false)
    expect(hasActiveFilters({ sort: '-score', view: 'list' }, 'list')).toBe(false)
  })

  it('switching to the Board drops status and resolution, the List keeps everything', () => {
    expect(withView({ ...search, resolution: ['accepted'] }, 'board')).toEqual({
      owner: 'me',
      view: 'board',
      sort: 'title',
    })
    expect(withView(search, 'list')).toEqual({ ...search, view: 'list' })
  })

  it('clearing keeps the view and the sort', () => {
    expect(clearFilters({ ...search, q: 'x', high_disagreement: true })).toEqual({
      view: 'board',
      sort: 'title',
    })
  })

  it('toggles values in list filters and drops empty lists', () => {
    expect(toggleValue(undefined, 'new')).toEqual(['new'])
    expect(toggleValue(['new'], 'closed')).toEqual(['new', 'closed'])
    expect(toggleValue(['new'], 'new')).toBeUndefined()
  })
})

describe('sort mapping', () => {
  it('defaults to most recently updated', () => {
    expect(parseSort(undefined)).toEqual({ column: 'updated', direction: 'desc' })
    expect(sortDirectionFor(undefined, 'updated')).toBe('desc')
    expect(sortDirectionFor(undefined, 'score')).toBe(false)
    expect(sortLabel(undefined)).toBe('Recently updated')
  })

  it('starts a new column in its natural direction', () => {
    expect(nextSort(undefined, 'score')).toBe('-score')
    expect(nextSort(undefined, 'votes')).toBe('-votes')
    expect(nextSort(undefined, 'title')).toBe('title')
    expect(nextSort('-score', 'created')).toBe('-created')
  })

  it('flips the current column, and the default order leaves the URL', () => {
    expect(nextSort('-score', 'score')).toBe('score')
    expect(nextSort('score', 'score')).toBe('-score')
    expect(nextSort('title', 'title')).toBe('-title')
    expect(nextSort(undefined, 'updated')).toBe('updated')
    expect(nextSort('updated', 'updated')).toBeUndefined()
  })

  it('reports header state for aria-sort', () => {
    expect(sortDirectionFor('-votes', 'votes')).toBe('desc')
    expect(sortDirectionFor('title', 'title')).toBe('asc')
    expect(sortDirectionFor('title', 'votes')).toBe(false)
    expect(sortLabel('-score')).toBe('Highest score')
  })
})

describe('sort menu', () => {
  it('offers five orders, plus the one in use when a header picked another', () => {
    const values = (sort?: Parameters<typeof sortMenuOptions>[0]) =>
      sortMenuOptions(sort).map((option) => option.value)
    expect(values()).toEqual(['-updated', '-score', '-votes', '-created', 'title'])
    expect(values('-score')).toHaveLength(5)
    expect(values('score')).toEqual(['-updated', '-score', '-votes', '-created', 'title', 'score'])
    expect(sortLabel('score')).toBe('Lowest score')
    expect(sortLabel(undefined)).toBe('Recently updated')
  })
})
