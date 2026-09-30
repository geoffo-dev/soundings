import { act, renderHook } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { registerCommands, useCommands, useRegisteredCommands } from '@/lib/command-registry'

describe('command registry', () => {
  it('lists groups while their page is mounted, in order', () => {
    const { result } = renderHook(() => useRegisteredCommands())
    let unregisterLate: () => void = () => undefined
    act(() => {
      unregisterLate = registerCommands({ id: 'late', heading: 'Late', actions: [], order: 5 })
    })
    const { unmount } = renderHook(() =>
      useCommands({
        id: 'idea',
        heading: 'CUST-12',
        actions: [{ id: 'evaluate', label: 'Evaluate', onSelect: () => undefined }],
      }),
    )
    const { result: after } = renderHook(() => useRegisteredCommands())
    expect(after.current.map((group) => group.id)).toEqual(['idea', 'late'])
    unmount()
    act(() => unregisterLate())
    expect(result.current).toEqual([])
  })

  it('runs the latest onSelect without re-registering', () => {
    const first = vi.fn()
    const second = vi.fn()
    const { rerender } = renderHook(
      ({ onSelect }: { onSelect: () => void }) =>
        useCommands({
          id: 'idea',
          heading: 'CUST-12',
          actions: [{ id: 'go', label: 'Go', onSelect }],
        }),
      { initialProps: { onSelect: first } },
    )
    rerender({ onSelect: second })
    const { result } = renderHook(() => useRegisteredCommands())
    result.current[0]?.actions[0]?.onSelect()
    expect(first).not.toHaveBeenCalled()
    expect(second).toHaveBeenCalledOnce()
  })
})
