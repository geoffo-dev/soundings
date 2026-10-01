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
    expect(field).toHaveValue(`Thanks @[Carol Díaz](user:${USERS.carol}) `)
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
    expect(submitted).toEqual([]) // Enter chose a person; it didn't post
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
    expect(chips[1]).toHaveClass('text-accent') // you
    expect(screen.getAllByRole('link')).toHaveLength(1)
  })

  it('leave other "@" text alone', () => {
    const { container } = render(<Markdown>{'Email ada@example.com or @ada'}</Markdown>)
    expect(container.querySelectorAll('[data-mention]')).toHaveLength(0)
    expect(container).toHaveTextContent('Email ada@example.com or @ada')
  })
})
