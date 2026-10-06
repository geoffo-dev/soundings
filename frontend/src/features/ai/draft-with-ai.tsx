import { RotateCw, Sparkles, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import { useCancelAiRun } from '@/api/ai'
import type { AiAgentRef, AiRun, ProposalSection } from '@/api/types'
import { AiBadge } from '@/components/ui/ai-badge'
import { Button } from '@/components/ui/button'
import { Callout } from '@/components/ui/callout'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Spinner } from '@/components/ui/spinner'
import { WithTooltip } from '@/components/ui/tooltip'
import { suggestionDomId } from '@/features/proposal/suggestions'
import { focusWhenRendered } from '@/lib/focus'

import { isActiveRun, runErrorWords } from './ai-copy'
import { useAskAi, useIdeaAi } from './idea-ai'
import { useRunProgress } from './use-run-progress'

/**
 * "Draft with AI" on one proposal section (contract-phase6 §3.9, §3.15): for the
 * owner and admins while c7 holds and an agent drafts for this project; one
 * agent asks straight away, several offer a choice. The draft arrives as a
 * Phase 5 suggestion (with the AI badge) under the section.
 */
export function DraftWithAiButton({
  ideaKey,
  section,
  className,
}: {
  ideaKey: string
  section: ProposalSection
  className?: string
}) {
  const ai = useIdeaAi(ideaKey)
  const { ask, pending, variables } = useAskAi(ideaKey)
  if (!ai.allowed('draft_section') || ai.activeRun('draft_section', section.key)) return null
  const agents = ai.agentsFor('draft_section')
  const asking = pending && variables?.sectionKey === section.key
  const label = `Draft ${section.title} with AI`
  // The button goes while the draft runs: focus the run's Cancel in its place.
  const onAsked = () =>
    focusWhenRendered(
      () => document.querySelector<HTMLElement>(`[data-draft-cancel="${CSS.escape(section.key)}"]`),
      { force: true },
    )
  if (agents.length === 1 && agents[0]) {
    const agent = agents[0]
    return (
      <WithTooltip content={`Ask ${agent.display_name} to suggest text for this section`}>
        <Button
          variant="ghost"
          size="sm"
          loading={asking}
          aria-label={label}
          className={className}
          onClick={() => ask('draft_section', agent, section.key, onAsked)}
        >
          <Sparkles />
          {/* A bare sparkle says nothing on a phone: "Draft" fits beside Write / Preview. */}
          <span className="sm:hidden">Draft</span>
          <span className="max-sm:hidden">Draft with AI</span>
        </Button>
      </WithTooltip>
    )
  }
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="sm" loading={asking} aria-label={label} className={className}>
          <Sparkles />
          {/* A bare sparkle says nothing on a phone: "Draft" fits beside Write / Preview. */}
          <span className="sm:hidden">Draft</span>
          <span className="max-sm:hidden">Draft with AI</span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuLabel>Choose an agent</DropdownMenuLabel>
        {agents.map((agent) => (
          <DropdownMenuItem
            key={agent.id}
            onSelect={() => ask('draft_section', agent, section.key, onAsked)}
          >
            <Sparkles />
            {agent.display_name}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

/** The DOM id of a section's "Try again" after a draft stopped (focus lands there). */
const retryDomId = (sectionKey: string) => `draft-retry-${sectionKey}`

/**
 * The section's draft run, in place: its live step while it works (Cancel), and
 * why it stopped when a run you watched fails, times out or is cancelled ("Try
 * again"). A finished draft needs nothing here: its suggestion card appears.
 *
 * Its Cancel goes when the run ends: if focus was on it (and is now lost), focus
 * moves to the new suggestion, or to "Try again" (else the callout) when it
 * stopped; anywhere else, focus stays where it is.
 */
export function SectionDraftProgress({
  ideaKey,
  section,
}: {
  ideaKey: string
  section: ProposalSection
}) {
  const ai = useIdeaAi(ideaKey)
  const { ask } = useAskAi(ideaKey)
  const runs = ai.runs.filter(
    (run) => run.kind === 'draft_section' && run.section_key === section.key,
  )
  // Runs seen active here keep their outcome until dismissed.
  const [watched, setWatched] = useState<ReadonlySet<string>>(() => new Set())
  const [dismissed, setDismissed] = useState<ReadonlySet<string>>(() => new Set())
  const activeIds = runs.filter(isActiveRun).map((run) => run.id)
  if (activeIds.some((id) => !watched.has(id))) setWatched(new Set([...watched, ...activeIds]))
  const run = runs.find(
    (candidate) =>
      isActiveRun(candidate) || (watched.has(candidate.id) && !dismissed.has(candidate.id)),
  )
  const calloutRef = useRef<HTMLDivElement>(null)
  // Focus was on the active draft's controls (a removed Cancel blurs to nothing).
  const hadFocus = useRef(false)
  const ended = run !== undefined && !isActiveRun(run)
  const runId = run?.id
  const suggestionId = run?.result.suggestion_id ?? null
  useEffect(() => {
    if (!ended || !hadFocus.current) return
    const active = document.activeElement
    if (active && active !== document.body && active.isConnected) return
    hadFocus.current = false
    focusWhenRendered(
      () =>
        suggestionId
          ? document.getElementById(suggestionDomId(suggestionId))
          : (document.getElementById(retryDomId(section.key)) ?? calloutRef.current),
      { force: true, frames: 90 },
    )
  }, [ended, runId, suggestionId, section.key])

  if (!run) return null
  if (isActiveRun(run)) {
    return (
      <ActiveDraft
        ideaKey={ideaKey}
        run={run}
        section={section}
        onFocusChange={(focused) => {
          hadFocus.current = focused
        }}
      />
    )
  }
  if (run.status === 'succeeded') {
    return (
      <p className="sr-only" role="status">
        {run.agent.display_name}’s suggestion for {section.title} is ready below.
      </p>
    )
  }
  const agent: AiAgentRef | undefined = ai
    .agentsFor('draft_section')
    .find((candidate) => candidate.id === run.agent.id)
  const stopped = run.status !== 'cancelled' ? runErrorWords(run) : null
  return (
    <Callout
      ref={calloutRef}
      tabIndex={-1}
      // You cancelled, or it stopped while you watched: news, not an emergency.
      role="status"
      tone={run.status === 'cancelled' ? 'neutral' : 'warning'}
      title={
        run.status === 'cancelled'
          ? `The draft by ${run.agent.display_name} was cancelled`
          : `${run.agent.display_name} couldn’t draft ${section.title}`
      }
      action={
        <span className="flex items-center gap-1">
          {agent && ai.allowed('draft_section') && (
            <Button
              id={retryDomId(section.key)}
              size="sm"
              variant="secondary"
              onClick={() =>
                ask('draft_section', agent, section.key, () =>
                  focusWhenRendered(
                    () =>
                      document.querySelector<HTMLElement>(
                        `[data-draft-cancel="${CSS.escape(section.key)}"]`,
                      ),
                    { force: true },
                  ),
                )
              }
            >
              <RotateCw />
              Try again
            </Button>
          )}
          <Button
            size="icon-sm"
            variant="ghost"
            aria-label="Dismiss"
            onClick={() => setDismissed(new Set([...dismissed, run.id]))}
          >
            <X />
          </Button>
        </span>
      }
    >
      {stopped ? `${stopped.what} ${stopped.next}` : 'Nothing was suggested.'}
    </Callout>
  )
}

function ActiveDraft({
  ideaKey,
  run,
  section,
  onFocusChange,
}: {
  ideaKey: string
  run: AiRun
  section: ProposalSection
  onFocusChange: (focused: boolean) => void
}) {
  const { detail } = useRunProgress(ideaKey, run)
  const cancel = useCancelAiRun(ideaKey)
  const latest = detail.events.at(-1)
  const cancelling = detail.cancel_requested || run.cancel_requested
  return (
    <div
      className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-lg border border-dashed bg-background px-3 py-2 text-sm"
      onFocus={() => onFocusChange(true)}
      onBlur={(event) => {
        const next = event.relatedTarget
        if (next instanceof Node && !event.currentTarget.contains(next)) onFocusChange(false)
      }}
    >
      <Spinner className="size-3.5 text-accent" />
      <span className="flex min-w-0 flex-1 flex-wrap items-center gap-x-2 gap-y-1">
        <span className="font-medium text-primary">
          {run.agent.display_name} is drafting {section.title}
        </span>
        <AiBadge />
        <span className="text-muted" aria-live="polite">
          {cancelling ? 'Cancelling…' : (latest?.message ?? 'Waiting to start')}
        </span>
      </span>
      {run.can_cancel && (
        <Button
          variant="ghost"
          size="sm"
          // Stays focusable while it cancels (aria-disabled), so focus isn't lost.
          loading={cancel.isPending || cancelling}
          data-draft-cancel={section.key}
          aria-label={`Cancel the draft of ${section.title}`}
          onClick={() => cancel.mutate(run.id)}
        >
          {!cancel.isPending && !cancelling && <X />}
          Cancel
        </Button>
      )}
    </div>
  )
}
