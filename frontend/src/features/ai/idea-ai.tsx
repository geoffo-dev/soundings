import { FileSearch, Gauge, PenLine, Sparkles } from 'lucide-react'
import { useCallback } from 'react'

import { useIdeaAiRuns, useRequestAiRun } from '@/api/ai'
import { describeError, hasErrorCode, isApiError } from '@/api/errors'
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
import { formatTime } from '@/lib/dates'
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

/** Whether an element is on screen now (the run's row, after asking). */
function onScreen(element: HTMLElement): boolean {
  const rect = element.getBoundingClientRect()
  return rect.bottom > 0 && rect.top < window.innerHeight && rect.height > 0
}

/** Calls `then(element)` once `find()` renders (a few frames), or `then(null)`. */
function whenRendered(
  find: () => HTMLElement | null,
  then: (element: HTMLElement | null) => void,
  frames = 12,
) {
  const attempt = (left: number) => {
    const element = find()
    if (element || left <= 0) then(element)
    else window.requestAnimationFrame(() => attempt(left - 1))
  }
  window.requestAnimationFrame(() => attempt(frames))
}

/**
 * Why asking failed, in words (the toast): the hourly limit says what it is and
 * when asking works again (contract-phase6 §3.3: 20 requests a person an hour).
 */
export function describeAskError(error: unknown): { title: string; description?: string } {
  if (isApiError(error) && error.status === 429 && hasErrorCode(error, 'too_many_attempts')) {
    const seconds = error.retryAfterSeconds
    return {
      title: 'You can ask AI agents 20 times an hour',
      description:
        seconds !== undefined
          ? `Try again after ${formatTime(Date.now() + seconds * 1000)}.`
          : 'Try again later this hour.',
    }
  }
  const { title, description } = describeError(error)
  return {
    title: 'Couldn’t ask the AI agent',
    description: [title, description].filter(Boolean).join('. '),
  }
}

/**
 * Asks an agent. Unless its row is already in view, a toast says so with "View
 * progress" (the row may be off-screen or on another tab). A repeated ask while the
 * run is active answers with that run (200): the toast says it is already running.
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
          const title = existing
            ? `${agent.display_name} is already working on this`
            : `Asked ${agent.display_name} ${what}`
          if (kind === 'draft_section') {
            toast.message(title, {
              description: 'Its suggestion appears under the section when it is done.',
            })
            return
          }
          // The row in view says it all (and announces its steps): no toast on top.
          whenRendered(
            () => document.getElementById(runDomId(run.id)),
            (row) => {
              if (row && onScreen(row)) return
              toast.message(title, {
                description: 'Follow its progress on the Overview tab.',
                action: { label: 'View progress', onClick: () => showRun(run.id, setTab) },
              })
            },
          )
        },
        onError: (error) => {
          // A 401 signs you out (the query client); everything else says why here.
          if (isApiError(error) && error.status === 401) return
          const { title, description } = describeAskError(error)
          toast.error(title, { description })
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
          <Button
            variant="outline"
            aria-label="AI actions"
            // Phones: a quiet icon among vote, watch and more (the primary action is below).
            className="max-sm:size-7 max-sm:border-transparent max-sm:bg-transparent max-sm:px-0 max-sm:text-secondary"
          >
            <Sparkles />
            <span className="max-sm:sr-only">AI</span>
          </Button>
        </DropdownMenuTrigger>
      </WithTooltip>
      <DropdownMenuContent align="end" className="w-64">
        <DropdownMenuLabel>AI assistance</DropdownMenuLabel>
        <KindItems kind="evaluate" ai={ai} submittedIds={submittedIds} onAsk={ask} onShow={show} />
        <KindItems kind="research" ai={ai} submittedIds={submittedIds} onAsk={ask} onShow={show} />
        <DraftItems ai={ai} onAsk={ask} setTab={setTab} />
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
 * "Draft a section…" (UX review m4): the proposal's drafting from the same AI menu,
 * so it isn't only a button that appears on hovering a section. One agent: pick the
 * section here; several: the Proposal tab, where each section offers the choice.
 */
function DraftItems({
  ai,
  onAsk,
  setTab,
}: {
  ai: ReturnType<typeof useIdeaAi>
  onAsk: ReturnType<typeof useAskAi>['ask']
  setTab: (tab: IdeaTab) => void
}) {
  if (!ai.allowed('draft_section')) return null
  const agents = ai.agentsFor('draft_section')
  const agent = agents.length === 1 ? agents[0] : undefined
  if (!agent) {
    return (
      <DropdownMenuItem onSelect={() => setTab('proposal')}>
        <PenLine />
        Draft a section…
      </DropdownMenuItem>
    )
  }
  return (
    <DropdownMenuSub>
      <DropdownMenuSubTrigger>
        <PenLine />
        Draft a section…
      </DropdownMenuSubTrigger>
      <DropdownMenuSubContent>
        <DropdownMenuLabel>{agent.display_name} drafts</DropdownMenuLabel>
        {(Object.keys(SECTION_TITLES) as ProposalSectionKey[]).map((key) => (
          <DropdownMenuItem
            key={key}
            disabled={Boolean(ai.activeRun('draft_section', key))}
            onSelect={() => {
              setTab('proposal')
              // The section's progress (and Cancel) takes over in the editor.
              onAsk('draft_section', agent, key, () =>
                focusWhenRendered(
                  () =>
                    document.querySelector<HTMLElement>(`[data-draft-cancel="${CSS.escape(key)}"]`),
                  { force: true, frames: 60 },
                ),
              )
            }}
          >
            {SECTION_TITLES[key]}
          </DropdownMenuItem>
        ))}
      </DropdownMenuSubContent>
    </DropdownMenuSub>
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
