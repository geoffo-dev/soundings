import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { SourceList } from './sources'

describe('SourceList', () => {
  it('lists sources under “Cited by AI, not checked” as safe links with their host', () => {
    render(
      <SourceList
        numbered
        sources={[
          { title: 'A review', url: 'https://example.org/review', host: 'example.org' },
          // The host shown is the browser's reading of the URL, not what was sent.
          { title: 'Look-alike', url: 'https://xn--pple-43d.example/x', host: 'apple.example' },
          { title: 'Script', url: 'javascript:alert(1)', host: 'evil.example' },
        ]}
      />,
    )
    const list = screen.getByRole('list', { name: 'Cited by AI, not checked' })
    expect(list.tagName).toBe('OL')
    const link = within(list).getByRole('link', { name: /A review/ })
    expect(link).toHaveAttribute('href', 'https://example.org/review')
    expect(link).toHaveAttribute('rel', 'noopener noreferrer nofollow')
    expect(link).toHaveAttribute('target', '_blank')
    expect(within(list).getByText('xn--pple-43d.example')).toBeInTheDocument()
    expect(within(list).queryByText('apple.example')).toBeNull()
    expect(within(list).queryByRole('link', { name: /Script/ })).toBeNull()
    expect(within(list).getByText('Script')).toBeInTheDocument()
  })

  it('renders nothing without sources, and a compact labelled line for criteria', () => {
    const { container, rerender } = render(<SourceList sources={[]} />)
    expect(container).toBeEmptyDOMElement()
    rerender(
      <SourceList
        compact
        sources={[{ title: 'One', url: 'https://a.example/', host: 'a.example' }]}
      />,
    )
    expect(
      screen.getByRole('list', { name: 'Sources cited by AI, not checked' }),
    ).toBeInTheDocument()
  })
})
