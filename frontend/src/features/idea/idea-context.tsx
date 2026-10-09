import { createContext, use, type ReactNode } from 'react'

import type {
  CurrentUser,
  IdeaDetail,
  IdeaEvaluator,
  IdeaStatus,
  Project,
  ResearchStep,
  Resolution,
  StatusLabels,
} from '@/api/types'
import { DEFAULT_RESOLUTION_LABELS, DEFAULT_STATUS_LABELS } from '@/lib/status'

import type { IdeaTab } from './idea-search'

/** Pickers opened from the sidebar, the palette, shortcuts or the phone details sheet. */
export type IdeaDialog =
  | 'status'
  | 'owner'
  | 'invite'
  | 'delete'
  /** Phase 8b: who does the research and by when ("Change"). */
  | 'researcher'
  /** Phase 8b: "Start research": who and by when, then the move into Research. */
  | 'start-research'
  /** Phase 8b: the researcher's "Hand back" (confirmed). */
  | 'hand-back'

export interface IdeaPageContextValue {
  /** The upper-case key from the URL (every `/ideas/{idea}` call uses it). */
  ideaKey: string
  idea: IdeaDetail
  /** Settings, rubric and labels; undefined while loading, and always for a guest researcher. */
  project: Project | undefined
  /**
   * Phase 8b: you see this idea only as its researcher (role matrix column R:
   * `permissions.can_view_project` false): no project, scores, evaluation or proposal.
   */
  guest: boolean
  /** The project's research step (a guest reads it from the idea's research panel). */
  researchStep: ResearchStep
  me: CurrentUser
  /** Your evaluator row, if you were asked to evaluate. */
  ownEvaluator: IdeaEvaluator | undefined
  /** The project is archived: everything is read-only (permissions are all false). */
  archived: boolean
  statusLabel: (status: IdeaStatus, resolution?: Resolution | null) => string
  openDialog: (dialog: IdeaDialog) => void
  /** Opens the evaluate sheet (`?evaluate=1`). */
  openEvaluate: () => void
  /** Switches to Overview and focuses the comment box. */
  focusComment: () => void
  /** The comment box calls this when it mounts or the request changes: true = focus yourself. */
  takeCommentFocus: () => boolean
  /** Bumped by `focusComment` so a mounted comment box knows to check. */
  commentFocusRequest: number
  setTab: (tab: IdeaTab) => void
  /** The tab in view (the proposal editor takes `c` for its own comments). */
  tab?: IdeaTab
}

const IdeaPageContext = createContext<IdeaPageContextValue | null>(null)

export function IdeaPageProvider({
  value,
  children,
}: {
  value: IdeaPageContextValue
  children: ReactNode
}) {
  return <IdeaPageContext value={value}>{children}</IdeaPageContext>
}

export function useIdeaPage(): IdeaPageContextValue {
  const value = use(IdeaPageContext)
  if (!value) throw new Error('useIdeaPage must be used inside the idea page')
  return value
}

const DEFAULT_LABELS: StatusLabels = { ...DEFAULT_STATUS_LABELS, ...DEFAULT_RESOLUTION_LABELS }

/** Project labels (admins rename them), falling back to the defaults while loading. */
export function statusLabeller(labels: StatusLabels | undefined) {
  const all = labels ?? DEFAULT_LABELS
  return (status: IdeaStatus, resolution?: Resolution | null) =>
    status === 'closed' && resolution ? all[resolution] : all[status]
}
