import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'

import {
  SCORE_GUIDANCE_PLACEHOLDER,
  SegmentedControl,
  scoreOptions,
} from '@/components/ui/segmented-control'

function ScoreHarness({
  initial = null,
  onChange,
}: {
  initial?: string | null
  onChange?: (v: string) => void
}) {
  const [value, setValue] = useState<string | null>(initial)
  return (
    <SegmentedControl
      aria-label="Value"
      variant="accent"
      options={scoreOptions({ 4: 'Strong benefit, customers are asking for it' })}
      value={value}
      onValueChange={(next) => {
        setValue(next)
        onChange?.(next)
      }}
      guidancePlaceholder="Hover a score to see what it means"
    />
  )
}

const radio = (name: string) => screen.getByRole('radio', { name })

/**
 * Hold the key down while Radix moves focus (it does so in a timeout and only
 * selects while an arrow key is pressed), then release — like a real keypress.
 */
async function press(user: ReturnType<typeof userEvent.setup>, key: string) {
  await user.keyboard(`{${key}>}`)
  await new Promise((resolve) => setTimeout(resolve, 0))
  await user.keyboard(`{/${key}}`)
}
const guidance = () => document.querySelector('[data-slot="segmented-guidance"]')

describe('SegmentedControl', () => {
  it('renders a labelled radio group with one radio per option', () => {
    render(<ScoreHarness initial="2" />)
    expect(screen.getByRole('radiogroup', { name: 'Value' })).toBeInTheDocument()
    expect(screen.getAllByRole('radio')).toHaveLength(5)
    expect(radio('2')).toBeChecked()
    expect(radio('4')).toHaveAccessibleDescription(
      '4 · Strong benefit, customers are asking for it',
    )
  })

  it('uses roving focus: one tab stop, arrow keys move and select', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(<ScoreHarness initial="2" onChange={onChange} />)

    await user.tab()
    expect(radio('2')).toHaveFocus()

    await press(user, 'ArrowRight')
    expect(radio('3')).toHaveFocus()
    expect(radio('3')).toBeChecked()

    await press(user, 'ArrowLeft')
    await press(user, 'ArrowLeft')
    expect(radio('1')).toHaveFocus()
    expect(radio('1')).toBeChecked()
    expect(onChange).toHaveBeenLastCalledWith('1')

    // No wrap-around at the ends.
    await press(user, 'ArrowLeft')
    expect(radio('1')).toHaveFocus()

    // Leaving the group takes a single Tab.
    await user.tab()
    expect(document.body).toHaveFocus()
  })

  it('jumps with End/Home and selects a score by typing its number', async () => {
    const user = userEvent.setup()
    render(<ScoreHarness initial="3" />)
    await user.tab()

    await press(user, 'End')
    expect(radio('5')).toHaveFocus()
    await press(user, 'Home')
    expect(radio('1')).toHaveFocus()

    await user.keyboard('4')
    expect(radio('4')).toBeChecked()
    expect(radio('4')).toHaveFocus()
  })

  it('shows guidance for the focused option, falling back to the selection', async () => {
    const user = userEvent.setup()
    render(<ScoreHarness />)
    expect(guidance()).toHaveTextContent('Hover a score to see what it means')

    await user.hover(radio('4'))
    expect(guidance()).toHaveTextContent('4 · Strong benefit, customers are asking for it')
    await user.unhover(radio('4'))
    expect(guidance()).toHaveTextContent('Hover a score to see what it means')

    await user.click(radio('2'))
    await press(user, 'ArrowRight')
    expect(guidance()).toHaveTextContent(/^3 · /)
  })

  it('says "Tap" instead of "Hover" on touch screens', () => {
    const coarse = (query: string) =>
      ({
        matches: query === '(pointer: coarse)',
        media: query,
        onchange: null,
        addEventListener: () => undefined,
        removeEventListener: () => undefined,
        addListener: () => undefined,
        removeListener: () => undefined,
        dispatchEvent: () => false,
      }) as MediaQueryList
    const options = scoreOptions()
    const { rerender } = render(
      <SegmentedControl
        aria-label="Value"
        options={options}
        value={null}
        onValueChange={() => undefined}
        guidancePlaceholder={SCORE_GUIDANCE_PLACEHOLDER}
      />,
    )
    expect(guidance()).toHaveTextContent(SCORE_GUIDANCE_PLACEHOLDER.pointer)
    vi.spyOn(window, 'matchMedia').mockImplementation(coarse)
    rerender(
      <SegmentedControl
        key="touch"
        aria-label="Value"
        options={options}
        value={null}
        onValueChange={() => undefined}
        guidancePlaceholder={SCORE_GUIDANCE_PLACEHOLDER}
      />,
    )
    expect(guidance()).toHaveTextContent(SCORE_GUIDANCE_PLACEHOLDER.touch)
  })
})
