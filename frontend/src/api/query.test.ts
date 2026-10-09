import { describe, expect, it } from 'vitest'

import { ApiError } from '@/api/errors'
import { queryKeys } from '@/api/keys'
import { createQueryClient } from '@/api/query'

const notFound = new ApiError({ status: 404, code: 'not_found', title: 'Not found' })
const conflict = new ApiError({ status: 409, code: 'idea_closed', title: 'Closed' })

async function failWith(error: ApiError) {
  const queryClient = createQueryClient()
  queryClient.setQueryData(queryKeys.ideas.detail('TOOLS-12'), { key: 'TOOLS-12' })
  await queryClient
    .getMutationCache()
    .build(queryClient, {
      mutationFn: () => Promise.reject(error),
      meta: { silent: true },
    })
    .execute(undefined)
    .catch(() => undefined)
  return queryClient.getQueryState(queryKeys.ideas.detail('TOOLS-12'))
}

describe('query client', () => {
  // P8B-QA-F1: a guest researcher unassigned while the page is open (contract-phase8b §4.6).
  it('re-checks the cached idea when a write is refused with 404', async () => {
    expect((await failWith(notFound))?.isInvalidated).toBe(true)
  })

  it('leaves the idea alone for other refusals', async () => {
    expect((await failWith(conflict))?.isInvalidated).toBe(false)
  })
})
