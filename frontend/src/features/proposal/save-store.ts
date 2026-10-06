import { useSyncExternalStore } from 'react'

import { hasErrorCode, isApiError, type ApiError } from '@/api/errors'
import type { ProposalSection, ProposalSectionKey } from '@/api/types'

/**
 * Autosave for the proposal editor (contract-phase4 §3.2). One entry per
 * section: the text being edited (`draft`), the text and version it is based
 * on (`saved`, `base`) and where its save is. A section saves on its own,
 * 800 ms after the last keystroke (or at once with ⌘S), one request at a time;
 * a save from an older version gets 409 `proposal_conflict`, which parks the
 * section until the person chooses theirs or keeps theirs ("Keep mine" saves
 * again from `current.version`). Nothing is ever overwritten silently.
 *
 * Newer server text (a refetch after someone else saved) replaces a section
 * only while it has no unsaved changes here.
 */
export type SaveStatus = 'saved' | 'dirty' | 'saving' | 'error' | 'conflict'

export interface SectionSaveState {
  draft: string
  /** The last text the server confirmed (what `base` is the version of). */
  saved: string
  base: number
  status: SaveStatus
  /** 409 proposal_conflict: the section as someone else saved it. */
  conflict: ProposalSection | null
  error: ApiError | null
  /** When this tab last saved the section. */
  savedAt: string | null
}

export type SaveFn = (
  key: ProposalSectionKey,
  bodyMd: string,
  baseVersion: number,
  options: { keepalive: boolean },
) => Promise<ProposalSection>

export const AUTOSAVE_DELAY_MS = 800

export class ProposalSaveStore {
  private sections = new Map<ProposalSectionKey, SectionSaveState>()
  private timers = new Map<ProposalSectionKey, ReturnType<typeof setTimeout>>()
  private inflight = new Map<ProposalSectionKey, Promise<void>>()
  private listeners = new Set<() => void>()
  private version = 0
  private disposed = false

  private readonly save: SaveFn
  private readonly onSaved: (section: ProposalSection) => void

  constructor(
    sections: readonly ProposalSection[],
    save: SaveFn,
    onSaved: (section: ProposalSection) => void,
  ) {
    this.save = save
    this.onSaved = onSaved
    for (const section of sections) {
      this.sections.set(section.key, {
        draft: section.body_md,
        saved: section.body_md,
        base: section.version,
        status: 'saved',
        conflict: null,
        error: null,
        savedAt: null,
      })
    }
  }

  subscribe = (listener: () => void) => {
    this.listeners.add(listener)
    return () => {
      this.listeners.delete(listener)
    }
  }

  /** Bumps on every change (for whole-editor summaries). */
  getVersion = () => this.version

  get(key: ProposalSectionKey): SectionSaveState | undefined {
    return this.sections.get(key)
  }

  all(): [ProposalSectionKey, SectionSaveState][] {
    return [...this.sections.entries()]
  }

  private set(key: ProposalSectionKey, patch: Partial<SectionSaveState>) {
    const current = this.sections.get(key)
    if (!current) return
    this.sections.set(key, { ...current, ...patch })
    this.version += 1
    this.listeners.forEach((listener) => listener())
  }

  /** Someone typed. */
  edit(key: ProposalSectionKey, text: string): void {
    const current = this.sections.get(key)
    if (!current || current.draft === text) return
    let status = current.status
    if (status === 'saved' || status === 'dirty' || status === 'error') {
      status = text === current.saved ? 'saved' : 'dirty'
    }
    this.set(key, { draft: text, status, error: null })
    if (status === 'dirty') this.schedule(key)
    else this.cancel(key)
  }

  private schedule(key: ProposalSectionKey) {
    this.cancel(key)
    this.timers.set(
      key,
      setTimeout(() => void this.saveNow(key), AUTOSAVE_DELAY_MS),
    )
  }

  private cancel(key: ProposalSectionKey) {
    const timer = this.timers.get(key)
    if (timer !== undefined) clearTimeout(timer)
    this.timers.delete(key)
  }

  /** Saves one section now (⌘S, Retry, the debounce). */
  async saveNow(key: ProposalSectionKey, { keepalive = false } = {}): Promise<void> {
    this.cancel(key)
    const current = this.sections.get(key)
    if (!current || current.status === 'saving' || current.status === 'conflict') return
    if (current.draft === current.saved) {
      if (current.status !== 'saved') this.set(key, { status: 'saved', error: null })
      return
    }
    const text = current.draft
    this.set(key, { status: 'saving', error: null })
    const done = this.send(key, text, current.base, keepalive)
    this.inflight.set(key, done)
    try {
      await done
    } finally {
      if (this.inflight.get(key) === done) this.inflight.delete(key)
    }
  }

  private async send(
    key: ProposalSectionKey,
    text: string,
    base: number,
    keepalive: boolean,
  ): Promise<void> {
    try {
      const section = await this.save(key, text, base, { keepalive })
      this.onSaved(section)
      const latest = this.sections.get(key)
      if (!latest) return
      const changedSince = latest.draft !== section.body_md
      this.set(key, {
        saved: section.body_md,
        base: section.version,
        status: changedSince ? 'dirty' : 'saved',
        savedAt: new Date().toISOString(),
      })
      // Typed while saving: save that too.
      if (changedSince && !this.disposed) this.schedule(key)
      else if (changedSince) void this.saveNow(key, { keepalive })
    } catch (error) {
      if (hasErrorCode(error, 'proposal_conflict')) {
        const current = (error.problem as { current?: ProposalSection | null } | undefined)?.current
        if (current) {
          this.set(key, { status: 'conflict', conflict: current, error: null })
          return
        }
      }
      this.set(key, { status: 'error', error: isApiError(error) ? error : null })
    }
  }

  /**
   * Waits until the section's typing is on the server: its waiting autosave is
   * sent now and a save in flight finishes (accepting a suggestion asks about
   * unsaved text only when there really is some). Ends saved, or with the
   * error or conflict that stopped it.
   */
  async settle(key: ProposalSectionKey): Promise<void> {
    for (let round = 0; round < 5; round++) {
      const status = this.sections.get(key)?.status
      if (status === 'saving') await this.inflight.get(key)
      else if (status === 'dirty') await this.saveNow(key)
      else return
    }
  }

  /** Every section with unsaved text, now (⌘S, leaving the tab). */
  async flush({ keepalive = false } = {}): Promise<void> {
    const keys = this.all()
      .filter(([, state]) => state.status === 'dirty')
      .map(([key]) => key)
    await Promise.all(keys.map((key) => this.saveNow(key, { keepalive })))
  }

  /** "Use theirs": their text replaces yours (yours is gone). */
  takeTheirs(key: ProposalSectionKey): void {
    const state = this.sections.get(key)
    if (!state?.conflict) return
    const theirs = state.conflict
    this.onSaved(theirs)
    this.set(key, {
      draft: theirs.body_md,
      saved: theirs.body_md,
      base: theirs.version,
      status: 'saved',
      conflict: null,
      error: null,
    })
  }

  /** "Keep mine": save yours over theirs, from their version. */
  keepMine(key: ProposalSectionKey): Promise<void> {
    const state = this.sections.get(key)
    if (!state?.conflict) return Promise.resolve()
    const theirs = state.conflict
    this.onSaved(theirs)
    this.set(key, {
      saved: theirs.body_md,
      base: theirs.version,
      status: state.draft === theirs.body_md ? 'saved' : 'dirty',
      conflict: null,
    })
    return this.saveNow(key)
  }

  /**
   * Accepting a suggestion (contract-phase5 §3.4) is about to replace the
   * section: its waiting autosave must not race it. `releaseSave` re-arms the
   * autosave if the accept didn't happen.
   */
  holdSave(key: ProposalSectionKey): void {
    this.cancel(key)
  }

  releaseSave(key: ProposalSectionKey): void {
    if (this.sections.get(key)?.status === 'dirty' && !this.disposed) this.schedule(key)
  }

  /** The server saved this section (an accepted suggestion): it replaces the text here. */
  replace(section: ProposalSection): void {
    this.cancel(section.key)
    if (!this.sections.has(section.key)) return
    this.onSaved(section)
    this.set(section.key, {
      draft: section.body_md,
      saved: section.body_md,
      base: section.version,
      status: 'saved',
      conflict: null,
      error: null,
      savedAt: new Date().toISOString(),
    })
  }

  /** Newer text from the server (a refetch): taken only where nothing is unsaved here. */
  receive(sections: readonly ProposalSection[]): void {
    for (const section of sections) {
      const state = this.sections.get(section.key)
      if (!state || section.version <= state.base) continue
      if (state.status === 'saved') {
        this.set(section.key, {
          draft: section.body_md,
          saved: section.body_md,
          base: section.version,
        })
      }
      // With unsaved changes, the next save meets the conflict and asks.
    }
  }

  /** True while something isn't on the server yet (the leave warning). */
  hasUnsaved(): boolean {
    return this.all().some(([, state]) => state.status !== 'saved')
  }

  /** The editor (re)mounted (StrictMode mounts twice). */
  resume(): void {
    this.disposed = false
  }

  /** The tab is going away: send what is pending now instead of dropping it. */
  dispose(): void {
    this.disposed = true
    for (const key of [...this.timers.keys()]) void this.saveNow(key, { keepalive: true })
  }
}

/** One section's save state; re-renders only when the store changes. */
export function useSectionSave(store: ProposalSaveStore, key: ProposalSectionKey) {
  return useSyncExternalStore(store.subscribe, () => store.get(key))
}

export type EditorSaveSummary =
  | { kind: 'saved'; at: string | null }
  | { kind: 'saving' }
  | { kind: 'unsaved'; count: number }
  | { kind: 'conflict'; count: number }

/** The whole editor's "Saving… / Saved 10:42 / Not saved" line. */
export function summarise(store: ProposalSaveStore, initialAt: string | null): EditorSaveSummary {
  const states = store.all().map(([, state]) => state)
  const conflicts = states.filter((state) => state.status === 'conflict').length
  if (conflicts) return { kind: 'conflict', count: conflicts }
  const failed = states.filter((state) => state.status === 'error').length
  if (failed) return { kind: 'unsaved', count: failed }
  if (states.some((state) => state.status === 'saving' || state.status === 'dirty')) {
    return { kind: 'saving' }
  }
  const latest = states.reduce<string | null>(
    (max, state) => (state.savedAt && (!max || state.savedAt > max) ? state.savedAt : max),
    null,
  )
  return { kind: 'saved', at: latest ?? initialAt }
}

export function useEditorSaveSummary(
  store: ProposalSaveStore,
  initialAt: string | null,
): EditorSaveSummary {
  useSyncExternalStore(store.subscribe, store.getVersion)
  return summarise(store, initialAt)
}
