import { CloudOff, Lock, Sparkles, TriangleAlert } from 'lucide-react'

import { useIdeaAiRuns } from '@/api/ai'
import { useBidAiAssessments, useRequestAiBidAssessment, useSetBidAiInclusion } from '@/api/bids'
import { describeError } from '@/api/errors'
import type { AiAgentRef, BidAiAssessment, BidCall, BidCallView, BidDetail } from '@/api/types'
import { AiBadge } from '@/components/ui/ai-badge'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { RelativeTime } from '@/components/ui/relative-time'
import { Skeleton, SkeletonGroup } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { toast } from '@/components/ui/toaster'
import { BLOCKED_COPY, isActiveRun } from '@/features/ai/ai-copy'
import { RunCard } from '@/features/ai/run-card'
import { visibleText } from '@/lib/visible-text'

import { Evidence } from './must-haves'

/**
 * The AI's assessment of one bid, for call managers (contract-phase10 §9): the latest
 * assess run (the call's AI assessor starts one by itself: "Started automatically"),
 * "Ask AI to assess", and what it submitted: a score per question with its rationale and
 * quotes checked against the documents. Left out of the totals until a manager counts it.
 */
export function BidAi({
  ideaKey,
  view,
  bid,
}: {
  ideaKey: string
  view: BidCallView & { call: BidCall }
  bid: BidDetail
}) {
  const runs = useIdeaAiRuns(ideaKey)
  const assessments = useBidAiAssessments(ideaKey, bid.id)
  const request = useRequestAiBidAssessment(ideaKey)
  const bidRuns = (runs.data?.items ?? []).filter(
    (run) => run.kind === 'assess_bid' && run.bid_id === bid.id,
  )
  const latest = bidRuns[0]
  const active = latest ? isActiveRun(latest) : false
  const agents = orderAgents(view.ai_agents, view.call.ai_assessor)
  const blocked = view.permissions.request_ai_blocked_by
  const canAsk = bid.permissions.can_request_ai && agents.length > 0 && !active
  const documents = new Map(bid.documents.map((d) => [d.id, d]))

  const ask = (agent: AiAgentRef) =>
    request.mutate(
      { bidId: bid.id, agentId: agent.id },
      {
        onSuccess: () =>
          toast.success(`${agent.display_name} is assessing the bid from ${bid.bidder}`, {
            description: 'Its scores stay out of the totals until you count them.',
          }),
        onError: (error) => {
          const { title, description } = describeError(error)
          toast.error(title, { description })
        },
      },
    )

  return (
    <section aria-labelledby={`ai-${bid.id}`} className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3
          id={`ai-${bid.id}`}
          className="flex items-center gap-2 text-base font-semibold text-primary"
        >
          AI assessment <AiBadge />
        </h3>
        {bid.permissions.can_request_ai && agents.length > 0 && (
          <AskButton agents={agents} disabled={!canAsk} pending={request.isPending} onAsk={ask} />
        )}
      </div>
      {view.call.ai_assessor && !latest && bid.status !== 'rejected' && (
        <p className="text-sm text-muted">
          {view.call.ai_assessor.display_name} assesses each bid by itself once its documents are
          read and nothing has been uploaded for 5 minutes.
        </p>
      )}
      {!bid.permissions.can_request_ai && blocked && !latest && (
        <p className="text-sm text-muted">{BLOCKED_COPY[blocked]}.</p>
      )}
      {latest && (
        <div className="rounded-lg border">
          <RunCard ideaKey={ideaKey} run={latest} />
        </div>
      )}
      {assessments.isPending ? (
        <SkeletonGroup label="Loading the AI’s assessment" className="flex flex-col gap-2">
          <Skeleton className="h-16 w-full rounded-lg" />
        </SkeletonGroup>
      ) : assessments.isError ? (
        <div role="alert" className="flex flex-wrap items-center gap-3 text-sm text-secondary">
          <CloudOff aria-hidden="true" className="size-4 text-muted" />
          We couldn’t load the AI’s assessment.
          <Button size="sm" variant="outline" onClick={() => void assessments.refetch()}>
            Try again
          </Button>
        </div>
      ) : assessments.data.items.length === 0 ? (
        !latest && (
          <p className="rounded-lg border px-4 py-3 text-sm text-muted">
            No AI assessment of this bid yet.
          </p>
        )
      ) : (
        assessments.data.items.map((assessment) => (
          <AssessmentCard
            key={assessment.id}
            ideaKey={ideaKey}
            call={view.call}
            bid={bid}
            assessment={assessment}
            canInclude={assessments.data.can_include}
            documents={documents}
          />
        ))
      )}
    </section>
  )
}

/** The call's AI assessor first, then the others by name. */
function orderAgents(agents: AiAgentRef[], assessor: AiAgentRef | null): AiAgentRef[] {
  if (!assessor) return agents
  const first = agents.find((a) => a.id === assessor.id)
  return first ? [first, ...agents.filter((a) => a.id !== assessor.id)] : agents
}

function AskButton({
  agents,
  disabled,
  pending,
  onAsk,
}: {
  agents: AiAgentRef[]
  disabled: boolean
  pending: boolean
  onAsk: (agent: AiAgentRef) => void
}) {
  const [first] = agents
  if (!first) return null
  if (agents.length === 1) {
    return (
      <Button
        size="sm"
        variant="outline"
        disabled={disabled}
        loading={pending}
        onClick={() => onAsk(first)}
      >
        <Sparkles /> Ask AI to assess
      </Button>
    )
  }
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button size="sm" variant="outline" disabled={disabled} loading={pending}>
          <Sparkles /> Ask AI to assess
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuLabel>Which agent?</DropdownMenuLabel>
        {agents.map((agent) => (
          <DropdownMenuItem key={agent.id} onSelect={() => onAsk(agent)}>
            {agent.display_name}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

function AssessmentCard({
  ideaKey,
  call,
  bid,
  assessment,
  canInclude,
  documents,
}: {
  ideaKey: string
  call: BidCall
  bid: BidDetail
  assessment: BidAiAssessment
  canInclude: boolean
  documents: Map<string, { filename: string }>
}) {
  const inclusion = useSetBidAiInclusion(ideaKey, bid.id)
  const scores = new Map(assessment.scores.map((s) => [s.question_id, s]))
  const hidden = new Set(assessment.hidden_section_ids)
  const switchId = `ai-include-${assessment.id}`

  return (
    <article
      className="flex flex-col gap-4 rounded-lg border p-4"
      aria-label={`${assessment.agent.display_name}’s assessment`}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex flex-col gap-0.5">
          <span className="text-sm font-medium text-primary">{assessment.agent.display_name}</span>
          <span className="text-xs text-muted">
            Submitted <RelativeTime date={assessment.submitted_at} />
          </span>
        </div>
        {canInclude ? (
          <label htmlFor={switchId} className="flex items-center gap-2 text-sm text-secondary">
            <Switch
              id={switchId}
              checked={assessment.included}
              pending={inclusion.isPending}
              onCheckedChange={(include) =>
                inclusion.mutate(
                  { assessmentId: assessment.id, include },
                  {
                    onSuccess: () =>
                      toast.success(
                        include ? 'The AI’s scores now count' : 'The AI’s scores are left out',
                        { description: `${bid.bidder}’s totals were worked out again.` },
                      ),
                    onError: (error) => toast.error(describeError(error).title),
                  },
                )
              }
            />
            Count in the totals
          </label>
        ) : (
          <span className="text-sm text-muted">
            {assessment.included ? 'Counted in the totals' : 'Not counted'}
          </span>
        )}
      </div>
      {assessment.quotes_not_found > 0 && (
        <p className="flex items-start gap-2 text-sm text-warning">
          <TriangleAlert aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
          {assessment.quotes_not_found === 1
            ? 'One quote wasn’t found in the documents.'
            : `${assessment.quotes_not_found} quotes weren’t found in the documents.`}{' '}
          Check them before counting this assessment.
        </p>
      )}
      {call.template.sections.map((section) => {
        if (hidden.has(section.id)) {
          return (
            <div key={section.id} className="flex flex-col gap-1">
              <h4 className="text-sm font-semibold text-primary">{section.title}</h4>
              <p className="flex items-center gap-2 text-sm text-muted">
                <Lock aria-hidden="true" className="size-3.5 shrink-0" />
                Hidden until you submit your assessment of this section.
              </p>
            </div>
          )
        }
        const questions = section.questions.filter((q) => scores.has(q.id))
        if (questions.length === 0) return null
        return (
          <div key={section.id} className="flex flex-col gap-3">
            <h4 className="text-sm font-semibold text-primary">{section.title}</h4>
            <ul className="flex flex-col gap-3">
              {questions.map((question) => {
                const score = scores.get(question.id)
                if (!score) return null
                return (
                  <li key={question.id} className="flex flex-col gap-1.5">
                    <div className="flex items-baseline justify-between gap-3">
                      <span className="text-sm text-secondary">{question.text}</span>
                      <span className="shrink-0 text-sm font-semibold text-primary tabular-nums">
                        {score.score}
                        <span className="font-normal text-muted"> / 5</span>
                      </span>
                    </div>
                    {score.rationale && (
                      <p className="text-sm whitespace-pre-wrap text-muted">
                        {visibleText(score.rationale)}
                      </p>
                    )}
                    <Evidence evidence={score.evidence} documents={documents} />
                  </li>
                )
              })}
            </ul>
          </div>
        )
      })}
    </article>
  )
}
