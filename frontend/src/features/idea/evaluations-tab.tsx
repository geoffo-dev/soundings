import { CloudOff, ListChecks, PencilLine, TriangleAlert } from 'lucide-react'

import { useEvaluations } from '@/api/evaluations'
import { AiBadge } from '@/components/ui/ai-badge'
import { AiInclusionControl } from '@/features/ai/ai-evaluation'
import { evaluationCardDomId } from '@/features/ai/dom-ids'
import { SourceList } from '@/features/ai/sources'
import type { AggregateScore, Evaluation, RubricCriterion } from '@/api/types'
import { Avatar } from '@/components/ui/avatar'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'
import { RelativeTime } from '@/components/ui/relative-time'
import { Skeleton, SkeletonGroup } from '@/components/ui/skeleton'
import { WithTooltip } from '@/components/ui/tooltip'
import { formatDateTime } from '@/lib/dates'
import { formatScore } from '@/lib/scores'
import { cn } from '@/lib/utils'
import { visibleText } from '@/lib/visible-text'

import { useIdeaPage } from './idea-context'
import { RecommendationBadge, ScoreChip } from './score-display'
import { AggregateView, HiddenScore } from './score-panel'

/**
 * Every submitted evaluation (contract: `GET …/evaluations`), a compact
 * per-criterion comparison, then one card per evaluator. A pending evaluator
 * sees the blind state only: nothing is fetched or rendered from scores.
 */
export function EvaluationsTab() {
  const { idea, ideaKey, project, ownEvaluator, openEvaluate } = useIdeaPage()
  const evaluations = useEvaluations(ideaKey, { enabled: !idea.score_hidden })
  const { submitted, total } = idea.evaluator_progress

  if (idea.score_hidden || evaluations.data?.score_hidden) {
    const canEvaluate = Boolean(ownEvaluator) && idea.permissions.can_evaluate
    return (
      <div className="flex flex-col gap-4">
        <ProgressLine submitted={submitted} total={total} />
        <HiddenScore evaluationOpen={idea.evaluation_open} />
        {canEvaluate && (
          <Button variant="outline" className="self-start" onClick={openEvaluate}>
            {ownEvaluator?.state === 'draft' ? 'Continue your evaluation' : 'Evaluate now'}
          </Button>
        )}
      </div>
    )
  }

  if (evaluations.isPending || !project) {
    return (
      <SkeletonGroup label="Loading evaluations" className="flex flex-col gap-4">
        <Skeleton className="h-4 w-48" />
        <Skeleton className="h-32 w-full rounded-lg" />
        <Skeleton className="h-40 w-full rounded-lg" />
      </SkeletonGroup>
    )
  }

  if (evaluations.isError) {
    return (
      <div role="alert" className="rounded-lg border">
        <EmptyState
          size="compact"
          icon={<CloudOff />}
          title="We couldn’t load the evaluations"
          description="Check your connection and try again."
          action={
            <Button size="sm" onClick={() => void evaluations.refetch()}>
              Try again
            </Button>
          }
        />
      </div>
    )
  }

  const items = evaluations.data.items
  const rubric = [...project.rubric].sort((a, b) => a.position - b.position)
  const pending = idea.evaluators.filter((evaluator) => evaluator.state !== 'submitted')

  if (items.length === 0) {
    return (
      <div className="rounded-lg border">
        <EmptyState
          size="compact"
          icon={<ListChecks />}
          title="No evaluations yet"
          description={
            total > 0
              ? `${total} ${total === 1 ? 'person has' : 'people have'} been asked. Their evaluations appear here once submitted.`
              : 'Nobody has been asked to evaluate this idea yet.'
          }
        />
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-8">
      <section aria-labelledby="evaluations-summary-heading" className="flex flex-col gap-4">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 id="evaluations-summary-heading" className="text-base font-semibold text-primary">
            {submitted} submitted of {total}
          </h2>
          {pending.length > 0 && (
            <p className="text-sm text-muted">
              Waiting for {pending.map((evaluator) => evaluator.user.display_name).join(', ')}
            </p>
          )}
        </div>
        {idea.aggregate && (
          // From lg the sidebar's Score section shows the same, right next to it.
          <div className="rounded-lg border bg-surface p-4 lg:hidden">
            <AggregateView aggregate={idea.aggregate} compact />
          </div>
        )}
        <Comparison rubric={rubric} items={items} aggregate={idea.aggregate} />
      </section>

      <section aria-labelledby="evaluations-list-heading" className="flex flex-col gap-3">
        <h2 id="evaluations-list-heading" className="text-sm font-medium text-muted">
          Evaluations
        </h2>
        <ul className="flex flex-col gap-3">
          {items.map((evaluation) => (
            <li key={evaluation.id}>
              <EvaluationCard evaluation={evaluation} rubric={rubric} />
            </li>
          ))}
        </ul>
      </section>
    </div>
  )
}

function ProgressLine({ submitted, total }: { submitted: number; total: number }) {
  if (total === 0) return null
  return (
    <p className="text-sm text-muted">
      {submitted} of {total} {total === 1 ? 'evaluator has' : 'evaluators have'} submitted.
    </p>
  )
}

/**
 * The Mean column: on phones it stays pinned at the right edge while a wide table
 * (many evaluators) scrolls underneath, so the summary is never off-screen.
 */
const MEAN_COLUMN =
  'px-3 py-2 text-right whitespace-nowrap max-sm:sticky max-sm:right-0 max-sm:border-l max-sm:border-subtle'

/** Criteria down, evaluators across: spot where people disagree at a glance. */
function Comparison({
  rubric,
  items,
  aggregate,
}: {
  rubric: RubricCriterion[]
  items: Evaluation[]
  aggregate: AggregateScore | null
}) {
  const { me } = useIdeaPage()
  const stats = new Map(aggregate?.criteria.map((c) => [c.criterion_id, c]))
  // An AI evaluation left out: its column is muted and Mean says it counts the rest.
  const someLeftOut = items.some((evaluation) => !evaluation.include_in_aggregate)
  return (
    // Scrolls sideways on phones: focusable so the keyboard can scroll it too (axe
    // scrollable-region-focusable); a named region says what it is.
    <div
      // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
      tabIndex={0}
      role="region"
      aria-label="Score comparison"
      className="overflow-x-auto rounded-lg border focus-visible:outline-offset-[-2px]"
    >
      <table className="w-full border-collapse text-sm">
        <caption className="sr-only">Scores by criterion and evaluator</caption>
        <thead>
          <tr className="border-b bg-background">
            <th scope="col" className="px-3 py-2 text-left font-medium text-secondary">
              Criterion
            </th>
            {items.map((evaluation) => {
              const name = evaluation.evaluator.display_name
              return (
                <th key={evaluation.id} scope="col" className="px-2 py-2 text-center font-medium">
                  <span className="sr-only">
                    {name}
                    {evaluation.evaluator.id === me.id ? ' (you)' : ''}
                    {evaluation.is_ai ? ', AI agent' : ''}
                    {evaluation.include_in_aggregate ? '' : ', not counted in the score'}
                  </span>
                  <Avatar
                    name={name}
                    src={evaluation.evaluator.avatar_url}
                    isAgent={evaluation.is_ai}
                    size="sm"
                    tooltip
                    decorative
                    className="mx-auto"
                  />
                  {/* Initials alone need a hover, which touch screens don't have. A
                      person goes by their first name; an agent's name is all one name
                      ("Idea evaluator", not "Idea"). */}
                  <span
                    aria-hidden="true"
                    title={evaluation.is_ai ? name : undefined}
                    // Narrower on phones, so the ellipsis shows before the pinned Mean column.
                    className="mx-auto mt-0.5 block max-w-16 truncate text-xs font-normal text-secondary sm:max-w-24"
                  >
                    {evaluation.is_ai ? name : name.split(' ')[0]}
                  </span>
                  {!evaluation.include_in_aggregate && (
                    <span
                      aria-hidden="true"
                      // Wraps on phones, inside the narrow column (not under the pinned Mean).
                      className="mx-auto block max-w-16 text-xs leading-tight font-normal text-muted sm:max-w-none sm:whitespace-nowrap"
                    >
                      not in score
                    </span>
                  )}
                </th>
              )
            })}
            <th scope="col" className={cn(MEAN_COLUMN, 'bg-background font-medium text-secondary')}>
              Mean
              {someLeftOut && <span className="block text-xs font-normal text-muted">counted</span>}
            </th>
          </tr>
        </thead>
        <tbody>
          {rubric.map((criterion) => {
            const stat = stats.get(criterion.id)
            const disagreement = stat !== undefined && stat.count >= 2 && stat.spread >= 2
            return (
              <tr key={criterion.id} className="border-b border-subtle last:border-0">
                <th scope="row" className="px-3 py-2 text-left font-normal">
                  <span className="whitespace-nowrap text-primary">{criterion.name}</span>
                  {criterion.inverted && (
                    // Under the name on phones, so the table fits.
                    <span className="ml-1.5 text-xs whitespace-nowrap text-muted max-sm:ml-0 max-sm:block">
                      lower is better
                    </span>
                  )}
                </th>
                {items.map((evaluation) => {
                  const score = evaluation.scores.find(
                    (s) => s.criterion_id === criterion.id,
                  )?.score
                  return (
                    <td key={evaluation.id} className="px-2 py-2 text-center">
                      {score === undefined ? (
                        <span className="text-muted">–</span>
                      ) : (
                        <ScoreChip
                          score={score}
                          inverted={criterion.inverted}
                          muted={!evaluation.include_in_aggregate}
                          label={`${evaluation.evaluator.display_name}: ${score} out of 5${evaluation.include_in_aggregate ? '' : ', not counted'}`}
                          className="mx-auto"
                        />
                      )}
                    </td>
                  )
                })}
                <td className={cn(MEAN_COLUMN, 'bg-surface')}>
                  <span className="inline-flex items-center gap-1.5">
                    {disagreement && (
                      <WithTooltip content={`Scores range ${stat.min}–${stat.max}`}>
                        <span className="inline-flex text-warning">
                          <TriangleAlert aria-hidden="true" className="size-3.5" />
                          <span className="sr-only">High disagreement,</span>
                        </span>
                      </WithTooltip>
                    )}
                    <span className="font-semibold text-primary tabular-nums">
                      {formatScore(stat && stat.count > 0 ? stat.mean : null)}
                    </span>
                  </span>
                </td>
              </tr>
            )
          })}
          <tr className="border-t bg-background">
            <th scope="row" className="px-3 py-2 text-left font-normal text-secondary">
              Recommendation
            </th>
            {items.map((evaluation) => (
              <td key={evaluation.id} className="px-2 py-2 text-center">
                <RecommendationBadge value={evaluation.recommendation} compact />
              </td>
            ))}
            <td className={cn(MEAN_COLUMN, 'bg-background')} />
          </tr>
        </tbody>
      </table>
    </div>
  )
}

function EvaluationCard({
  evaluation,
  rubric,
}: {
  evaluation: Evaluation
  rubric: RubricCriterion[]
}) {
  const { me, ideaKey } = useIdeaPage()
  const name = evaluation.evaluator.display_name
  const isMe = evaluation.evaluator.id === me.id
  const headingId = `evaluation-${evaluation.id}`
  const ai = evaluation.is_ai
  // An AI evaluator gives a rationale (and sources) for every criterion: show them all.
  const commented = rubric.flatMap((criterion) => {
    const entry = evaluation.scores.find((s) => s.criterion_id === criterion.id)
    return entry && (entry.comment || entry.sources.length > 0 || ai) ? [{ criterion, entry }] : []
  })
  return (
    <article
      id={evaluationCardDomId(evaluation.id)}
      tabIndex={-1}
      aria-labelledby={headingId}
      className="scroll-mt-20 rounded-lg border bg-surface outline-offset-2"
    >
      <header className="flex flex-wrap items-center gap-x-2.5 gap-y-1 border-b border-subtle px-4 py-3">
        <Avatar
          name={name}
          src={evaluation.evaluator.avatar_url}
          isAgent={ai}
          agentBadge={false}
          size="sm"
          decorative
        />
        <h3 id={headingId} className="font-medium text-primary">
          {name}
          {isMe && <span className="font-normal text-muted"> (you)</span>}
        </h3>
        {ai && <AiBadge />}
        <RecommendationBadge value={evaluation.recommendation} />
        {!evaluation.include_in_aggregate && <Badge variant="outline">Not in score</Badge>}
        <span className="ml-auto flex items-center gap-2 text-sm text-muted">
          {evaluation.edited_at &&
            (ai ? (
              // An agent asked again re-submits: that is a new evaluation, not an edit.
              <span>
                Re-evaluated <RelativeTime date={evaluation.edited_at} />
              </span>
            ) : (
              <WithTooltip content={`Edited ${formatDateTime(evaluation.edited_at)}`}>
                <span className="inline-flex items-center gap-1">
                  <PencilLine aria-hidden="true" className="size-3.5" />
                  Edited after submission
                </span>
              </WithTooltip>
            ))}
          {!(ai && evaluation.edited_at) && (
            <span>
              Submitted <RelativeTime date={evaluation.submitted_at} />
            </span>
          )}
        </span>
      </header>
      {ai && <AiInclusionControl ideaKey={ideaKey} evaluation={evaluation} />}
      {/* The scores are in the table above: the card is for what people wrote. */}
      {commented.length > 0 && (
        <dl className="flex flex-col divide-y divide-subtle">
          {commented.map(({ criterion, entry }) => (
            <div key={criterion.id} className="flex flex-col gap-1 px-4 py-2.5">
              <dt className="flex items-center justify-between gap-3 text-sm text-secondary">
                {criterion.name}
                <ScoreChip
                  score={entry.score}
                  inverted={criterion.inverted}
                  muted={!evaluation.include_in_aggregate}
                  label={`${criterion.name}: ${entry.score} out of 5`}
                />
              </dt>
              <dd className="flex flex-col gap-1.5">
                {entry.comment ? (
                  <p className="text-sm [overflow-wrap:anywhere] whitespace-pre-line text-primary">
                    {ai && <span className="mr-1.5 text-xs font-medium text-muted">Rationale</span>}
                    {/* An agent's words: nothing invisible or direction-changing. */}
                    {ai ? visibleText(entry.comment) : entry.comment}
                  </p>
                ) : (
                  ai && <p className="text-sm text-muted">No rationale given.</p>
                )}
                {/* Only AI evaluators cite sources (people never do). */}
                {ai && <SourceList sources={entry.sources} compact />}
              </dd>
            </div>
          ))}
        </dl>
      )}
      {commented.length === 0 && !evaluation.comment && (
        <p className="px-4 py-3 text-sm text-muted">No comments.</p>
      )}
      {evaluation.comment && (
        <div
          className={cn(
            'flex flex-col gap-1 px-4 py-3',
            commented.length > 0 && 'border-t border-subtle',
          )}
        >
          <p className="text-xs font-medium text-muted">{ai ? 'Summary' : 'Overall comment'}</p>
          <p className="text-sm [overflow-wrap:anywhere] whitespace-pre-line text-primary">
            {ai ? visibleText(evaluation.comment) : evaluation.comment}
          </p>
        </div>
      )}
      {ai && (
        <p className="border-t border-subtle px-4 py-2 text-xs text-muted">
          Written by an AI agent. Its sources are cited by AI, not checked: an agent can get them
          wrong.
        </p>
      )}
    </article>
  )
}
