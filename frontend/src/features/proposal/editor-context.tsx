import { createContext, use } from 'react'

import type {
  CurrentUser,
  IdeaDetail,
  ProposalPermissions,
  ProposalSectionKey,
  ProposalSuggestion,
  ProposalSuggestionPermissions,
  ProposalThread,
} from '@/api/types'

import type { ProposalExportFormat } from '@/api/proposals'

import type { ProposalSaveStore } from './save-store'

export type SectionMode = 'write' | 'preview'

export interface ProposalEditorContextValue {
  ideaKey: string
  idea: IdeaDetail
  me: CurrentUser
  permissions: ProposalPermissions
  store: ProposalSaveStore
  /** Margin threads per section (template order, then oldest first); undefined while loading. */
  threads: Map<ProposalSectionKey, ProposalThread[]> | undefined
  threadsError: boolean
  retryThreads: () => void
  /** Phase 5: pending suggestions per section (template order, then oldest first). */
  suggestions: Map<ProposalSectionKey, ProposalSuggestion[]>
  /** Accept / discard (`can_decide`), suggest (`can_suggest`); false while loading. */
  suggestionPermissions: ProposalSuggestionPermissions
  modeOf: (key: ProposalSectionKey) => SectionMode
  setMode: (key: ProposalSectionKey, mode: SectionMode) => void
  /** Write ⇄ Preview, keeping focus in the section (its text, or the preview). */
  toggleSectionMode: (key: ProposalSectionKey) => void
  /** The section whose "new thread" composer is open in the margin (desktop). */
  composingIn: ProposalSectionKey | null
  setComposingIn: (key: ProposalSectionKey | null) => void
  /** The section whose comments sheet is open (phones and tablets). */
  sheetFor: ProposalSectionKey | null
  setSheetFor: (key: ProposalSectionKey | null) => void
  /** "Comment on this section": the margin composer on wide screens, else the sheet. */
  startComment: (key: ProposalSectionKey) => void
  /** Moves focus to a section (outline, jump list, j/k). */
  focusSection: (key: ProposalSectionKey) => void
  /** Export runner (the menu and the palette). */
  exporting: {
    run: (format: ProposalExportFormat) => void
    format: ProposalExportFormat | null
    announcement: string
  }
  /** The section in view or holding focus. */
  current: ProposalSectionKey
  setCurrent: (key: ProposalSectionKey) => void
}

const ProposalEditorContext = createContext<ProposalEditorContextValue | null>(null)

export const ProposalEditorProvider = ProposalEditorContext

export function useProposalEditor(): ProposalEditorContextValue {
  const value = use(ProposalEditorContext)
  if (!value) throw new Error('useProposalEditor must be used inside the proposal editor')
  return value
}

/** Threads that are still open, for counts (outline badges, "Comments (2)"). */
export function openThreadCount(threads: ProposalThread[] | undefined): number {
  return threads?.filter((thread) => !thread.resolved_at).length ?? 0
}
