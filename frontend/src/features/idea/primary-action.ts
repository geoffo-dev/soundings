import type { IdeaDetail } from '@/api/types'

/**
 * The page's one primary action (wireframe 03, "one primary action per view"),
 * decided from the API's permissions and state — never from roles:
 *
 * 1. a pending evaluator (you owe a score): **Evaluate** (or Continue for a draft);
 * 2. an unowned idea: **Assign owner** (admins) or **I'll own this** (volunteers);
 * 3. owner/admin, nobody invited yet: **Invite evaluators**;
 * 4. owner/admin, every evaluation in and evaluation still open: **Close evaluation**;
 * 5. owner/admin, evaluation closed while the idea is still Evaluating: **Change status**
 *    (shortlist it or close it);
 * 6. otherwise none — commenting is always a secondary action.
 */
export type PrimaryAction =
  | { kind: 'evaluate'; label: 'Evaluate' | 'Continue evaluation' }
  | { kind: 'assign-owner'; label: 'Assign owner' }
  | { kind: 'volunteer'; label: 'I’ll own this' }
  | { kind: 'invite'; label: 'Invite evaluators' }
  | { kind: 'close-evaluation'; label: 'Close evaluation' }
  | { kind: 'change-status'; label: 'Change status' }

export function primaryAction(idea: IdeaDetail, viewerId: string): PrimaryAction | null {
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
  const { submitted, total } = idea.evaluator_progress
  if (total === 0 && permissions.can_invite_evaluators) {
    return { kind: 'invite', label: 'Invite evaluators' }
  }
  if (total > 0 && submitted >= total && idea.evaluation_open && permissions.can_close_evaluation) {
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
