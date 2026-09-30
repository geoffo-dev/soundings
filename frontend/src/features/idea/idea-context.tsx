import { createContext, use, type ReactNode } from 'react'

import type {
  CurrentUser,
  IdeaDetail,
  IdeaEvaluator,
  IdeaStatus,
  Project,
  Resolution,
  StatusLabels,
} from '@/api/types'
import { DEFAULT_RESOLUTION_LABELS, DEFAULT_STATUS_LABELS } from '@/lib/status'

import type { IdeaTab } from './idea-search'

/** Pickers opened from the sidebar, the palette, shortcuts or the phone details sheet. */
export type IdeaDialog = 'status' | 'owner' | 'invite' | 'delete'

export interface IdeaPageContextValue {
  /** The upper-case key from the URL (every `/ideas/{idea}` call uses it). */
  ideaKey: string
  idea: IdeaDetail
  /** Settings, rubric and labels; undefined while loading. */
  project: Project | undefined
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
