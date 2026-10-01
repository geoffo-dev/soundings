import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it } from 'vitest'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Sheet,
  SheetBody,
  SheetContent,
  SheetHeader,
  SheetTitle,
  useSideSheetOpen,
} from '@/components/ui/sheet'
import { ariaKeys } from '@/components/ui/kbd'
import { focusRow, ROW_ID_ATTRIBUTE } from '@/lib/return-to-row'

function OpenFlag() {
  return <output aria-label="Sheet open">{String(useSideSheetOpen())}</output>
}

function Harness() {
  const [open, setOpen] = useState(false)
  return (
    <>
      <Button onClick={() => setOpen(true)}>Open Bob</Button>
      <OpenFlag />
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent aria-describedby={undefined}>
          <SheetHeader>
            <SheetTitle>Bob Chen</SheetTitle>
          </SheetHeader>
          <SheetBody>
            <Input aria-label="Name" defaultValue="Bob Chen" />
          </SheetBody>
        </SheetContent>
      </Sheet>
    </>
  )
}

describe('SheetContent', () => {
  it('opens with focus on the sheet, not its first field', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    expect(screen.getByRole('status', { name: 'Sheet open', hidden: true })).toHaveTextContent(
      'false',
    )
    await user.click(screen.getByRole('button', { name: 'Open Bob' }))
    const sheet = await screen.findByRole('dialog', { name: 'Bob Chen' })
    await waitFor(() => expect(sheet).toHaveFocus())
    expect(screen.getByRole('textbox', { name: 'Name' })).not.toHaveFocus()
    // The toaster moves up while it is open.
    expect(screen.getByRole('status', { name: 'Sheet open', hidden: true })).toHaveTextContent(
      'true',
    )

    await user.keyboard('{Tab}')
    expect(screen.getByRole('textbox', { name: 'Name' })).toHaveFocus()
    await user.keyboard('{Escape}')
    await waitFor(() => expect(screen.getByRole('button', { name: 'Open Bob' })).toHaveFocus())
    expect(screen.getByRole('status', { name: 'Sheet open', hidden: true })).toHaveTextContent(
      'false',
    )
  })
})

describe('focusRow', () => {
  it('focuses the rendered row with that id, and says when there is none', () => {
    render(
      <ul>
        <li>
          <a href="#a" {...{ [ROW_ID_ATTRIBUTE]: 'a' }}>
            Alice
          </a>
        </li>
        <li>
          <a href="#b" {...{ [ROW_ID_ATTRIBUTE]: 'b' }}>
            Bob
          </a>
        </li>
      </ul>,
    )
    expect(focusRow('b')).toBe(true)
    expect(screen.getByRole('link', { name: 'Bob' })).toHaveFocus()
    expect(focusRow('c')).toBe(false)
  })
})

describe('ariaKeys', () => {
  it('spells shortcuts for aria-keyshortcuts', () => {
    expect(ariaKeys('mod+enter')).toBe('Control+Enter Meta+Enter')
    expect(ariaKeys('mod+s')).toBe('Control+S Meta+S')
    expect(ariaKeys('e')).toBe('E')
  })
})
