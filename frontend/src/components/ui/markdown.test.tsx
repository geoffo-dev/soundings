import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { Markdown, safeMarkdownUrl } from '@/components/ui/markdown'

describe('safeMarkdownUrl (the same allow-list as the exported PDF)', () => {
  it.each([
    'https://example.org/a?b=c',
    'http://example.org',
    'mailto:team@example.org',
    'HTTPS://X.Y',
  ])('keeps %s', (url) => expect(safeMarkdownUrl(url)).toBe(url))

  it.each([
    '/ideas/CUST-1',
    '//evil.example/path',
    '#section',
    'relative/path',
    'javascript:alert(1)',
    'data:text/html,hi',
    'tel:+441234',
    'irc://irc.example',
    'xmpp:someone@example.org',
    'java%09script:alert(1)',
    '',
  ])('drops %s', (url) => expect(safeMarkdownUrl(url)).toBeNull())
})

describe('Markdown links', () => {
  it('renders allowed links as links and the rest as plain text', () => {
    render(
      <Markdown>
        {
          '[web](https://example.org) [mail](mailto:a@example.org) [rel](//evil.example) [tel](tel:123) [js](javascript:alert(1))'
        }
      </Markdown>,
    )
    expect(screen.getByRole('link', { name: 'web' })).toHaveAttribute('href', 'https://example.org')
    expect(screen.getByRole('link', { name: 'web' })).toHaveAttribute('target', '_blank')
    expect(screen.getByRole('link', { name: 'mail' })).toHaveAttribute(
      'href',
      'mailto:a@example.org',
    )
    for (const name of ['rel', 'tel', 'js']) {
      expect(screen.queryByRole('link', { name })).toBeNull()
      expect(screen.getByText(name)).toBeInTheDocument()
    }
  })

  it('shows an image with an unsafe source as its alt text, never a link or an image', () => {
    const { container } = render(<Markdown>{'![a chart](//evil.example/x.png)'}</Markdown>)
    expect(container.querySelector('img')).toBeNull()
    expect(screen.queryByRole('link')).toBeNull()
    expect(screen.getByText('a chart')).toBeInTheDocument()
  })

  it('keeps nested section headings one level down and visibly headings, as in the PDF', () => {
    render(<Markdown nested>{'# One\n\n## Two\n\n### Three\n\n#### Four\n\n##### Five'}</Markdown>)
    expect(screen.getByRole('heading', { level: 3, name: 'One' })).toHaveClass('font-semibold')
    expect(screen.getByRole('heading', { level: 3, name: 'Two' })).toHaveClass('font-semibold')
    expect(screen.getByRole('heading', { level: 4, name: 'Three' })).toHaveClass('font-semibold')
    expect(screen.getByRole('heading', { level: 5, name: 'Four' })).toHaveClass('font-semibold')
    expect(screen.getByRole('heading', { level: 6, name: 'Five' })).toHaveClass('font-semibold')
  })
})
