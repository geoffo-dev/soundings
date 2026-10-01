import { QueryClientProvider, type QueryClient } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from 'vitest'

import { api } from '@/api/client'
import { createQueryClient } from '@/api/query'
import { Markdown } from '@/components/ui/markdown'
import { resetDb, USERS } from '@/mocks/db'
import { server } from '@/mocks/server'
import { endSession } from '@/mocks/session'

import { MarkdownEditor } from './markdown-editor'

let queryClient: QueryClient
let submitted: string[] = []

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
beforeEach(async () => {
  resetDb()
  localStorage.setItem('soundings-mock-latency', 'none')
  queryClient = createQueryClient()
  submitted = []
  await api.POST('/api/v1/auth/dev/login', { body: { user_id: USERS.alice } })
})
afterEach(() => {
  server.resetHandlers()
  endSession()
})
afterAll(() => server.close())

function Composer() {
  const [value, setValue] = useState('')
  return (
    <QueryClientProvider client={queryClient}>
      <MarkdownEditor
        label="Write a comment"
        value={value}
        onValueChange={setValue}
        onSubmit={() => submitted.push(value)}
        mentions={{ project: 'customer-innovation', excludeUserId: USERS.alice }}
      />
    </QueryClientProvider>
  )
}

describe('the mention picker', () => {
  it('opens on "@", filters by name, and inserts the token with Enter', async () => {
    const user = userEvent.setup()
    render(<Composer />)
    const field = screen.getByRole('textbox', { name: 'Write a comment' })
    await user.type(field, 'Thanks @car')
    const list = await screen.findByRole('listbox', { name: 'People to mention' })
    await waitFor(() => expect(list).toHaveTextContent('Carol Díaz'))
    expect(list).not.toHaveTextContent('Alice Anders') // not yourself
    expect(field).toHaveAttribute('aria-activedescendant')
    await user.keyboard('{Enter}')
    // The box shows the name; the stored text has the token.
    expect(field).toHaveValue('Thanks @Carol Díaz ')
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
    expect(submitted).toEqual([]) // Enter chose a person; it didn't post
    await user.keyboard('please{Control>}{Enter}{/Control}')
    expect(submitted).toEqual([`Thanks @[Carol Díaz](user:${USERS.carol}) please`])
  })

  it('tints real mentions, drops one that is edited, and Backspace removes a whole one', async () => {
    const user = userEvent.setup()
    const { container } = render(<Composer />)
    const field = screen.getByRole('textbox', { name: 'Write a comment' })
    await user.type(field, '@bo')
    await screen.findByRole('option', { name: /Bob Chen/ })
    await user.keyboard('{Enter}')
    expect(field).toHaveValue('@Bob Chen ')
    expect(container.querySelector(`[data-mention-tint="${USERS.bob}"]`)).toHaveTextContent(
      '@Bob Chen',
    )
    // The caret right after the name doesn't reopen the picker; Backspace removes it all.
    await user.keyboard('{Backspace}')
    expect(field).toHaveValue('@Bob Chen')
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
    await user.keyboard('{Backspace}')
    expect(field).toHaveValue('')
    expect(container.querySelector('[data-mention-tint]')).toBeNull()

    // Editing inside a name makes it plain text (no tint, no token).
    await user.type(field, '@bo')
    await screen.findByRole('option', { name: /Bob Chen/ })
    await user.keyboard('{Enter}{ArrowLeft}{ArrowLeft}x')
    expect(field).toHaveValue('@Bob Chexn ')
    expect(container.querySelector('[data-mention-tint]')).toBeNull()
    await user.keyboard('{Control>}{Enter}{/Control}')
    expect(submitted).toEqual(['@Bob Chexn '])
  })

  it('offers only people with a role in the project, and Esc closes it', async () => {
    const user = userEvent.setup()
    render(<Composer />)
    const field = screen.getByRole('textbox', { name: 'Write a comment' })
    await user.type(field, '@')
    const list = await screen.findByRole('listbox', { name: 'People to mention' })
    await waitFor(() => expect(list).toHaveTextContent('Bob Chen'))
    expect(list).not.toHaveTextContent('Ivan Petrov') // no role in Customer Innovation
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
    expect(field).toHaveValue('@')
  })

  it('stays closed inside an email address', async () => {
    const user = userEvent.setup()
    render(<Composer />)
    await user.type(screen.getByRole('textbox', { name: 'Write a comment' }), 'mail bob@exa')
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  })
})

describe('rendered mentions', () => {
  it('are name chips, never links to user:', () => {
    const { container } = render(
      <Markdown mentionSelfId={USERS.alice}>
        {`Hi @[Bob Chen](user:${USERS.bob}) and @[Alice Anders](user:${USERS.alice}), see [docs](https://example.com)`}
      </Markdown>,
    )
    const chips = container.querySelectorAll('[data-mention]')
    expect([...chips].map((chip) => chip.textContent)).toEqual(['@Bob Chen', '@Alice Anders'])
    expect(container.querySelector('a[href^="user:"]')).toBeNull()
    expect(container).toHaveTextContent('Hi @Bob Chen and @Alice Anders, see docs')
    expect(chips[1]).toHaveAttribute('data-mention-self') // you
    expect(chips[0]).not.toHaveAttribute('data-mention-self')
    expect(screen.getAllByRole('link')).toHaveLength(1)
  })

  it('only for the exact token: other spellings of a user: link are plain text', () => {
    const { container } = render(
      <Markdown>
        {[
          `@[CEO Jane](user:${USERS.bob} "t")`,
          `@[CEO Jane](<user:${USERS.bob}>)`,
          `@[CEO [x] Jane](user:${USERS.bob})`,
          `[Jane](user:${USERS.bob})`,
        ].join('\n\n')}
      </Markdown>,
    )
    expect(container.querySelectorAll('[data-mention]')).toHaveLength(0)
    expect(container.querySelectorAll('a')).toHaveLength(0)
    expect(container).toHaveTextContent('@CEO Jane @CEO Jane @CEO [x] Jane Jane')
  })

  it('leave other "@" text alone', () => {
    const { container } = render(<Markdown>{'Email ada@example.com or @ada'}</Markdown>)
    expect(container.querySelectorAll('[data-mention]')).toHaveLength(0)
    expect(container).toHaveTextContent('Email ada@example.com or @ada')
  })
})
