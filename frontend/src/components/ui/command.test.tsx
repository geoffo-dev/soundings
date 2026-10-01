import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import {
  Command,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  useTopResult,
} from '@/components/ui/command'

interface Person {
  id: string
  name: string
  disabled?: boolean
}

/** A server-filtered picker: the parent swaps `people` when "the server" answers. */
function Picker({ people, onPick }: { people: Person[]; onPick: (id: string) => void }) {
  const highlight = useTopResult(people.filter((p) => !p.disabled).map((p) => p.id))
  return (
    <Command shouldFilter={false} {...highlight}>
      <CommandInput aria-label="People" />
      <CommandList aria-label="People" empty="No one matches">
        <CommandGroup>
          {people.map((person) => (
            <CommandItem
              key={person.id}
              value={person.id}
              disabled={person.disabled}
              onSelect={() => onPick(person.id)}
            >
              {person.name}
            </CommandItem>
          ))}
        </CommandGroup>
      </CommandList>
    </Command>
  )
}

const everyone: Person[] = [
  { id: 'alice', name: 'Alice' },
  { id: 'bob', name: 'Bob' },
  { id: 'kenji', name: 'Kenji' },
]
const selected = () => screen.getByRole('option', { selected: true })

describe('useTopResult', () => {
  it('highlights the top result when the results change, so Enter picks it', async () => {
    const user = userEvent.setup()
    const onPick = vi.fn()
    const { rerender } = render(<Picker people={everyone} onPick={onPick} />)
    expect(selected()).toHaveTextContent('Alice')

    await user.type(screen.getByRole('combobox'), 'Ken')
    rerender(<Picker people={[{ id: 'kenji', name: 'Kenji' }]} onPick={onPick} />)
    expect(selected()).toHaveTextContent('Kenji')
    await user.keyboard('{Enter}')
    expect(onPick).toHaveBeenCalledWith('kenji')
  })

  it('skips people who cannot be picked, and still follows the arrow keys', async () => {
    const user = userEvent.setup()
    render(
      <Picker
        people={[{ id: 'alice', name: 'Alice', disabled: true }, ...everyone.slice(1)]}
        onPick={vi.fn()}
      />,
    )
    expect(selected()).toHaveTextContent('Bob')
    await user.click(screen.getByRole('combobox'))
    await user.keyboard('{ArrowDown}')
    expect(selected()).toHaveTextContent('Kenji')
  })

  it('shows the empty message outside the listbox', () => {
    render(<Picker people={[]} onPick={vi.fn()} />)
    expect(screen.getByText('No one matches')).toBeInTheDocument()
    expect(screen.getByRole('listbox')).not.toHaveTextContent('No one matches')
  })
})

describe('Command in a form', () => {
  // jsdom isn't macOS, so "mod" is Ctrl.
  it('submits the form on Ctrl+Enter instead of picking the highlighted item', async () => {
    const user = userEvent.setup()
    const onPick = vi.fn()
    const onSubmit = vi.fn((event: Event) => event.preventDefault())
    render(
      <form onSubmit={(event) => onSubmit(event.nativeEvent)}>
        <Picker people={everyone} onPick={onPick} />
      </form>,
    )
    await user.click(screen.getByRole('combobox'))
    await user.keyboard('{Control>}{Enter}{/Control}')
    expect(onSubmit).toHaveBeenCalledTimes(1)
    expect(onPick).not.toHaveBeenCalled()

    await user.keyboard('{Enter}')
    expect(onPick).toHaveBeenCalledWith('alice')
  })
})
