import {
  CalendarDays,
  Check,
  Clock,
  Lock,
  MessageSquarePlus,
  Sparkles,
  TriangleAlert,
} from 'lucide-react'
import { useEffect, useId, useRef, useState, type ReactNode } from 'react'

import { Avatar } from '@/components/ui/avatar'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ProgressTicks } from '@/components/ui/progress-ticks'
import { ScoreBadge } from '@/components/ui/score-badge'
import { ScoreBar } from '@/components/ui/score-bar'
import { SegmentedControl, scoreOptions } from '@/components/ui/segmented-control'
import {
  Sheet,
  SheetBody,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from '@/components/ui/sheet'
import { StatusBadge, StatusDot } from '@/components/ui/status-badge'
import { Textarea } from '@/components/ui/textarea'
import { toast } from '@/components/ui/toaster'
import { statusTone } from '@/lib/status'
import { cn } from '@/lib/utils'

import {
  CRITERION_RESULTS,
  IDEAS,
  person,
  RUBRIC,
  type Criterion,
  type SampleIdea,
} from './sample-data'

/* ------------------------------------------------------------------ */
/* Evaluate                                                            */
/* ------------------------------------------------------------------ */

export function EvaluateCriterionRow({
  criterion,
  value,
  onValueChange,
}: {
  criterion: Criterion
  value: string | null
  onValueChange: (value: string) => void
}) {
  const id = useId()
  const [commenting, setCommenting] = useState(false)
  const commentRef = useRef<HTMLTextAreaElement>(null)
  // Move focus into the comment field once the user asks for it.
  useEffect(() => {
    if (commenting) commentRef.current?.focus()
  }, [commenting])
  return (
    <div className="flex flex-col gap-3 border-b border-subtle py-5 first:pt-0 last:border-0 last:pb-0">
      <div className="flex items-start justify-between gap-4">
        <div className="flex min-w-0 flex-col gap-0.5">
          <span id={`${id}-name`} className="text-base font-medium text-primary">
            {criterion.name}
          </span>
          <span className="text-sm text-muted">{criterion.description}</span>
        </div>
        <span className="shrink-0 text-xs text-muted tabular-nums">Weight {criterion.weight}</span>
      </div>
      <SegmentedControl
        variant="accent"
        fullWidth
        aria-labelledby={`${id}-name`}
        options={scoreOptions(criterion.guidance)}
        value={value}
        onValueChange={onValueChange}
        guidancePlaceholder="Hover a score to see what it means"
      />
      {commenting ? (
        <Textarea
          aria-label={`Comment on ${criterion.name}`}
          placeholder="Optional — what drove this score?"
          minRows={2}
          ref={commentRef}
        />
      ) : (
        <Button
          variant="ghost"
          size="sm"
          className="-ml-2 self-start text-muted"
          onClick={() => setCommenting(true)}
        >
          <MessageSquarePlus /> Add comment
        </Button>
      )}
    </div>
  )
}

function useEvaluationForm(initial: Record<string, string> = {}) {
  const [scores, setScores] = useState<Record<string, string>>(initial)
  const [recommendation, setRecommendation] = useState<string | null>(null)
  const scored = RUBRIC.filter((c) => scores[c.id]).length
  return {
    scores,
    setScore: (id: string, value: string) => setScores((s) => ({ ...s, [id]: value })),
    recommendation,
    setRecommendation,
    scored,
    complete: scored === RUBRIC.length && recommendation !== null,
  }
}

export function EvaluateSheet({ trigger }: { trigger?: ReactNode }) {
  const [open, setOpen] = useState(false)
  const form = useEvaluationForm({ value: '4' })
  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild>{trigger ?? <Button variant="primary">Evaluate</Button>}</SheetTrigger>
      <SheetContent size="md">
        <SheetHeader>
          <SheetTitle>Evaluate idea</SheetTitle>
          <SheetDescription>
            Self-serve returns portal · Scores from others stay hidden until you submit.
          </SheetDescription>
        </SheetHeader>
        <SheetBody>
          {RUBRIC.map((criterion) => (
            <EvaluateCriterionRow
              key={criterion.id}
              criterion={criterion}
              value={form.scores[criterion.id] ?? null}
              onValueChange={(value) => form.setScore(criterion.id, value)}
            />
          ))}
          <div className="mt-6 flex flex-col gap-3 rounded-lg bg-background p-4">
            <span id="overall-label" className="text-base font-medium text-primary">
              Overall recommendation
            </span>
            <SegmentedControl
              variant="accent"
              fullWidth
              aria-labelledby="overall-label"
              options={[
                { value: 'go', label: 'Go', description: 'Take it forward to a proposal' },
                { value: 'maybe', label: 'Maybe', description: 'Promising, but needs more work' },
                { value: 'no', label: 'No', description: 'Don’t pursue this now' },
              ]}
              value={form.recommendation}
              onValueChange={form.setRecommendation}
              guidancePlaceholder="Go, Maybe or No?"
            />
          </div>
        </SheetBody>
        <SheetFooter>
          <span className="mr-auto text-sm text-muted tabular-nums">
            {form.scored} of {RUBRIC.length} scored
          </span>
          <Button variant="ghost" onClick={() => setOpen(false)}>
            Save draft
          </Button>
          <Button
            variant="primary"
            disabled={!form.complete}
            onClick={() => {
              setOpen(false)
              toast.success('Evaluation submitted', {
                description: 'Other evaluators’ scores are now visible.',
              })
            }}
          >
            Submit
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  )
}

export function EvaluateExample() {
  const form = useEvaluationForm({ value: '4' })
  return (
    <div className="flex flex-col">
      {RUBRIC.slice(0, 2).map((criterion) => (
        <EvaluateCriterionRow
          key={criterion.id}
          criterion={criterion}
          value={form.scores[criterion.id] ?? null}
          onValueChange={(value) => form.setScore(criterion.id, value)}
        />
      ))}
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* List row & board card                                               */
/* ------------------------------------------------------------------ */

export function IdeaListRow({ idea }: { idea: SampleIdea }) {
  const owner = idea.ownerId ? person(idea.ownerId) : null
  return (
    <a
      href="#idea-sidebar"
      className="group flex h-11 items-center gap-3 border-b border-subtle px-4 transition-colors duration-100 last:border-0 hover:bg-subtle focus-visible:-outline-offset-2"
    >
      <StatusDot tone={statusTone(idea.status, idea.resolution)} />
      <span className="hidden w-11 shrink-0 text-xs text-muted tabular-nums sm:block">
        {idea.key}
      </span>
      <span className="min-w-0 truncate text-sm font-medium text-primary">{idea.title}</span>
      <span className="hidden shrink-0 gap-1 lg:flex">
        {idea.tags.map((tag) => (
          <Badge key={tag} variant="outline">
            {tag}
          </Badge>
        ))}
      </span>
      <span className="ml-auto flex shrink-0 items-center gap-4">
        {idea.evaluatorIds.length > 0 && (
          <ProgressTicks
            className="hidden md:inline-flex"
            done={idea.submitted}
            total={idea.evaluatorIds.length}
          />
        )}
        <ScoreBadge score={idea.score} size="sm" />
        {owner ? (
          <Avatar name={owner.name} src={owner.src} size="sm" />
        ) : (
          <span
            className="size-6 rounded-full border border-dashed border-strong"
            aria-label="No owner"
            role="img"
          />
        )}
        <span className="hidden w-16 text-right text-xs text-muted sm:block">{idea.updated}</span>
      </span>
    </a>
  )
}

export function BoardCard({ idea, dragging = false }: { idea: SampleIdea; dragging?: boolean }) {
  const owner = idea.ownerId ? person(idea.ownerId) : null
  return (
    <a
      href="#idea-sidebar"
      className={cn(
        'flex flex-col gap-2.5 rounded-lg border bg-surface p-3 transition-[border-color,box-shadow] duration-150 hover:border-strong',
        dragging && 'rotate-1 border-strong shadow-raised',
      )}
    >
      <span className="flex items-center justify-between gap-2">
        <span className="text-xs text-muted tabular-nums">{idea.key}</span>
        <ScoreBadge score={idea.score} size="sm" />
      </span>
      <span className="line-clamp-2 text-sm font-medium text-primary">{idea.title}</span>
      <span className="flex flex-wrap gap-1">
        {idea.tags.map((tag) => (
          <Badge key={tag}>{tag}</Badge>
        ))}
      </span>
      <span className="flex items-center justify-between gap-2 pt-0.5">
        {idea.evaluatorIds.length > 0 ? (
          <ProgressTicks done={idea.submitted} total={idea.evaluatorIds.length} />
        ) : (
          <Badge variant="warning">Needs evaluators</Badge>
        )}
        {owner ? (
          <Avatar name={owner.name} src={owner.src} size="sm" />
        ) : (
          <span className="text-xs text-muted">No owner</span>
        )}
      </span>
    </a>
  )
}

export function BoardExample() {
  const columns = [
    { status: 'new' as const, ideas: IDEAS.filter((i) => i.status === 'new') },
    { status: 'evaluating' as const, ideas: IDEAS.filter((i) => i.status === 'evaluating') },
    {
      status: 'shortlisted' as const,
      ideas: IDEAS.filter((i) => i.status === 'shortlisted' || i.status === 'proposal'),
    },
  ]
  return (
    <div className="grid gap-3 overflow-x-auto sm:grid-cols-3">
      {columns.map((column) => (
        <div
          key={column.status}
          className="flex min-w-56 flex-col gap-2 rounded-lg bg-background p-2"
        >
          <div className="flex items-center gap-2 px-1.5 py-1">
            <StatusBadge status={column.status} variant="plain" />
            <span className="text-sm text-muted tabular-nums">{column.ideas.length}</span>
          </div>
          {column.ideas.map((idea, index) => (
            <BoardCard
              key={idea.id}
              idea={idea}
              dragging={column.status === 'shortlisted' && index === 1}
            />
          ))}
        </div>
      ))}
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* Idea sidebar                                                        */
/* ------------------------------------------------------------------ */

function Property({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[6.5rem_minmax(0,1fr)] items-center gap-3">
      <dt className="text-sm text-muted">{label}</dt>
      <dd className="flex min-w-0 items-center gap-2 text-sm text-primary">{children}</dd>
    </div>
  )
}

export function IdeaSidebar({ blind }: { blind: boolean }) {
  const idea = IDEAS[0]
  if (!idea) return null
  const owner = person('u1')
  const evaluators = [
    { ...person('u2'), done: true },
    { ...person('u3'), done: true },
    { ...person('u4'), done: false },
    { ...person('ai'), done: true },
  ]
  return (
    <aside aria-label="Idea details" className="flex w-full flex-col gap-6">
      <dl className="flex flex-col gap-3">
        <Property label="Status">
          <StatusBadge status="evaluating" />
        </Property>
        <Property label="Owner">
          <Avatar name={owner.name} src={owner.src} size="xs" />
          <span className="truncate">{owner.name}</span>
        </Property>
        <Property label="Due">
          <CalendarDays aria-hidden="true" className="size-4 text-muted" />
          Oct 7 <span className="text-muted">· in 7 days</span>
        </Property>
        <Property label="Tags">
          <span className="flex flex-wrap gap-1">
            {idea.tags.map((tag) => (
              <Badge key={tag}>{tag}</Badge>
            ))}
          </span>
        </Property>
      </dl>

      <section
        aria-labelledby="evaluators-heading"
        className="flex flex-col gap-2.5 border-t border-subtle pt-5"
      >
        <div className="flex items-center justify-between">
          <h3 id="evaluators-heading" className="text-sm font-medium text-primary">
            Evaluators
          </h3>
          <ProgressTicks done={3} total={4} />
        </div>
        <ul className="flex flex-col gap-2">
          {evaluators.map((evaluator) => (
            <li key={evaluator.id} className="flex items-center gap-2.5 text-sm">
              <Avatar
                name={evaluator.name}
                src={evaluator.src}
                isAgent={evaluator.isAgent}
                size="sm"
              />
              <span className="min-w-0 flex-1 truncate text-primary">{evaluator.name}</span>
              {evaluator.isAgent && <span className="text-xs text-muted">not in score</span>}
              {evaluator.done ? (
                <Check aria-label="Submitted" className="size-4 text-success" />
              ) : (
                <Clock aria-label="Pending" className="size-4 text-muted" />
              )}
            </li>
          ))}
        </ul>
      </section>

      <section
        aria-labelledby="score-heading"
        className="flex flex-col gap-4 border-t border-subtle pt-5"
      >
        <div className="flex items-center justify-between gap-2">
          <h3 id="score-heading" className="text-sm font-medium text-primary">
            Score
          </h3>
          {!blind && (
            <Badge variant="warning" className="animate-reveal">
              <TriangleAlert /> High disagreement
            </Badge>
          )}
        </div>
        {blind ? (
          <div className="flex flex-col items-start gap-3 rounded-lg bg-background p-4">
            <span className="flex items-center gap-2 text-sm font-medium text-primary">
              <Lock aria-hidden="true" className="size-4 text-muted" /> Scores are hidden
            </span>
            <p className="text-sm text-muted">
              Submit your own evaluation first so others’ scores don’t anchor yours.
            </p>
            <EvaluateSheet
              trigger={
                <Button variant="primary" size="sm">
                  Evaluate
                </Button>
              }
            />
          </div>
        ) : (
          <>
            <div className="flex animate-reveal items-baseline gap-2">
              <span className="text-3xl font-semibold text-primary tabular-nums">3.8</span>
              <span className="text-sm text-muted">/ 5 · 3 evaluations</span>
            </div>
            <div className="flex flex-col gap-3.5">
              {RUBRIC.map((criterion, index) => {
                const result = CRITERION_RESULTS[criterion.id]
                if (!result) return null
                return (
                  <ScoreBar
                    key={criterion.id}
                    reveal
                    style={{ animationDelay: `${index * 40}ms` }}
                    label={criterion.name}
                    value={result.value}
                    min={result.min}
                    max={result.max}
                    disagreement={result.max - result.min >= 2}
                  />
                )
              })}
            </div>
            <p className="flex items-center gap-1.5 text-xs text-muted">
              <Sparkles aria-hidden="true" className="size-3.5" /> AI evaluation excluded from the
              aggregate
            </p>
          </>
        )}
      </section>
    </aside>
  )
}
