import { ChevronRight, RotateCw } from 'lucide-react'
import { useId, useState } from 'react'

import { useEvaluations } from '@/api/evaluations'
import type { AiRun } from '@/api/types'
import { Button } from '@/components/ui/button'
import { useIdeaPage } from '@/features/idea/idea-context'
import { focusWhenRendered } from '@/lib/focus'
import { cn } from '@/lib/utils'

import { isActiveRun } from './ai-copy'
import { evaluationCardDomId, researchNoteDomId, runDomId } from './dom-ids'
import { useAskAi, useIdeaAi } from './idea-ai'
import { RunCard } from './run-card'

/** Runs that keep a row on Overview: one per agent and kind (drafts live in the proposal). */
const groupKey = (run: AiRun) => `${run.agent.id}:${run.kind}`

/** A run that ended without doing its job (it offers "Try again"). */
const stoppedShort = (run: AiRun) => run.status === 'failed' || run.status === 'timed_out'

/**
 * Splits the idea's runs (newest first) into the rows on show and "History". A row
 * is the latest run of an agent and kind while it works or when it stopped short;
 * runs that did their job (their evaluation or note is on the page already) go to
 * History with everything older, unless `keep` holds them (a run someone watched
 * finish stays, so its outcome doesn't vanish). Draft runs stay out: the proposal
 * editor shows them under their section.
 */
export function partitionRuns(
  runs: readonly AiRun[],
  keep: (run: AiRun) => boolean = () => false,
): { latest: AiRun[]; history: AiRun[] } {
  const seen = new Set<string>()
  const latest: AiRun[] = []
  const history: AiRun[] = []
  for (const run of runs) {
    if (run.kind === 'draft_section') continue
    const key = groupKey(run)
    if (seen.has(key)) {
      history.push(run)
    } else {
      seen.add(key)
      if (isActiveRun(run) || stoppedShort(run) || keep(run)) latest.push(run)
      else history.push(run)
    }
  }
  // Working runs on top; the rest keep newest first.
  latest.sort((a, b) => Number(isActiveRun(b)) - Number(isActiveRun(a)))
  return { latest, history }
}

/**
 * The idea's AI runs on the Overview tab (contract-phase6 §3.15): a row per agent
 * and kind only while its latest run works or after it stopped short (with "Try
 * again"); finished runs fold under "History (N)", since what they saved is on the
 * page already (the feed, the Evaluations tab). Nothing at all while there are none.
 * Everyone who can open the idea sees them (they hold no score data); only the
 * owner and admins get Cancel and "Try again".
 */
export function AiRunsSection() {
  const { ideaKey, idea, setTab } = useIdeaPage()
  const ai = useIdeaAi(ideaKey)
  const { ask, pending } = useAskAi(ideaKey, setTab)
  // Runs seen working on this page keep their row once they end, outcome and all.
  const [watched] = useState(() => new Set<string>())
  for (const run of ai.runs) if (isActiveRun(run)) watched.add(run.id)
  const { latest, history } = partitionRuns(ai.runs, (run) => watched.has(run.id))
  const [showHistory, setShowHistory] = useState(false)
  const headingId = useId()
  const historyId = useId()
  // Whether an AI evaluation counts yet (people who can see evaluations only).
  const evaluated = latest.some((run) => run.kind === 'evaluate' && run.status === 'succeeded')
  const evaluations = useEvaluations(ideaKey, { enabled: evaluated && !idea.score_hidden })

  if (latest.length === 0 && history.length === 0) return null

  const counted = (run: AiRun): boolean | undefined => {
    const id = run.result.evaluation_id
    if (run.kind !== 'evaluate' || !id || idea.score_hidden) return undefined
    return evaluations.data?.items.find((item) => item.id === id)?.include_in_aggregate
  }

  const resultAction = (run: AiRun) => {
    if (run.status !== 'succeeded') return undefined
    const { evaluation_id: evaluationId, note_id: noteId } = run.result
    if (run.kind === 'evaluate' && evaluationId && !idea.score_hidden) {
      return (
        <Button
          variant="ghost"
          size="sm"
          onClick={() => {
            setTab('evaluations')
            focusWhenRendered(() => document.getElementById(evaluationCardDomId(evaluationId)), {
              force: true,
              frames: 60,
            })
          }}
        >
          View the evaluation
          <ChevronRight />
        </Button>
      )
    }
    if (run.kind === 'research' && noteId) {
      return (
        <Button
          variant="ghost"
          size="sm"
          onClick={() =>
            focusWhenRendered(() => document.getElementById(researchNoteDomId(noteId)), {
              force: true,
              frames: 60,
            })
          }
        >
          Read the note
          <ChevronRight />
        </Button>
      )
    }
    return undefined
  }

  /** A latest row already links to what this older run saved. */
  const linkedAbove = (run: AiRun) => {
    const { evaluation_id: evaluationId, note_id: noteId } = run.result
    return latest.some(
      (other) =>
        other.status === 'succeeded' &&
        ((evaluationId !== null && other.result.evaluation_id === evaluationId) ||
          (noteId !== null && other.result.note_id === noteId)),
    )
  }

  /** "Try again" on a latest run that stopped short, while the agent can be asked. */
  const retry = (run: AiRun) => {
    if (run.status === 'succeeded' || isActiveRun(run)) return undefined
    const agent = ai.agentsFor(run.kind).find((candidate) => candidate.id === run.agent.id)
    if (!agent || !ai.allowed(run.kind) || ai.activeRun(run.kind, run.section_key)) {
      return undefined
    }
    return (
      <Button
        variant="secondary"
        size="sm"
        loading={pending}
        onClick={() =>
          // The new run takes this row's place (this one moves to History): follow it.
          ask(run.kind, agent, run.section_key ?? undefined, (next) =>
            focusWhenRendered(() => document.getElementById(runDomId(next.id)), { force: true }),
          )
        }
      >
        <RotateCw />
        Try again
      </Button>
    )
  }

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-2">
      <h2 id={headingId} className="text-sm font-medium text-muted">
        AI runs
      </h2>
      {latest.length > 0 && (
        <ul className="flex flex-col divide-y divide-subtle rounded-lg border bg-surface">
          {latest.map((run) => (
            <li key={run.id}>
              <RunCard
                ideaKey={ideaKey}
                run={run}
                resultAction={resultAction(run)}
                retry={retry(run)}
                counted={counted(run)}
              />
            </li>
          ))}
        </ul>
      )}
      {history.length > 0 && (
        <>
          <Button
            variant="ghost"
            size="sm"
            className="-ml-2 self-start text-secondary"
            aria-expanded={showHistory}
            aria-controls={historyId}
            onClick={() => setShowHistory((value) => !value)}
          >
            <ChevronRight
              className={cn('transition-transform duration-150', showHistory && 'rotate-90')}
            />
            History ({history.length})
          </Button>
          {showHistory && (
            <ul
              id={historyId}
              aria-label="Earlier AI runs"
              className="flex flex-col divide-y divide-subtle rounded-lg border bg-surface"
            >
              {history.map((run) => (
                <li key={run.id}>
                  <RunCard
                    ideaKey={ideaKey}
                    run={run}
                    // An agent asked again re-submits the same evaluation: one link to it.
                    resultAction={linkedAbove(run) ? undefined : resultAction(run)}
                  />
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  )
}
