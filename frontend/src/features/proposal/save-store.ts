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
export type SaveStatus = 'saved' | 'dirty' | 'saving' | 'error' | 'conflict' | 'removed'

export interface SectionSaveState {
  /** The section's title (kept for a section removed from the template meanwhile). */
  title: string
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

/**
 * Phase 8 (contract-phase8 §2.7): text typed into a section that was removed from the
 * template meanwhile (its save answers 404, or a refetch no longer lists it) is kept
 * as a local draft (`keep`) and never saved again, until the person discards it.
 */
export interface RemovedSectionKeeper {
  keep: (key: ProposalSectionKey, title: string, text: string) => void
  forget: (key: ProposalSectionKey) => void
  /**
   * A save answered 404: the template changed under the editor, so the proposal is read
   * again (the removed section leaves the editor; `receive` then keeps its text).
   */
  refresh?: () => void
}

const NO_KEEPER: RemovedSectionKeeper = { keep: () => undefined, forget: () => undefined }

export class ProposalSaveStore {
  private sections = new Map<ProposalSectionKey, SectionSaveState>()
  private timers = new Map<ProposalSectionKey, ReturnType<typeof setTimeout>>()
  private inflight = new Map<ProposalSectionKey, Promise<void>>()
  private listeners = new Set<() => void>()
  private version = 0
  private disposed = false

  private readonly save: SaveFn
  private readonly onSaved: (section: ProposalSection) => void
  private readonly keeper: RemovedSectionKeeper

  constructor(
    sections: readonly ProposalSection[],
    save: SaveFn,
    onSaved: (section: ProposalSection) => void,
    keeper: RemovedSectionKeeper = NO_KEEPER,
  ) {
    this.save = save
    this.onSaved = onSaved
    this.keeper = keeper
    for (const section of sections) this.sections.set(section.key, this.fromServer(section))
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
    if (current.status === 'removed') {
      // Kept locally only: the section no longer exists on the server.
      this.set(key, { draft: text })
      this.keeper.keep(key, current.title, text)
      return
    }
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
    if (
      !current ||
      current.status === 'saving' ||
      current.status === 'conflict' ||
      current.status === 'removed'
    ) {
      return
    }
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
      // Phase 8: the section was removed from the template while you typed.
      if (isApiError(error) && error.status === 404) {
        this.markRemoved(key)
        this.keeper.refresh?.()
        return
      }
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

  private markRemoved(key: ProposalSectionKey) {
    const state = this.sections.get(key)
    if (!state) return
    this.cancel(key)
    this.set(key, { status: 'removed', conflict: null, error: null })
    this.keeper.keep(key, state.title, state.draft)
  }

  /** A section's entry as the server has it (saved, nothing typed here). */
  private fromServer(section: ProposalSection): SectionSaveState {
    return {
      title: section.title,
      draft: section.body_md,
      saved: section.body_md,
      base: section.version,
      status: 'saved',
      conflict: null,
      error: null,
      savedAt: null,
    }
  }

  /** Text kept from earlier (a local draft of a removed section): shown until discarded. */
  restoreKept(key: ProposalSectionKey, title: string, text: string): void {
    if (this.sections.get(key)?.status === 'removed' || !text) return
    if (this.sections.has(key) && this.sections.get(key)?.draft === text) return
    // A section of the template under the same key keeps its own row; the kept text
    // gets a row of its own.
    const keptKey = this.sections.has(key) ? `${key}#kept` : key
    this.sections.set(keptKey, {
      title,
      draft: text,
      saved: '',
      base: 0,
      status: 'removed',
      conflict: null,
      error: null,
      savedAt: null,
    })
    this.keeper.keep(key, title, text)
    this.version += 1
    this.listeners.forEach((listener) => listener())
  }

  /** Sections removed from the template with your text kept here. */
  removed(): [ProposalSectionKey, SectionSaveState][] {
    return this.all().filter(([, state]) => state.status === 'removed')
  }

  /** "Discard": the kept text goes (here and in the local draft). */
  discardRemoved(key: ProposalSectionKey): void {
    if (this.sections.get(key)?.status !== 'removed') return
    this.sections.delete(key)
    this.keeper.forget(key.replace(/#kept$/, ''))
    this.version += 1
    this.listeners.forEach((listener) => listener())
  }

  /**
   * Newer text from the server (a refetch): taken only where nothing is unsaved here.
   * Phase 8: sections added to the template join; one removed meanwhile goes, unless
   * it has unsaved text here, which is kept (`removed`).
   */
  receive(sections: readonly ProposalSection[]): void {
    const listed = new Set(sections.map((section) => section.key))
    for (const [key, state] of this.all()) {
      if (listed.has(key) || state.status === 'removed') continue
      if (state.status === 'saved') {
        this.cancel(key)
        this.sections.delete(key)
        this.version += 1
        this.listeners.forEach((listener) => listener())
      } else this.markRemoved(key)
    }
    for (const section of sections) {
      const state = this.sections.get(section.key)
      if (state?.status === 'removed') {
        // Restored to the template: the section is edited again as the server has it,
        // and the text kept from before keeps a row of its own ("back in the template").
        const keptKey = `${section.key}#kept`
        if (!this.sections.has(keptKey)) this.sections.set(keptKey, state)
        this.sections.set(section.key, this.fromServer(section))
        this.version += 1
        this.listeners.forEach((listener) => listener())
        continue
      }
      if (!state) {
        this.sections.set(section.key, this.fromServer(section))
        this.version += 1
        this.listeners.forEach((listener) => listener())
        continue
      }
      if (state.title !== section.title) this.set(section.key, { title: section.title })
      if (section.version <= state.base) continue
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

  /** True while something isn't on the server yet (the leave warning; kept text is local). */
  hasUnsaved(): boolean {
    return this.all().some(([, state]) => state.status !== 'saved' && state.status !== 'removed')
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
  const states = store
    .all()
    .map(([, state]) => state)
    .filter((state) => state.status !== 'removed')
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
