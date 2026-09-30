import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { CommandPalette, type CommandGroupData } from '@/components/ui/command-palette'

const action = (id: string, label: string) => ({ id, label, onSelect: () => undefined })
const project = action('project-green', 'Sustainability')
const idea = action('idea-green-8', 'Supplier sustainability questionnaire')
const otherIdea = action('idea-green-2', 'Solar panels on the warehouse')

/**
 * Server search results (`pending` while they belong to an earlier query) above the
 * local ones, like the app's palette.
 */
function Palette({
  search,
  ideas,
  pending = false,
  local = [project],
}: {
  search: string
  ideas: CommandGroupData['actions']
  pending?: boolean
  local?: CommandGroupData['actions']
}) {
  return (
    <CommandPalette
      open
      onOpenChange={() => undefined}
      search={search}
      onSearchChange={() => undefined}
      shouldFilter={false}
      groups={[
        { heading: 'Ideas', actions: ideas, pending },
        { heading: 'Go to', actions: local },
      ]}
    />
  )
}

const selected = () => screen.getByRole('option', { selected: true })

describe('CommandPalette highlight', () => {
  it('stays on what you see when server results arrive late', () => {
    const { rerender } = render(<Palette search="sustainab" ideas={[]} />)
    expect(selected()).toHaveTextContent('Sustainability')

    rerender(<Palette search="sustainab" ideas={[idea]} />)
    expect(selected()).toHaveTextContent('Sustainability')
  })

  it('prefers a current result to one that is about to be replaced', () => {
    const { rerender } = render(<Palette search="sus" ideas={[otherIdea]} pending />)
    expect(selected()).toHaveTextContent('Sustainability')

    rerender(<Palette search="sus" ideas={[idea]} />)
    expect(selected()).toHaveTextContent('Sustainability')
  })

  it('follows the best match while only earlier results are shown', () => {
    const { rerender } = render(<Palette search="supp" ideas={[otherIdea]} pending local={[]} />)
    expect(selected()).toHaveTextContent('Solar panels on the warehouse')

    rerender(<Palette search="supp" ideas={[idea, otherIdea]} local={[]} />)
    expect(selected()).toHaveTextContent('Supplier sustainability questionnaire')
  })

  it('moves to the first result when the query changes, and keeps a picked one', async () => {
    const user = userEvent.setup()
    const { rerender } = render(<Palette search="s" ideas={[idea]} />)
    expect(selected()).toHaveTextContent('Supplier sustainability questionnaire')

    await user.keyboard('{ArrowDown}')
    expect(selected()).toHaveTextContent('Sustainability')
    rerender(<Palette search="s" ideas={[otherIdea, idea]} />)
    expect(selected()).toHaveTextContent('Sustainability')

    rerender(<Palette search="su" ideas={[otherIdea, idea]} />)
    expect(selected()).toHaveTextContent('Solar panels on the warehouse')
  })
})

describe('CommandPalette with local filtering', () => {
  it('highlights the first match as you type', async () => {
    const user = userEvent.setup()
    render(
      <CommandPalette
        open
        onOpenChange={() => undefined}
        groups={[
          {
            heading: 'Actions',
            actions: [action('a', 'New idea'), action('b', 'My work'), action('c', 'Settings')],
          },
        ]}
      />,
    )
    expect(selected()).toHaveTextContent('New idea')
    await user.keyboard('sett')
    expect(selected()).toHaveTextContent('Settings')
    await user.keyboard('{Backspace>4/}')
    expect(selected()).toHaveTextContent('New idea')
  })
})
