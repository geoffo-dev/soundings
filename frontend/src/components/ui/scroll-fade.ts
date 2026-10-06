import { type RefCallback, useCallback, useRef } from 'react'

/**
 * A row that scrolls sideways (settings sections, tabs on a phone) says so: while
 * there is more to scroll towards an edge, the element gets `data-fade-start` /
 * `data-fade-end`, and the `scroll-fade-x` utility fades that edge out, so a cut-off
 * label reads as "more this way" instead of a clipped one. Use with `scroll-fade-x`.
 */
export function useScrollFade<T extends HTMLElement>(): RefCallback<T> {
  const stop = useRef<(() => void) | undefined>(undefined)
  return useCallback((node: T | null) => {
    stop.current?.()
    stop.current = node ? watch(node) : undefined
  }, [])
}

function watch(node: HTMLElement): () => void {
  const update = () => {
    const max = node.scrollWidth - node.clientWidth
    // Whole pixels: zoomed layouts leave fractions at either end.
    node.toggleAttribute('data-fade-start', max > 1 && node.scrollLeft > 1)
    node.toggleAttribute('data-fade-end', max > 1 && node.scrollLeft < max - 1)
  }
  update()
  node.addEventListener('scroll', update, { passive: true })
  const resize = typeof ResizeObserver === 'undefined' ? undefined : new ResizeObserver(update)
  resize?.observe(node)
  return () => {
    node.removeEventListener('scroll', update)
    resize?.disconnect()
  }
}
