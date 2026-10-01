import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/api/errors'
import type { ProposalSection, ProposalSectionKey } from '@/api/types'

import { AUTOSAVE_DELAY_MS, ProposalSaveStore, summarise, type SaveFn } from './save-store'

const section = (
  key: ProposalSectionKey,
  body_md: string,
  version = 1,
  by: string | null = null,
): ProposalSection => ({
  key,
  title: key,
  prompt: '',
  body_md,
  version,
  updated_at: '2026-10-01T10:00:00Z',
  updated_by: by ? { id: by, display_name: by, avatar_url: null, initials: 'X' } : null,
})

function conflict(current: ProposalSection) {
  return new ApiError({
    status: 409,
    code: 'proposal_conflict',
    title: 'Conflict',
    problem: { code: 'proposal_conflict', current } as never,
  })
}

describe('ProposalSaveStore', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  function setup(save: SaveFn) {
    const onSaved = vi.fn()
    const store = new ProposalSaveStore(
      [section('summary', 'Hello', 3), section('problem', '', 1)],
      save,
      onSaved,
    )
    return { store, onSaved }
  }

  it('saves a section 800 ms after the last keystroke, from its version', async () => {
    const save = vi.fn<SaveFn>((key, body, base) => Promise.resolve(section(key, body, base + 1)))
    const { store, onSaved } = setup(save)
    store.edit('summary', 'Hello w')
    store.edit('summary', 'Hello world')
    expect(store.get('summary')?.status).toBe('dirty')
    await vi.advanceTimersByTimeAsync(AUTOSAVE_DELAY_MS - 1)
    expect(save).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(1)
    expect(save).toHaveBeenCalledTimes(1)
    expect(save).toHaveBeenCalledWith('summary', 'Hello world', 3, { keepalive: false })
    expect(store.get('summary')).toMatchObject({ status: 'saved', base: 4, saved: 'Hello world' })
    expect(onSaved).toHaveBeenCalledTimes(1)
  })

  it('typing back to the saved text needs no save', async () => {
    const save = vi.fn<SaveFn>()
    const { store } = setup(save)
    store.edit('summary', 'Hello!')
    store.edit('summary', 'Hello')
    expect(store.get('summary')?.status).toBe('saved')
    await vi.advanceTimersByTimeAsync(AUTOSAVE_DELAY_MS * 2)
    expect(save).not.toHaveBeenCalled()
  })

  it('keeps text typed during a save and saves it next, from the new version', async () => {
    let finish: (value: ProposalSection) => void = () => undefined
    const save = vi
      .fn<SaveFn>()
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            finish = resolve
          }),
      )
      .mockImplementation((key, body, base) => Promise.resolve(section(key, body, base + 1)))
    const { store } = setup(save)
    store.edit('summary', 'One')
    void store.flush()
    expect(store.get('summary')?.status).toBe('saving')
    store.edit('summary', 'One two')
    finish(section('summary', 'One', 4))
    await vi.advanceTimersByTimeAsync(0)
    expect(store.get('summary')).toMatchObject({ status: 'dirty', base: 4 })
    await vi.advanceTimersByTimeAsync(AUTOSAVE_DELAY_MS)
    expect(save).toHaveBeenLastCalledWith('summary', 'One two', 4, { keepalive: false })
    expect(store.get('summary')?.status).toBe('saved')
  })

  it('parks a conflicting section until the person chooses', async () => {
    const theirs = section('summary', 'Their text', 5, 'Priya')
    const save = vi
      .fn<SaveFn>()
      .mockRejectedValueOnce(conflict(theirs))
      .mockImplementation((key, body, base) => Promise.resolve(section(key, body, base + 1)))
    const { store } = setup(save)
    store.edit('summary', 'My text')
    await store.flush()
    expect(store.get('summary')).toMatchObject({ status: 'conflict', conflict: theirs })
    expect(summarise(store, null)).toEqual({ kind: 'conflict', count: 1 })
    // More typing doesn't save while the conflict is open.
    store.edit('summary', 'My text, longer')
    await vi.advanceTimersByTimeAsync(AUTOSAVE_DELAY_MS * 2)
    expect(save).toHaveBeenCalledTimes(1)

    await store.keepMine('summary')
    expect(save).toHaveBeenLastCalledWith('summary', 'My text, longer', 5, { keepalive: false })
    expect(store.get('summary')).toMatchObject({ status: 'saved', base: 6 })
  })

  it('"Use theirs" replaces the draft with their text and version', async () => {
    const theirs = section('summary', 'Their text', 5, 'Priya')
    const { store, onSaved } = setup(vi.fn<SaveFn>().mockRejectedValue(conflict(theirs)))
    store.edit('summary', 'Mine')
    await store.flush()
    store.takeTheirs('summary')
    expect(store.get('summary')).toMatchObject({
      status: 'saved',
      draft: 'Their text',
      base: 5,
      conflict: null,
    })
    expect(onSaved).toHaveBeenCalledWith(theirs)
  })

  it('reports other failures and retries when asked', async () => {
    const save = vi
      .fn<SaveFn>()
      .mockRejectedValueOnce(
        new ApiError({ status: 500, code: 'internal_error', title: 'Internal Server Error' }),
      )
      .mockImplementation((key, body, base) => Promise.resolve(section(key, body, base + 1)))
    const { store } = setup(save)
    store.edit('problem', 'Why')
    await store.flush()
    expect(store.get('problem')).toMatchObject({ status: 'error', draft: 'Why' })
    expect(store.hasUnsaved()).toBe(true)
    expect(summarise(store, null)).toEqual({ kind: 'unsaved', count: 1 })
    await store.saveNow('problem')
    expect(store.get('problem')?.status).toBe('saved')
    expect(store.hasUnsaved()).toBe(false)
  })

  it('takes newer server text only where nothing is unsaved', () => {
    const { store } = setup(vi.fn<SaveFn>())
    store.edit('problem', 'Local draft')
    store.receive([section('summary', 'Someone else', 4), section('problem', 'Theirs', 2)])
    expect(store.get('summary')).toMatchObject({ draft: 'Someone else', base: 4 })
    expect(store.get('problem')).toMatchObject({ draft: 'Local draft', base: 1 })
  })

  it('sends pending saves at once when the editor goes away', () => {
    const save = vi.fn<SaveFn>((key, body, base) => Promise.resolve(section(key, body, base + 1)))
    const { store } = setup(save)
    store.edit('summary', 'Leaving')
    store.dispose()
    expect(save).toHaveBeenCalledWith('summary', 'Leaving', 3, { keepalive: true })
  })
})
