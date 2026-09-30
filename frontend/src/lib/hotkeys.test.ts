import { describe, expect, it } from 'vitest'

import { createHotkeyMatcher, formatKeys, isTypingTarget } from '@/lib/hotkeys'

function key(k: string, init: KeyboardEventInit = {}, target: EventTarget = document.body, at = 0) {
  const event = new KeyboardEvent('keydown', { key: k, bubbles: true, cancelable: true, ...init })
  Object.defineProperty(event, 'target', { value: target })
  Object.defineProperty(event, 'timeStamp', { value: at })
  return event
}

describe('createHotkeyMatcher', () => {
  it('maps mod to ⌘ on macOS and Ctrl elsewhere', () => {
    const mac = createHotkeyMatcher('mod+k', { mac: true })
    expect(mac(key('k', { metaKey: true }))).toBe(true)
    expect(mac(key('k', { ctrlKey: true }))).toBe(false)
    const other = createHotkeyMatcher('mod+k', { mac: false })
    expect(other(key('k', { ctrlKey: true }))).toBe(true)
    expect(other(key('k'))).toBe(false)
  })

  it('ignores Shift for symbol keys like "?" but not for letters', () => {
    expect(createHotkeyMatcher('?')(key('?', { shiftKey: true }))).toBe(true)
    expect(createHotkeyMatcher('n')(key('N', { shiftKey: true }))).toBe(false)
    expect(createHotkeyMatcher('shift+n')(key('N', { shiftKey: true }))).toBe(true)
  })

  it('ignores plain keys while typing, but not modifier combos', () => {
    const input = document.createElement('input')
    const textarea = document.createElement('textarea')
    const checkbox = Object.assign(document.createElement('input'), { type: 'checkbox' })
    expect(createHotkeyMatcher('n')(key('n', {}, input))).toBe(false)
    expect(createHotkeyMatcher('n')(key('n', {}, textarea))).toBe(false)
    expect(createHotkeyMatcher('n')(key('n', {}, checkbox))).toBe(true)
    expect(createHotkeyMatcher('mod+k', { mac: false })(key('k', { ctrlKey: true }, input))).toBe(
      true,
    )
    expect(createHotkeyMatcher('n', { allowInInputs: true })(key('n', {}, input))).toBe(true)
  })

  it('ignores single keys inside dialogs and menus', () => {
    const dialog = document.createElement('div')
    dialog.setAttribute('role', 'dialog')
    const button = document.createElement('button')
    dialog.append(button)
    expect(createHotkeyMatcher('n')(key('n', {}, button))).toBe(false)
  })

  it('matches sequences within the timeout', () => {
    const match = createHotkeyMatcher('g m')
    expect(match(key('g', {}, document.body, 0))).toBe(false)
    expect(match(key('m', {}, document.body, 300))).toBe(true)

    // Too slow: the sequence resets.
    expect(match(key('g', {}, document.body, 1000))).toBe(false)
    expect(match(key('m', {}, document.body, 2500))).toBe(false)

    // A wrong key in between resets; "g g m" still works.
    expect(match(key('g', {}, document.body, 3000))).toBe(false)
    expect(match(key('x', {}, document.body, 3100))).toBe(false)
    expect(match(key('m', {}, document.body, 3200))).toBe(false)
    expect(match(key('g', {}, document.body, 4000))).toBe(false)
    expect(match(key('g', {}, document.body, 4100))).toBe(false)
    expect(match(key('m', {}, document.body, 4200))).toBe(true)
  })

  it('skips events that were already handled or are auto-repeats', () => {
    const match = createHotkeyMatcher('n')
    const handled = key('n')
    handled.preventDefault()
    expect(match(handled)).toBe(false)
    expect(match(key('n', { repeat: true }))).toBe(false)
  })
})

describe('formatKeys / isTypingTarget', () => {
  it('formats platform-aware labels', () => {
    expect(formatKeys('mod+k', true)).toEqual([['⌘', 'K']])
    expect(formatKeys('mod+k', false)).toEqual([['Ctrl', 'K']])
    expect(formatKeys('g m', false)).toEqual([['G'], ['M']])
    expect(formatKeys('shift+enter', false)).toEqual([['Shift', 'Enter']])
  })

  it('detects contenteditable', () => {
    const div = document.createElement('div')
    div.contentEditable = 'true'
    document.body.append(div)
    // jsdom doesn't implement isContentEditable; emulate the browser.
    Object.defineProperty(div, 'isContentEditable', { value: true })
    expect(isTypingTarget(div)).toBe(true)
    div.remove()
  })
})
