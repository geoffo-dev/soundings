import { ChevronRight, RotateCw } from 'lucide-react'
import { useId, useState } from 'react'

import type { AiRun } from '@/api/types'
import { Button } from '@/components/ui/button'
import { useIdeaPage } from '@/features/idea/idea-context'
import { suggestionDomId } from '@/features/proposal/suggestions'
import { focusWhenRendered } from '@/lib/focus'
import { cn } from '@/lib/utils'

import { isActiveRun } from './ai-copy'
import { evaluationCardDomId, researchNoteDomId } from './dom-ids'
import { useAskAi, useIdeaAi } from './idea-ai'
import { RunCard } from './run-card'

/** Finished runs shown (folded) before "Show N earlier runs". */
const RECENT = 3

/**
 * The idea's AI runs on the Overview tab (contract-phase6 §3.15): every active
 * run as a live card, runs that finished while you watched with their outcome,
 * then the three latest others folded to their outcome (and "Show N earlier
 * runs"). Nothing at all while there are none.
 * Everyone who can open the idea sees them (they hold no score data); only the
 * owner and admins get Cancel and "Try again".
 */
export function AiRunsSection() {
  const { ideaKey, idea, setTab } = useIdeaPage()
  const ai = useIdeaAi(ideaKey)
  const { ask, pending } = useAskAi(ideaKey, setTab)
  const runs = ai.runs
  // Runs seen active on this visit keep their card when they finish (the outcome).
  const [watched, setWatched] = useState<ReadonlySet<string>>(() => new Set())
  const activeIds = runs.filter(isActiveRun).map((run) => run.id)
  if (activeIds.some((id) => !watched.has(id))) setWatched(new Set([...watched, ...activeIds]))
  const [showEarlier, setShowEarlier] = useState(false)
  const headingId = useId()
  const earlierId = useId()

  if (runs.length === 0) return null
  const prominent = runs.filter((run) => isActiveRun(run) || watched.has(run.id))
  const earlier = runs.filter((run) => !prominent.includes(run))

  const resultAction = (run: AiRun) => {
    if (run.status !== 'succeeded') return undefined
    const { evaluation_id: evaluationId, note_id: noteId, suggestion_id: suggestionId } = run.result
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
    if (run.kind === 'draft_section' && suggestionId) {
      return (
        <Button
          variant="ghost"
          size="sm"
          onClick={() => {
            setTab('proposal')
            focusWhenRendered(() => document.getElementById(suggestionDomId(suggestionId)), {
              force: true,
              frames: 90,
            })
          }}
        >
          Open the proposal
          <ChevronRight />
        </Button>
      )
    }
    return undefined
  }

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
        onClick={() => ask(run.kind, agent, run.section_key ?? undefined)}
      >
        <RotateCw />
        Try again
      </Button>
    )
  }

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-3">
      <h2 id={headingId} className="text-sm font-medium text-muted">
        AI runs
      </h2>
      {prominent.length > 0 && (
        <ul className="flex flex-col gap-3">
          {prominent.map((run) => (
            <li key={run.id}>
              <RunCard
                ideaKey={ideaKey}
                run={run}
                resultAction={resultAction(run)}
                retry={retry(run)}
              />
            </li>
          ))}
        </ul>
      )}
      {earlier.length > 0 && (
        <ul id={earlierId} className="flex flex-col gap-2">
          {earlier.slice(0, showEarlier ? undefined : RECENT).map((run) => (
            <li key={run.id}>
              <RunCard
                ideaKey={ideaKey}
                run={run}
                collapsed
                resultAction={resultAction(run)}
                retry={retry(run)}
              />
            </li>
          ))}
        </ul>
      )}
      {earlier.length > RECENT && (
        <Button
          variant="ghost"
          size="sm"
          className="-ml-2 self-start text-secondary"
          aria-expanded={showEarlier}
          aria-controls={earlierId}
          onClick={() => setShowEarlier((value) => !value)}
        >
          <ChevronRight
            className={cn('transition-transform duration-150', showEarlier && 'rotate-90')}
          />
          {showEarlier ? 'Show fewer runs' : `Show ${earlier.length - RECENT} earlier runs`}
        </Button>
      )}
    </section>
  )
}
