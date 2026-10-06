import { FileSearch, Gauge, Sparkles } from 'lucide-react'
import { useCallback } from 'react'

import { useIdeaAiRuns, useRequestAiRun } from '@/api/ai'
import type { AiAgentRef, AiBlockedReason, AiRun, AiRunKind, ProposalSectionKey } from '@/api/types'
import { Button } from '@/components/ui/button'
import type { CommandAction } from '@/components/ui/command-palette'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { toast } from '@/components/ui/toaster'
import { WithTooltip } from '@/components/ui/tooltip'
import type { IdeaTab } from '@/features/idea/idea-search'
import { useCommands } from '@/lib/command-registry'
import { focusWhenRendered } from '@/lib/focus'

import { BLOCKED_COPY, isActiveRun, KIND_COPY, SECTION_TITLES } from './ai-copy'
import { runDomId } from './dom-ids'

/**
 * What AI can do on this idea for you now (contract-phase6 §3.15): the runs,
 * the agents per kind (c10), and each request's flag with its blocked reason.
 * `visible` is false for people who may not ask (members, viewers) and while AI
 * assistance is off: they see runs, never the actions.
 */
export function useIdeaAi(ideaKey: string) {
  const query = useIdeaAiRuns(ideaKey)
  const data = query.data
  const permissions = data?.permissions
  const agentsFor = useCallback(
    (kind: AiRunKind): AiAgentRef[] =>
      data?.agents.filter((agent) => agent.purposes.includes(kind)) ?? [],
    [data],
  )
  const blockedBy = (kind: AiRunKind): AiBlockedReason | null => {
    if (!permissions) return 'not_allowed'
    return kind === 'evaluate'
      ? permissions.request_evaluation_blocked_by
      : kind === 'research'
        ? permissions.research_blocked_by
        : permissions.draft_section_blocked_by
  }
  const allowed = (kind: AiRunKind) => blockedBy(kind) === null && agentsFor(kind).length > 0
  const activeRun = (kind: AiRunKind, sectionKey: ProposalSectionKey | null = null) =>
    data?.items.find(
      (run) => run.kind === kind && run.section_key === sectionKey && isActiveRun(run),
    )
  const offered = (['evaluate', 'research'] as const).filter((kind) => {
    const reason = blockedBy(kind)
    return reason !== 'not_allowed' && reason !== 'ai_off'
  })
  return {
    query,
    runs: data?.items ?? [],
    permissions,
    aiEnabled: data?.ai_enabled ?? false,
    agentsFor,
    blockedBy,
    allowed,
    activeRun,
    /** The AI menu has something to offer you (allowed, or explained). */
    visible: Boolean(data?.ai_enabled) && offered.length > 0,
  }
}

/**
 * The evaluate action's words, the same in the AI menu, the evaluators list and
 * ⌘K: "…again" once every agent offered has submitted its evaluation here.
 */
export function evaluateActionLabel(
  agents: readonly AiAgentRef[],
  submittedIds: readonly string[],
): string {
  const again = agents.length > 0 && agents.every((agent) => submittedIds.includes(agent.user_id))
  return again ? 'Ask AI to evaluate again' : KIND_COPY.evaluate.action
}

/** Evaluators who have submitted (an agent among them would re-evaluate). */
export function submittedEvaluatorIds(
  evaluators: readonly { state: string; user: { id: string } }[],
): string[] {
  return evaluators
    .filter((evaluator) => evaluator.state === 'submitted')
    .map((evaluator) => evaluator.user.id)
}

/** Switches to Overview (where run cards live) and focuses the run's card. */
export function showRun(runId: string, setTab?: (tab: IdeaTab) => void) {
  setTab?.('overview')
  focusWhenRendered(() => document.getElementById(runDomId(runId)), { force: true, frames: 60 })
}

/**
 * Asks an agent; the toast says so with "View progress" (the run card may be
 * off-screen or on another tab). A repeated ask while the run is active
 * answers with that run (200): the toast says it is already running.
 */
export function useAskAi(ideaKey: string, setTab?: (tab: IdeaTab) => void) {
  const request = useRequestAiRun(ideaKey)
  const ask = (
    kind: AiRunKind,
    agent: AiAgentRef,
    sectionKey?: ProposalSectionKey,
    /** After the run exists (the control that asked may be gone: move focus on). */
    onAsked?: (run: AiRun) => void,
  ) =>
    request.mutate(
      { kind, agentId: agent.id, sectionKey },
      {
        onSuccess: ({ run, existing }) => {
          onAsked?.(run)
          const what =
            kind === 'evaluate'
              ? 'to evaluate this idea'
              : kind === 'research'
                ? 'to research this idea'
                : `to draft ${sectionKey ? SECTION_TITLES[sectionKey] : 'a section'}`
          toast.message(
            existing
              ? `${agent.display_name} is already working on this`
              : `Asked ${agent.display_name} ${what}`,
            {
              description:
                kind === 'draft_section'
                  ? 'Its suggestion appears under the section when it is done.'
                  : 'Follow its progress on the Overview tab.',
              ...(kind === 'draft_section'
                ? {}
                : { action: { label: 'View progress', onClick: () => showRun(run.id, setTab) } }),
            },
          )
        },
      },
    )
  return { ask, pending: request.isPending, variables: request.variables }
}

function KindItems({
  kind,
  ai,
  submittedIds,
  onAsk,
  onShow,
}: {
  kind: 'evaluate' | 'research'
  ai: ReturnType<typeof useIdeaAi>
  submittedIds: readonly string[]
  onAsk: (kind: AiRunKind, agent: AiAgentRef) => void
  onShow: (run: AiRun) => void
}) {
  const Icon = kind === 'evaluate' ? Gauge : FileSearch
  const reason = ai.blockedBy(kind)
  if (reason === 'not_allowed' || reason === 'ai_off') return null
  const active = ai.activeRun(kind)
  if (active) {
    return (
      <DropdownMenuItem onSelect={() => onShow(active)}>
        <Icon />
        <span className="flex flex-col">
          <span>{KIND_COPY[kind].doing}…</span>
          <span className="text-xs text-muted">{active.agent.display_name} · view progress</span>
        </span>
      </DropdownMenuItem>
    )
  }
  const agents = ai.agentsFor(kind)
  const action =
    kind === 'evaluate' ? evaluateActionLabel(agents, submittedIds) : KIND_COPY[kind].action
  if (reason !== null || agents.length === 0) {
    return (
      <DropdownMenuItem disabled className="h-auto py-1.5 sm:h-auto">
        <Icon />
        <span className="flex flex-col">
          <span>{action}</span>
          <span className="text-xs text-muted">{BLOCKED_COPY[reason ?? 'no_agent']}</span>
        </span>
      </DropdownMenuItem>
    )
  }
  if (agents.length === 1 && agents[0]) {
    const agent = agents[0]
    return (
      <DropdownMenuItem onSelect={() => onAsk(kind, agent)} className="h-auto py-1.5 sm:h-auto">
        <Icon />
        <span className="flex flex-col">
          <span>{action}</span>
          <span className="text-xs text-muted">{agent.display_name}</span>
        </span>
      </DropdownMenuItem>
    )
  }
  return (
    <DropdownMenuSub>
      <DropdownMenuSubTrigger>
        <Icon />
        {action}
      </DropdownMenuSubTrigger>
      <DropdownMenuSubContent>
        <DropdownMenuLabel>Choose an agent</DropdownMenuLabel>
        {agents.map((agent) => (
          <DropdownMenuItem key={agent.id} onSelect={() => onAsk(kind, agent)}>
            <Sparkles />
            {agent.display_name}
          </DropdownMenuItem>
        ))}
      </DropdownMenuSubContent>
    </DropdownMenuSub>
  )
}

/**
 * The idea's "AI" menu beside its primary action (owner and admins): "Ask AI to
 * evaluate" and "Research this", straight to the one agent or with a choice of
 * several; disabled with the reason when it can't be done now; "Evaluating…"
 * links to a run that is already active.
 */
export function AiMenu({
  ideaKey,
  setTab,
  submittedIds = [],
}: {
  ideaKey: string
  setTab: (tab: IdeaTab) => void
  /** Evaluators who have submitted: an agent among them would re-evaluate. */
  submittedIds?: readonly string[]
}) {
  const ai = useIdeaAi(ideaKey)
  const { ask } = useAskAi(ideaKey, setTab)
  if (!ai.visible) return null
  const show = (run: AiRun) => showRun(run.id, setTab)
  return (
    <DropdownMenu>
      <WithTooltip content="Ask an AI agent">
        <DropdownMenuTrigger asChild>
          <Button variant="outline" aria-label="AI actions">
            <Sparkles />
            <span className="max-sm:sr-only">AI</span>
          </Button>
        </DropdownMenuTrigger>
      </WithTooltip>
      <DropdownMenuContent align="end" className="w-64">
        <DropdownMenuLabel>AI assistance</DropdownMenuLabel>
        <KindItems kind="evaluate" ai={ai} submittedIds={submittedIds} onAsk={ask} onShow={show} />
        <KindItems kind="research" ai={ai} submittedIds={submittedIds} onAsk={ask} onShow={show} />
        <DropdownMenuSeparator />
        <p className="px-2 py-1 text-xs text-muted">
          Agents work only on this idea, and only while the run lasts. Their evaluations don’t count
          in the score until you include them.
        </p>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

/**
 * "Ask AI to evaluate" in the evaluators list, where an AI evaluator ends up:
 * only when it can be asked now (the menu explains when it can't).
 */
export function AskAiToEvaluateButton({
  ideaKey,
  setTab,
  submittedIds = [],
}: {
  ideaKey: string
  setTab: (tab: IdeaTab) => void
  /** Evaluators who have submitted: an agent among them would re-evaluate. */
  submittedIds?: readonly string[]
}) {
  const ai = useIdeaAi(ideaKey)
  const { ask, pending } = useAskAi(ideaKey, setTab)
  const agents = ai.agentsFor('evaluate')
  if (!ai.allowed('evaluate') || ai.activeRun('evaluate')) return null
  const label = evaluateActionLabel(agents, submittedIds)
  // The button goes while the run works: focus its row's progress button instead.
  const onAsked = (run: AiRun) =>
    focusWhenRendered(
      () => document.querySelector<HTMLElement>(`[data-ai-run-state="${CSS.escape(run.id)}"]`),
      { force: true },
    )
  if (agents.length === 1 && agents[0]) {
    const agent = agents[0]
    return (
      <Button
        variant="ghost"
        size="sm"
        className="-ml-2 self-start text-secondary"
        loading={pending}
        onClick={() => ask('evaluate', agent, undefined, onAsked)}
      >
        <Sparkles />
        {label}
      </Button>
    )
  }
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="sm"
          className="-ml-2 self-start text-secondary"
          loading={pending}
        >
          <Sparkles />
          {label}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start">
        <DropdownMenuLabel>Choose an agent</DropdownMenuLabel>
        {agents.map((agent) => (
          <DropdownMenuItem
            key={agent.id}
            onSelect={() => ask('evaluate', agent, undefined, onAsked)}
          >
            <Sparkles />
            {agent.display_name}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

/** ⌘K: "Ask AI to evaluate" / "Research this" while they can be done (one per agent). */
export function useAiCommands(
  ideaKey: string,
  setTab: (tab: IdeaTab) => void,
  submittedIds: readonly string[] = [],
) {
  const ai = useIdeaAi(ideaKey)
  const { ask } = useAskAi(ideaKey, setTab)
  const actions: CommandAction[] = []
  for (const kind of ['evaluate', 'research'] as const) {
    if (!ai.allowed(kind)) continue
    const active = ai.activeRun(kind)
    if (active) {
      actions.push({
        id: `ai-${kind}-progress`,
        label: `${KIND_COPY[kind].doing}… view progress`,
        icon: <Sparkles />,
        keywords: ['ai', 'agent', 'progress'],
        onSelect: () => showRun(active.id, setTab),
      })
      continue
    }
    const agents = ai.agentsFor(kind)
    for (const agent of agents) {
      const action =
        kind === 'evaluate' ? evaluateActionLabel([agent], submittedIds) : KIND_COPY[kind].action
      actions.push({
        id: `ai-${kind}-${agent.id}`,
        label: agents.length > 1 ? `${action} (${agent.display_name})` : action,
        icon: kind === 'evaluate' ? <Gauge /> : <FileSearch />,
        keywords: ['ai', 'agent', 'kagent', kind === 'evaluate' ? 'score' : 'research'],
        onSelect: () => ask(kind, agent),
      })
    }
  }
  useCommands({ id: 'idea-ai', heading: 'AI assistance', actions })
}
