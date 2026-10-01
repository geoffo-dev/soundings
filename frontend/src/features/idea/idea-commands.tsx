import {
  ArrowRightLeft,
  Eye,
  EyeOff,
  Gauge,
  Link2,
  Lock,
  LockOpen,
  MessageSquarePlus,
  ThumbsUp,
  UserMinus,
  UserPlus,
  UserRoundCheck,
  UserRoundPen,
} from 'lucide-react'

import {
  useSetEvaluationClosed,
  useSetIdeaOwner,
  useVoteIdea,
  useVolunteerAsOwner,
  useWatchIdea,
} from '@/api/ideas'
import type { CommandAction } from '@/components/ui/command-palette'
import { toast } from '@/components/ui/toaster'
import { useCommands } from '@/lib/command-registry'
import { SHORTCUTS, useShortcut } from '@/lib/shortcuts'

import type { IdeaPageContextValue } from './idea-context'

/** The idea's shareable URL. */
export function ideaUrl(key: string): string {
  return `${window.location.origin}/ideas/${key}`
}

export function copyIdeaLink(key: string) {
  const link = ideaUrl(key)
  navigator.clipboard
    .writeText(link)
    .then(() => toast.message('Link copied', { description: link }))
    .catch(() => toast.error('Couldn’t copy the link', { description: link }))
}

/**
 * Keyboard shortcuts (E, S, A, C, 1–3; listed in the "?" sheet) and ⌘K
 * palette actions for the idea in view. Only what the API's `permissions`
 * allow is registered.
 */
export function useIdeaCommands(page: IdeaPageContextValue) {
  const { idea, ideaKey, me, ownEvaluator, openDialog, openEvaluate, focusComment, setTab } = page
  const { permissions } = idea
  const setOwner = useSetIdeaOwner(ideaKey)
  const volunteer = useVolunteerAsOwner(ideaKey)
  const setClosed = useSetEvaluationClosed(ideaKey)
  const vote = useVoteIdea(ideaKey)
  const watch = useWatchIdea(ideaKey)
  const isOwner = idea.owner?.id === me.id
  const evaluationClosed = idea.evaluation_closed_at !== null && idea.status !== 'closed'

  useShortcut('evaluate', openEvaluate, { enabled: Boolean(ownEvaluator) })
  useShortcut('changeStatus', () => openDialog('status'), {
    enabled: permissions.can_change_status,
  })
  useShortcut('assignOwner', () => openDialog('owner'), { enabled: permissions.can_assign_owner })
  // On the Proposal tab "c" comments on the section in view (features/proposal).
  useShortcut('focusComment', focusComment, {
    enabled: permissions.can_comment && page.tab !== 'proposal',
  })
  useShortcut('overviewTab', () => setTab('overview'))
  useShortcut('evaluationsTab', () => setTab('evaluations'))
  useShortcut('proposalTab', () => setTab('proposal'))

  const actions: CommandAction[] = []
  if (ownEvaluator) {
    actions.push({
      id: 'evaluate',
      label:
        ownEvaluator.state === 'submitted'
          ? 'Open my evaluation'
          : ownEvaluator.state === 'draft'
            ? 'Continue evaluation'
            : 'Evaluate',
      icon: <Gauge />,
      shortcut: SHORTCUTS.evaluate.keys,
      keywords: ['score', 'rate', 'evaluate'],
      onSelect: openEvaluate,
    })
  }
  if (permissions.can_change_status) {
    actions.push({
      id: 'change-status',
      label: 'Change status…',
      icon: <ArrowRightLeft />,
      shortcut: SHORTCUTS.changeStatus.keys,
      keywords: ['move', 'shortlist', 'close', 'status'],
      onSelect: () => openDialog('status'),
    })
  }
  if (permissions.can_assign_owner) {
    actions.push({
      id: 'assign-owner',
      label: idea.owner ? 'Change owner…' : 'Assign owner…',
      icon: <UserRoundPen />,
      shortcut: SHORTCUTS.assignOwner.keys,
      keywords: ['owner', 'assign'],
      onSelect: () => openDialog('owner'),
    })
  }
  if (permissions.can_volunteer && !idea.owner) {
    actions.push({
      id: 'volunteer',
      label: 'I’ll own this',
      icon: <UserRoundCheck />,
      keywords: ['owner', 'volunteer', 'take'],
      onSelect: () => volunteer.mutate({}),
    })
  }
  if (isOwner && permissions.can_release_owner) {
    actions.push({
      id: 'step-down',
      label: 'Step down as owner',
      icon: <UserMinus />,
      keywords: ['owner', 'release'],
      onSelect: () => setOwner.mutate({ owner: null }),
    })
  }
  if (permissions.can_invite_evaluators) {
    actions.push({
      id: 'invite-evaluators',
      label: 'Invite evaluators…',
      icon: <UserPlus />,
      keywords: ['evaluator', 'invite', 'assign', 'due date'],
      onSelect: () => openDialog('invite'),
    })
  }
  if (permissions.can_close_evaluation && idea.status !== 'closed') {
    actions.push(
      evaluationClosed
        ? {
            id: 'reopen-evaluation',
            label: 'Reopen evaluation',
            icon: <LockOpen />,
            onSelect: () => setClosed.mutate({ closed: false }),
          }
        : {
            id: 'close-evaluation',
            label: 'Close evaluation',
            icon: <Lock />,
            keywords: ['finish', 'end', 'evaluation'],
            onSelect: () => setClosed.mutate({ closed: true }),
          },
    )
  }
  if (permissions.can_comment) {
    actions.push({
      id: 'comment',
      label: 'Write a comment',
      icon: <MessageSquarePlus />,
      shortcut: SHORTCUTS.focusComment.keys,
      keywords: ['comment', 'reply', 'discuss'],
      onSelect: focusComment,
    })
  }
  if (permissions.can_vote) {
    actions.push({
      id: 'vote',
      label: idea.has_voted ? 'Remove my vote' : 'Vote for this idea',
      icon: <ThumbsUp />,
      keywords: ['vote', 'upvote', 'like'],
      onSelect: () => vote.mutate({ vote: !idea.has_voted }),
    })
  }
  actions.push(
    {
      id: 'watch',
      label: idea.watching ? 'Stop watching' : 'Watch this idea',
      icon: idea.watching ? <EyeOff /> : <Eye />,
      keywords: ['subscribe', 'follow', 'notify'],
      onSelect: () => watch.mutate({ watch: !idea.watching }),
    },
    {
      id: 'copy-link',
      label: 'Copy link to idea',
      icon: <Link2 />,
      keywords: ['share', 'url'],
      onSelect: () => copyIdeaLink(idea.key),
    },
  )

  useCommands({ id: 'idea', heading: `${idea.key} ${idea.title}`, actions })
}
