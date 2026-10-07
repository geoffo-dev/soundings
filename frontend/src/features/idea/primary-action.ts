import type { IdeaDetail } from '@/api/types'

/**
 * The page's one primary action (wireframe 03, "one primary action per view"),
 * decided from the API's permissions and state — never from roles. It follows
 * the idea's status, so every idea page has one obvious next step (UX review M6):
 *
 * 1. a pending evaluator (you owe a score): **Evaluate** (or Continue for a draft);
 * 2. an unowned idea: **Assign owner** (admins) or **I'll own this** (volunteers);
 * 3. owner/admin, nobody invited yet: **Invite evaluators**;
 * 4. owner/admin while evaluation is open (New or Evaluating): **Close evaluation**;
 * 5. owner/admin, evaluation closed while the idea is still Evaluating: **Change status**
 *    (shortlist it or close it);
 * 6. owner/admin of a Shortlisted idea with no proposal yet: **Start proposal**;
 * 7. owner/admin once there is (or may be) a proposal: **Open proposal** (the Proposal
 *    tab, whose editor has Export);
 * 8. otherwise none — commenting is always a secondary action.
 */
export type PrimaryAction =
  | { kind: 'evaluate'; label: 'Evaluate' | 'Continue evaluation' }
  | { kind: 'assign-owner'; label: 'Assign owner' }
  | { kind: 'volunteer'; label: 'I’ll own this' }
  | { kind: 'invite'; label: 'Invite evaluators' }
  | { kind: 'close-evaluation'; label: 'Close evaluation' }
  | { kind: 'change-status'; label: 'Change status' }
  | { kind: 'start-proposal'; label: 'Start proposal' }
  | { kind: 'open-proposal'; label: 'Open proposal' }

/** What the Proposal tab knows (its query), when it has loaded. */
export interface ProposalState {
  exists: boolean
  canCreate: boolean
}

export function primaryAction(
  idea: IdeaDetail,
  viewerId: string,
  proposal?: ProposalState,
): PrimaryAction | null {
  const { permissions } = idea
  const own = idea.evaluators.find((evaluator) => evaluator.user.id === viewerId)
  if (permissions.can_evaluate && own && own.state !== 'submitted') {
    return {
      kind: 'evaluate',
      label: own.state === 'draft' ? 'Continue evaluation' : 'Evaluate',
    }
  }
  if (idea.status === 'closed') return null
  if (!idea.owner) {
    if (permissions.can_assign_owner) return { kind: 'assign-owner', label: 'Assign owner' }
    if (permissions.can_volunteer) return { kind: 'volunteer', label: 'I’ll own this' }
  }
  const proposalStage = idea.status === 'shortlisted' || idea.status === 'proposal'
  if (proposalStage) {
    if (!permissions.can_change_status) return null
    if (idea.status === 'shortlisted' && proposal && !proposal.exists && proposal.canCreate) {
      return { kind: 'start-proposal', label: 'Start proposal' }
    }
    return { kind: 'open-proposal', label: 'Open proposal' }
  }
  const { total } = idea.evaluator_progress
  if (total === 0 && permissions.can_invite_evaluators) {
    return { kind: 'invite', label: 'Invite evaluators' }
  }
  if (total > 0 && idea.evaluation_open && permissions.can_close_evaluation) {
    return { kind: 'close-evaluation', label: 'Close evaluation' }
  }
  if (
    idea.status === 'evaluating' &&
    idea.evaluation_closed_at !== null &&
    permissions.can_change_status
  ) {
    return { kind: 'change-status', label: 'Change status' }
  }
  return null
}
