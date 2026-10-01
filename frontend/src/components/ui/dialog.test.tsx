import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it } from 'vitest'

import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'

/** A dialog opened from code (a shortcut, a menu item): no Radix Trigger. */
function Harness({ fromMenu = false }: { fromMenu?: boolean }) {
  const [open, setOpen] = useState(false)
  return (
    <>
      {fromMenu ? (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button>More</Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent>
            <DropdownMenuItem onSelect={() => setOpen(true)}>Delete…</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      ) : (
        <Button onClick={() => setOpen(true)}>Invite</Button>
      )}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogTitle>Dialog</DialogTitle>
          <DialogDescription>Opened from code.</DialogDescription>
          {/* Like the status picker: a field that takes focus as the dialog renders. */}
          {/* eslint-disable-next-line jsx-a11y/no-autofocus */}
          <input aria-label="Field" autoFocus />
        </DialogContent>
      </Dialog>
    </>
  )
}

describe('DialogContent focus return', () => {
  it('goes back to what had focus when it opened', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    await user.click(screen.getByRole('button', { name: 'Invite' }))
    await waitFor(() => expect(screen.getByRole('textbox', { name: 'Field' })).toHaveFocus())

    await user.keyboard('{Escape}')
    await waitFor(() => expect(screen.getByRole('button', { name: 'Invite' })).toHaveFocus())
  })

  it('goes back to the menu button when opened from a menu item', async () => {
    const user = userEvent.setup()
    render(<Harness fromMenu />)
    await user.click(screen.getByRole('button', { name: 'More' }))
    await user.click(await screen.findByRole('menuitem', { name: 'Delete…' }))
    await waitFor(() => expect(screen.getByRole('textbox', { name: 'Field' })).toHaveFocus())

    await user.keyboard('{Escape}')
    await waitFor(() => expect(screen.getByRole('button', { name: 'More' })).toHaveFocus())
  })
})
