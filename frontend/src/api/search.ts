import { keepPreviousData, queryOptions, useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'

import { api, unwrap } from '@/api/client'
import { queryKeys } from '@/api/keys'

export const SEARCH_DEBOUNCE_MS = 150

export const globalSearchQueryOptions = (q: string, limit = 8) =>
  queryOptions({
    queryKey: queryKeys.search.query(q, limit),
    queryFn: ({ signal }) =>
      unwrap(api.GET('/api/v1/search', { params: { query: { q: q.trim(), limit } }, signal })),
    staleTime: 30_000,
    placeholderData: keepPreviousData,
  })

/** Returns `value` once it has stopped changing for `delay` ms. */
export function useDebouncedValue<T>(value: T, delay = SEARCH_DEBOUNCE_MS): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delay)
    return () => window.clearTimeout(timer)
  }, [value, delay])
  return debounced
}

/**
 * Ideas and projects matching `q` (palette, pickers). Debounced; idle for an
 * empty query; keeps the previous results while typing. An exact key
 * (`cust-12`) always comes first. Results never contain scores.
 */
export function useGlobalSearch(q: string, { limit = 8, debounceMs = SEARCH_DEBOUNCE_MS } = {}) {
  const debounced = useDebouncedValue(q.trim().slice(0, 200), debounceMs)
  const query = useQuery({
    ...globalSearchQueryOptions(debounced, limit),
    enabled: debounced.length > 0,
  })
  return {
    ...query,
    /** True while the user is typing or the request is in flight. */
    isSearching: q.trim() !== debounced || (query.isFetching && debounced.length > 0),
    query: debounced,
  }
}
