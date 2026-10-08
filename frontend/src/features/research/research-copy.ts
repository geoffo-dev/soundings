import type { GateAction } from '@/api/research'
import type { IdeaStatus, ResearchProgress, ResearchStep } from '@/api/types'

/** "2 of 3 answered" (screen readers and the panel; cards show "2/3"). */
export function progressWords(progress: ResearchProgress): string {
  return `${progress.answered} of ${progress.total} answered`
}

/** A card's badge name: "Research 2 of 3 answered, 1 required item open". */
export function badgeLabel(progress: ResearchProgress): string {
  const open = progress.required_open
  return `Research ${progressWords(progress)}${
    open > 0 ? `, ${open} required ${open === 1 ? 'item' : 'items'} open` : ', complete'
  }`
}

/**
 * Whether a card (board, list, My work) shows the checklist badge: in Research, and in
 * the status before it only once something is answered, so a column of "0/3" badges
 * doesn't crowd the cards before anyone started (UX review m1).
 */
export function showsResearchBadge(idea: {
  status: IdeaStatus
  research: ResearchProgress | null
}): boolean {
  const research = idea.research
  if (!research || research.total === 0) return false
  return idea.status === 'research' || research.answered > 0
}

/** The badge's words: "2 open" (required items left) or "Ready" (nothing blocks the move). */
export function badgeWords(progress: ResearchProgress): string {
  return progress.required_open > 0 ? `${progress.required_open} open` : 'Ready'
}

/** The one line under the step choice: where Research goes and what it does. */
export const STEP_EXPLANATIONS: Record<ResearchStep, string> = {
  off: 'No research stage: ideas go straight from New to evaluation.',
  before_evaluation: 'The owner checks every idea before anyone scores it.',
  before_proposal: 'Only shortlisted ideas are checked, before anyone writes a proposal.',
}

/** The gate dialog's "… anyway" button, by what was refused. */
export const OVERRIDE_LABELS: Record<GateAction, string> = {
  move: 'Move anyway',
  invite: 'Invite anyway',
  evaluate: 'Ask anyway',
  proposal: 'Start anyway',
}

export function gateDescription(action: GateAction, ideaKey: string, target?: string): string {
  switch (action) {
    case 'move':
      return `${ideaKey} can’t move to ${target ?? 'that status'} until its research checklist is done.`
    case 'invite':
      return `Inviting the first evaluator starts evaluation, which waits for ${ideaKey}’s research checklist.`
    case 'evaluate':
      return `Asking AI to evaluate starts evaluation, which waits for ${ideaKey}’s research checklist.`
    case 'proposal':
      return `Starting the proposal moves ${ideaKey} past research, which waits for its checklist.`
  }
}
