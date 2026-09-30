import { QueryClient, type InfiniteData } from '@tanstack/react-query'
import { describe, expect, it } from 'vitest'

import { moveOnBoards } from '@/api/cache'
import { queryKeys } from '@/api/keys'
import type { Board, BoardColumn, IdeaPage, IdeaStatus, IdeaSummary } from '@/api/types'

const idea = (key: string, status: IdeaStatus, extra: Partial<IdeaSummary> = {}) =>
  ({
    id: `id-${key}`,
    key,
    title: key,
    status,
    resolution: null,
    status_label: status,
    ...extra,
  }) as IdeaSummary

const column = (status: IdeaStatus, items: IdeaSummary[], count: number): BoardColumn => ({
  status,
  label: status,
  count,
  items,
  next_cursor: count > items.length ? 'more' : null,
  resolution_counts: status === 'closed' ? { accepted: 1, rejected: 0, parked: 0 } : null,
})

function board(): Board {
  return {
    columns: [
      column('new', [idea('CUST-1', 'new')], 60),
      column('evaluating', [idea('CUST-2', 'evaluating')], 1),
      column('shortlisted', [], 0),
      column('proposal', [], 0),
      column('closed', [idea('CUST-3', 'closed', { resolution: 'accepted' })], 1),
    ],
  }
}

const counts = (data: Board | undefined) =>
  Object.fromEntries((data?.columns ?? []).map((c) => [c.status, c.count]))
const keysIn = (data: Board | undefined, status: IdeaStatus) =>
  data?.columns.find((c) => c.status === status)?.items.map((i) => i.key)

describe('moveOnBoards', () => {
  const filters = { owner: 'me', sort: '-score' as const }

  it('moves a card from the first page and keeps counts and resolution counts right', () => {
    const client = new QueryClient()
    const key = queryKeys.ideas.board('cust', filters)
    client.setQueryData(key, board())

    moveOnBoards(client, 'cust-1', {
      status: 'closed',
      resolution: 'parked',
      status_label: 'Parked',
    })

    const data = client.getQueryData<Board>(key)
    expect(counts(data)).toMatchObject({ new: 59, closed: 2 })
    expect(keysIn(data, 'closed')).toEqual(['CUST-1', 'CUST-3'])
    expect(data?.columns.at(-1)?.resolution_counts).toEqual({ accepted: 1, rejected: 0, parked: 1 })
  })

  it('moves a card loaded with "Show more" into its new column at once', () => {
    const client = new QueryClient()
    const boardKey = queryKeys.ideas.board('cust', filters)
    client.setQueryData(boardKey, board())
    // "Show more" of New: list_ideas with the board's filters and status=new (keys in any order).
    const more: InfiniteData<IdeaPage> = {
      pages: [{ items: [idea('CUST-60', 'new')], next_cursor: null, total: 60 }],
      pageParams: ['more'],
    }
    client.setQueryData(queryKeys.ideas.list('cust', { status: ['new'], ...filters }), more)
    // Another board with other filters doesn't hold that card: left alone.
    const otherKey = queryKeys.ideas.board('cust', { sort: '-score' })
    client.setQueryData(otherKey, board())

    moveOnBoards(client, 'CUST-60', {
      status: 'shortlisted',
      resolution: null,
      status_label: 'Shortlisted',
    })

    const data = client.getQueryData<Board>(boardKey)
    expect(counts(data)).toMatchObject({ new: 59, shortlisted: 1 })
    expect(keysIn(data, 'shortlisted')).toEqual(['CUST-60'])
    expect(client.getQueryData(otherKey)).toEqual(board())
  })
})
