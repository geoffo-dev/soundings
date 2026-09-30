import '@testing-library/jest-dom/vitest'

import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

afterEach(() => {
  cleanup()
  window.localStorage.clear()
  document.documentElement.className = ''
  document.documentElement.removeAttribute('style')
})

// jsdom lacks a few browser APIs that Radix, cmdk and the theme code use.
// Plain functions (not vi.fn) so `restoreMocks` can't reset them between tests.
function stub(target: object, name: string, value: unknown) {
  // jsdom declares some of these as accessors that return undefined.
  if ((target as Record<string, unknown>)[name] === undefined) {
    Object.defineProperty(target, name, { configurable: true, writable: true, value })
  }
}

const noop = () => undefined

stub(window, 'matchMedia', (query: string) => ({
  matches: false,
  media: query,
  onchange: null,
  addEventListener: noop,
  removeEventListener: noop,
  addListener: noop,
  removeListener: noop,
  dispatchEvent: () => false,
}))
stub(
  window,
  'ResizeObserver',
  class {
    observe = noop
    unobserve = noop
    disconnect = noop
  },
)
stub(Element.prototype, 'scrollIntoView', noop)
stub(Element.prototype, 'hasPointerCapture', () => false)
stub(Element.prototype, 'releasePointerCapture', noop)
