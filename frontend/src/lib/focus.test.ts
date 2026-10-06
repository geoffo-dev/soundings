import { afterEach, describe, expect, it } from 'vitest'

import { focusWhenRendered } from './focus'

const frame = () => new Promise<void>((resolve) => window.requestAnimationFrame(() => resolve()))

afterEach(() => {
  document.body.replaceChildren()
})

/** A dialog whose focus trap holds while it is mounted (as Radix's does), with its busy button. */
function trappingDialog(): { dialog: HTMLElement; busy: HTMLButtonElement; remove: () => void } {
  const dialog = document.createElement('div')
  dialog.dataset.slot = 'dialog-content'
  dialog.dataset.state = 'closed' // animating out
  const busy = document.createElement('button')
  busy.setAttribute('aria-disabled', 'true')
  dialog.append(busy)
  document.body.append(dialog)
  const trap = (event: FocusEvent) => {
    if (event.target instanceof Node && !dialog.contains(event.target)) busy.focus()
  }
  document.addEventListener('focusin', trap)
  busy.focus()
  return {
    dialog,
    busy,
    remove: () => {
      document.removeEventListener('focusin', trap)
      dialog.remove()
    },
  }
}

describe('focusWhenRendered', () => {
  it('focuses what the action produced', async () => {
    const target = document.createElement('button')
    document.body.append(target)
    focusWhenRendered(() => target)
    await frame()
    expect(document.activeElement).toBe(target)
  })

  it('tries again while a closing dialog’s focus trap pulls focus back to its busy button', async () => {
    const row = document.createElement('div')
    row.tabIndex = -1
    document.body.append(row)
    const { busy, remove } = trappingDialog()

    focusWhenRendered(() => row, { force: true })
    await frame()
    expect(document.activeElement).toBe(busy) // the trap won this frame
    await frame()
    remove() // the dialog has animated out
    await frame()
    await frame()
    expect(document.activeElement).toBe(row)
  })

  it('gives up after its frames when the dialog stays', async () => {
    const row = document.createElement('div')
    row.tabIndex = -1
    document.body.append(row)
    const { busy, remove } = trappingDialog()

    focusWhenRendered(() => row, { force: true, frames: 3 })
    for (let i = 0; i < 6; i++) await frame()
    expect(document.activeElement).toBe(busy)
    remove()
    await frame()
    expect(document.activeElement).not.toBe(row)
  })
})
