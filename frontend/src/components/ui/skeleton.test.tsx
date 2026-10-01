import { act, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { SkeletonGroup } from '@/components/ui/skeleton'

describe('SkeletonGroup', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('says it is loading a moment after it appears, so the live region announces it', () => {
    render(<SkeletonGroup label="Loading ideas" />)
    const status = screen.getByRole('status')
    // Text a live region is created with isn't read out; quick loads stay silent.
    expect(status).toHaveTextContent(/^$/)
    act(() => {
      vi.advanceTimersByTime(300)
    })
    expect(status).toHaveTextContent('Loading ideas')
  })
})
