import { useEffect, useEffectEvent } from 'react'

import { isMac } from '@/lib/utils'

/**
 * Tiny keyboard-shortcut layer.
 *
 * Syntax: keys joined with "+" form a combo, combos separated by spaces form a
 * sequence. `mod` is ⌘ on macOS and Ctrl elsewhere.
 *   "mod+k"   "?"   "n"   "shift+enter"   "g m"   "["
 *
 * Shortcuts are ignored while the user is typing (inputs, textareas, selects,
 * contenteditable) unless the combo uses mod/ctrl/meta/alt or `allowInInputs`
 * is set. Single-key shortcuts are also ignored inside open dialogs and menus.
 */

export interface HotkeyOptions {
  enabled?: boolean
  /** Also fire while focus is in a text field. Defaults to true for mod/ctrl/meta/alt combos. */
  allowInInputs?: boolean
  /** Call preventDefault() when the shortcut fires. Default true. */
  preventDefault?: boolean
}

interface Combo {
  key: string
  mod: boolean
  ctrl: boolean
  meta: boolean
  alt: boolean
  shift: boolean
}

const SEQUENCE_TIMEOUT_MS = 1000
const MODIFIER_KEYS = new Set(['shift', 'control', 'meta', 'alt', 'altgraph', 'capslock', 'os'])
const KEY_ALIASES: Record<string, string> = {
  esc: 'escape',
  space: ' ',
  return: 'enter',
  del: 'delete',
}
const NON_TEXT_INPUT_TYPES = new Set([
  'checkbox',
  'radio',
  'button',
  'submit',
  'reset',
  'range',
  'color',
  'file',
  'image',
])

function parseCombo(combo: string): Combo {
  // "shift++" or "+" alone would be ambiguous; we only support named keys, so a
  // trailing "+" means the plus key itself.
  const parts = combo.endsWith('++') ? [...combo.slice(0, -2).split('+'), '+'] : combo.split('+')
  const result: Combo = { key: '', mod: false, ctrl: false, meta: false, alt: false, shift: false }
  for (const raw of parts) {
    const part = raw.toLowerCase()
    if (part === 'mod') result.mod = true
    else if (part === 'ctrl' || part === 'control') result.ctrl = true
    else if (part === 'meta' || part === 'cmd') result.meta = true
    else if (part === 'alt' || part === 'option') result.alt = true
    else if (part === 'shift') result.shift = true
    else result.key = KEY_ALIASES[part] ?? part
  }
  return result
}

export function parseKeys(keys: string): Combo[] {
  return keys.trim().split(/\s+/).map(parseCombo)
}

/** Printable, non-alphanumeric keys like "?" need Shift on many layouts — ignore Shift for them. */
const isSymbolKey = (key: string) => key.length === 1 && !/[a-z0-9]/i.test(key)

function comboMatches(combo: Combo, event: KeyboardEvent, mac: boolean): boolean {
  if (event.key.toLowerCase() !== combo.key) return false
  const wantMeta = combo.meta || (combo.mod && mac)
  const wantCtrl = combo.ctrl || (combo.mod && !mac)
  if (event.metaKey !== wantMeta || event.ctrlKey !== wantCtrl || event.altKey !== combo.alt)
    return false
  return isSymbolKey(combo.key) || event.shiftKey === combo.shift
}

export function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  if (target.isContentEditable) return true
  if (target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement) return true
  if (target instanceof HTMLInputElement) return !NON_TEXT_INPUT_TYPES.has(target.type)
  return false
}

const isInsideOverlay = (target: EventTarget | null) =>
  target instanceof Element &&
  target.closest('[role="dialog"],[role="alertdialog"],[role="menu"],[role="listbox"]') !== null

/**
 * Returns a stateful matcher: feed it every keydown, it returns true when the
 * full combo/sequence has just been completed.
 */
export function createHotkeyMatcher(
  keys: string,
  options: Pick<HotkeyOptions, 'allowInInputs'> & { mac?: boolean } = {},
): (event: KeyboardEvent) => boolean {
  const sequence = parseKeys(keys)
  const mac = options.mac ?? isMac
  const hasModifier = sequence.some((c) => c.mod || c.ctrl || c.meta || c.alt)
  const allowInInputs = options.allowInInputs ?? hasModifier
  let index = 0
  let lastAt = 0

  return (event) => {
    if (event.defaultPrevented || event.isComposing || event.repeat) return false
    if (MODIFIER_KEYS.has(event.key.toLowerCase())) return false
    if (!allowInInputs && isTypingTarget(event.target)) return false
    if (!hasModifier && isInsideOverlay(event.target)) return false

    if (index > 0 && event.timeStamp - lastAt > SEQUENCE_TIMEOUT_MS) index = 0
    const expected = sequence[index]
    if (expected && comboMatches(expected, event, mac)) {
      index += 1
      lastAt = event.timeStamp
    } else {
      // Allow restarting a sequence mid-way ("g g m").
      const first = sequence[0]
      index = first && comboMatches(first, event, mac) ? 1 : 0
      lastAt = event.timeStamp
    }
    if (index === sequence.length) {
      index = 0
      return true
    }
    return false
  }
}

export function useHotkey(
  keys: string,
  handler: (event: KeyboardEvent) => void,
  { enabled = true, allowInInputs, preventDefault = true }: HotkeyOptions = {},
): void {
  const onHotkey = useEffectEvent(handler)

  useEffect(() => {
    if (!enabled) return
    const matches = createHotkeyMatcher(keys, { allowInInputs })
    const onKeyDown = (event: KeyboardEvent) => {
      if (!matches(event)) return
      if (preventDefault) event.preventDefault()
      onHotkey(event)
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [keys, enabled, allowInInputs, preventDefault])
}

const DISPLAY_NAMES: Record<string, [mac: string, other: string]> = {
  mod: ['⌘', 'Ctrl'],
  meta: ['⌘', 'Win'],
  ctrl: ['⌃', 'Ctrl'],
  alt: ['⌥', 'Alt'],
  shift: ['⇧', 'Shift'],
  enter: ['↵', 'Enter'],
  escape: ['Esc', 'Esc'],
  backspace: ['⌫', 'Backspace'],
  delete: ['⌦', 'Del'],
  arrowup: ['↑', '↑'],
  arrowdown: ['↓', '↓'],
  arrowleft: ['←', '←'],
  arrowright: ['→', '→'],
  ' ': ['Space', 'Space'],
  tab: ['⇥', 'Tab'],
}

/** "mod+k" → [["⌘","K"]] on macOS; "g m" → [["G"],["M"]]. */
export function formatKeys(keys: string, mac: boolean = isMac): string[][] {
  return parseKeys(keys).map((combo) => {
    const names: string[] = []
    const push = (id: string) => {
      const display = DISPLAY_NAMES[id]
      names.push(display ? display[mac ? 0 : 1] : id.length === 1 ? id.toUpperCase() : id)
    }
    if (combo.ctrl) push('ctrl')
    if (combo.alt) push('alt')
    if (combo.shift) push('shift')
    if (combo.meta) push('meta')
    if (combo.mod) push('mod')
    push(combo.key)
    return names
  })
}
