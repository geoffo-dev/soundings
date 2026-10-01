import { useVirtualizer } from '@tanstack/react-virtual'
import { useCallback, useEffect, useLayoutEffect, useState } from 'react'

/** Fetch the next page when the last rendered row is this close to the end. */
const PREFETCH_ROWS = 20

interface PageVirtualizerOptions {
  count: number
  estimateSize: (index: number) => number
  getItemKey: (index: number) => string | number
  /** Load more rows as the reader nears the end (infinite queries). */
  hasNextPage?: boolean
  isFetchingNextPage?: boolean
  isError?: boolean
  fetchNextPage?: () => unknown
}

/**
 * A long list that scrolls with the page (the shell's `<main>`), rendering only
 * the rows in view: the admin users list and the audit log. Unlike the project
 * List (its own scroll box), filters and headings scroll away naturally.
 *
 *   const { listRef, rows, paddingTop, paddingBottom, measure } = usePageVirtualizer(…)
 */
export function usePageVirtualizer({
  count,
  estimateSize,
  getItemKey,
  hasNextPage = false,
  isFetchingNextPage = false,
  isError = false,
  fetchNextPage,
}: PageVirtualizerOptions) {
  const [list, setList] = useState<HTMLElement | null>(null)
  const [scrollMargin, setScrollMargin] = useState(0)
  const scrollElement =
    list?.closest<HTMLElement>('#main') ??
    (typeof document === 'undefined' ? null : (document.scrollingElement as HTMLElement | null))

  // Where the list starts inside the scrolling element. Content above it (filters that
  // wrap, a callout) can change size on any render, so measure after every render and on
  // window resizes; state only changes when the offset does. (A ResizeObserver on the page
  // would fire while the virtualizer's own observer resizes rows: a loop error.)
  const measure = useCallback(() => {
    if (!list || !scrollElement) return
    const offset =
      list.getBoundingClientRect().top -
      scrollElement.getBoundingClientRect().top +
      scrollElement.scrollTop
    setScrollMargin((current) => (Math.abs(current - offset) < 1 ? current : offset))
  }, [list, scrollElement])
  useLayoutEffect(measure)
  useEffect(() => {
    window.addEventListener('resize', measure)
    return () => window.removeEventListener('resize', measure)
  }, [measure])

  // The virtualizer is mutable by design; this hook isn't compiler-memoised.
  // eslint-disable-next-line react-hooks/incompatible-library -- TanStack Virtual (documented)
  const virtualizer = useVirtualizer({
    count,
    getScrollElement: () => scrollElement,
    estimateSize,
    getItemKey,
    overscan: 10,
    scrollMargin,
  })
  const rows = virtualizer.getVirtualItems()
  const lastIndex = rows.at(-1)?.index ?? -1

  useEffect(() => {
    if (
      fetchNextPage &&
      lastIndex >= count - PREFETCH_ROWS &&
      hasNextPage &&
      !isFetchingNextPage &&
      !isError
    ) {
      void fetchNextPage()
    }
  }, [lastIndex, count, hasNextPage, isFetchingNextPage, isError, fetchNextPage])

  const paddingTop = Math.max(0, (rows[0]?.start ?? scrollMargin) - scrollMargin)
  const paddingBottom = Math.max(
    0,
    virtualizer.getTotalSize() - ((rows.at(-1)?.end ?? scrollMargin) - scrollMargin),
  )
  const listRef = useCallback((node: HTMLElement | null) => setList(node), [])

  return {
    listRef,
    rows,
    paddingTop,
    paddingBottom,
    measure: virtualizer.measureElement,
    scrollToTop: () => scrollElement?.scrollTo({ top: 0 }),
  }
}
