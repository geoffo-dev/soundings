import { ChevronRight, Lock, TriangleAlert } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import { useBidComparison, useSectionAssessments } from '@/api/bids'
import type { BidCall, BidCallSection, BidCallView, BidDetail, BidSectionScore } from '@/api/types'
import { AiBadge } from '@/components/ui/ai-badge'
import { Avatar } from '@/components/ui/avatar'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { RelativeTime } from '@/components/ui/relative-time'
import { Skeleton, SkeletonGroup } from '@/components/ui/skeleton'
import { useIdeaPage } from '@/features/idea/idea-context'
import { visibleText } from '@/lib/visible-text'
import { cn } from '@/lib/utils'

import { formatPoints, progressText } from './bid-copy'
import { Evidence } from './must-haves'

type CallWithView = BidCallView & { call: NonNullable<BidCallView['call']> }

/** What the disagreement mark means, said once under the scores (UX review m8). */
export const DISAGREEMENT_NOTE =
  'Disagree: two assessors’ scores on a question differ by 2 or more.'

/**
 * One section of one bid as you may see it (`get_bid_section_assessments`): each
 * question's counted scores (mean, range, how many, disagreement), every submitted
 * assessment with its comments and answers, and the AI's scores with their quotes. Blind:
 * while you still owe this section for this bid the API sends nothing ("Hidden until you
 * submit"). Used by assessors after submitting and by call managers in the bid sheet.
 */
export function SectionResults({
  bid,
  section,
  call,
  headingId,
  title = 'Everyone’s scores',
  onOpenQuote,
}: {
  bid: BidDetail
  section: BidCallSection
  call: BidCall
  headingId: string
  title?: string
  onOpenQuote?: (documentId: string, quote: string) => void
}) {
  const { ideaKey } = useIdeaPage()
  const results = useSectionAssessments(ideaKey, bid.id, section.id)
  return (
    <>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3
          id={headingId}
          tabIndex={-1}
          className="text-base font-semibold text-primary outline-none"
        >
          {title}
        </h3>
        {results.data?.section_score != null && (
          <span className="text-sm text-secondary">
            Section score{' '}
            <span className="font-semibold text-primary tabular-nums">
              {formatPoints(results.data.section_score)}
            </span>
            <span className="text-muted"> / 100</span>
          </span>
        )}
      </div>
      <SectionResultsBody bid={bid} section={section} call={call} onOpenQuote={onOpenQuote} />
    </>
  )
}

function SectionResultsBody({
  bid,
  section,
  call,
  onOpenQuote,
}: {
  bid: BidDetail
  section: BidCallSection
  call: BidCall
  onOpenQuote?: (documentId: string, quote: string) => void
}) {
  const { ideaKey } = useIdeaPage()
  const results = useSectionAssessments(ideaKey, bid.id, section.id)
  const questions = new Map(section.questions.map((q) => [q.id, q]))
  const documents = new Map(bid.documents.map((d) => [d.id, d]))

  if (results.isPending) {
    return (
      <SkeletonGroup label="Loading the scores" className="flex flex-col gap-2">
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-10 w-full" />
      </SkeletonGroup>
    )
  }
  if (results.isError) {
    return (
      <div role="alert" className="flex flex-wrap items-center gap-3 text-sm text-secondary">
        We couldn’t load the scores.
        <Button size="sm" variant="outline" onClick={() => void results.refetch()}>
          Try again
        </Button>
      </div>
    )
  }
  if (results.data.hidden) {
    return (
      <p className="flex items-start gap-2 text-sm text-muted">
        <Lock aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
        Hidden until you submit your own assessment of this section.
      </p>
    )
  }
  const disagreement = results.data.questions.some((q) => q.disagreement)
  const nobody = results.data.assessments.length === 0 && results.data.ai.length === 0
  return (
    <div className="flex flex-col gap-4">
      <ul className="flex flex-col gap-2" aria-label={`${section.title}: scores by question`}>
        {results.data.questions.map((stats) => {
          const question = questions.get(stats.question_id)
          if (!question) return null
          return (
            <li
              key={stats.question_id}
              className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 text-sm"
            >
              <span className="min-w-0 text-secondary">{question.text}</span>
              <span className="flex items-center gap-2 tabular-nums">
                {stats.disagreement && (
                  <Badge variant="warning">
                    <TriangleAlert aria-hidden="true" /> Disagree
                  </Badge>
                )}
                <span className="font-semibold text-primary">
                  {stats.mean?.toFixed(2) ?? '—'}
                  <span className="font-normal text-muted"> / 5</span>
                </span>
                {stats.type === 'price' ? (
                  <span className="text-xs text-muted">Scored from the price</span>
                ) : (
                  <>
                    {stats.min !== null && stats.max !== null && stats.min !== stats.max && (
                      <span className="text-muted">
                        ({stats.min}-{stats.max})
                      </span>
                    )}
                    <span className="text-xs text-muted">
                      {stats.count} {stats.count === 1 ? 'score' : 'scores'}
                    </span>
                  </>
                )}
              </span>
            </li>
          )
        })}
      </ul>
      {disagreement && <p className="text-xs text-muted">{DISAGREEMENT_NOTE}</p>}
      {nobody ? (
        <p className="text-sm text-muted">Nobody has submitted this section yet.</p>
      ) : (
        <ul
          className="flex flex-col divide-y divide-subtle rounded-lg border"
          aria-label={`${section.title}: assessments`}
        >
          {results.data.assessments.map((assessment) => (
            <li key={assessment.assessor.id} className="flex flex-col gap-2 px-4 py-3">
              <div className="flex items-center gap-2 text-sm">
                <Avatar
                  name={assessment.assessor.display_name}
                  src={assessment.assessor.avatar_url}
                  size="xs"
                  decorative
                />
                <span className="font-medium text-primary">{assessment.assessor.display_name}</span>
                <span className="text-xs text-muted">
                  <RelativeTime date={assessment.edited_at ?? assessment.submitted_at} />
                </span>
              </div>
              <ul className="flex flex-col gap-1.5 text-sm">
                {assessment.answers.map((answer) => {
                  const question = questions.get(answer.question_id)
                  if (!question || (answer.score === null && !answer.comment)) return null
                  return (
                    <li key={answer.question_id} className="flex flex-col">
                      <span className="flex items-baseline justify-between gap-3">
                        <span className="text-muted">{question.text}</span>
                        {answer.score !== null && (
                          <span className="font-medium text-primary tabular-nums">
                            {answer.score}
                          </span>
                        )}
                      </span>
                      {answer.comment && (
                        <span className="whitespace-pre-wrap text-secondary">{answer.comment}</span>
                      )}
                    </li>
                  )
                })}
              </ul>
            </li>
          ))}
          {results.data.ai.map((ai) => (
            <li key={ai.ai_assessment_id} className="flex flex-col gap-2 px-4 py-3">
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <Avatar name={ai.agent.display_name} isAgent size="xs" decorative />
                <span className="font-medium text-primary">{ai.agent.display_name}</span>
                <AiBadge />
                <span className="text-xs text-muted">
                  {ai.included ? 'Counted in the totals' : 'Not counted in the totals'}
                </span>
              </div>
              <ul className="flex flex-col gap-2 text-sm">
                {ai.scores.map((score) => (
                  <li key={score.question_id} className="flex flex-col gap-1">
                    <span className="flex items-baseline justify-between gap-3">
                      <span className="text-muted">{questions.get(score.question_id)?.text}</span>
                      <span className="font-medium text-primary tabular-nums">{score.score}</span>
                    </span>
                    {score.rationale && (
                      <span className="whitespace-pre-wrap text-secondary">
                        {visibleText(score.rationale)}
                      </span>
                    )}
                    <Evidence
                      evidence={score.evidence}
                      documents={documents}
                      onOpenQuote={onOpenQuote}
                    />
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ul>
      )}
      {call.status === 'assessing' && !callManager(bid) && (
        <p className="text-xs text-muted">Totals and the ranking are for the call’s managers.</p>
      )}
    </div>
  )
}

/** The bid's permissions say whether you are one of the call's managers. */
const callManager = (bid: BidDetail) => bid.permissions.can_view_ai

/**
 * Call managers read the assessments where they decide (UX review M4): each section of
 * this bid with its score and progress, opening to every assessor's scores and comments
 * and the AI's. `focusSection` opens that one and moves focus to it (from a comparison
 * cell). Blind for a manager who still owes a section, like everywhere else.
 */
export function BidAssessments({
  view,
  bid,
  focusSection,
  onOpenQuote,
}: {
  view: CallWithView
  bid: BidDetail
  focusSection?: string
  onOpenQuote?: (documentId: string, quote: string) => void
}) {
  const { ideaKey } = useIdeaPage()
  const { call } = view
  const comparison = useBidComparison(ideaKey)
  const row = comparison.data?.rows.find((r) => r.bid.id === bid.id)
  const cells = new Map((row?.sections ?? []).map((cell) => [cell.section_id, cell]))
  const sections = call.template.sections

  return (
    <section aria-labelledby={`assessments-${bid.id}`} className="flex flex-col gap-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 id={`assessments-${bid.id}`} className="text-base font-semibold text-primary">
          Assessments
        </h3>
        <span className="text-sm text-muted tabular-nums">
          {progressText(bid.progress)}
          {row && !row.total_hidden && row.total !== null && (
            <>
              {' · '}
              <span className="text-secondary">
                Total <span className="font-semibold text-primary">{formatPoints(row.total)}</span>
              </span>
            </>
          )}
        </span>
      </div>
      <ul className="flex flex-col divide-y divide-subtle rounded-lg border">
        {sections.map((section) => (
          <SectionDisclosure
            key={section.id}
            bid={bid}
            call={call}
            section={section}
            cell={cells.get(section.id)}
            focus={focusSection === section.id}
            onOpenQuote={onOpenQuote}
          />
        ))}
      </ul>
    </section>
  )
}

function SectionDisclosure({
  bid,
  call,
  section,
  cell,
  focus,
  onOpenQuote,
}: {
  bid: BidDetail
  call: BidCall
  section: BidCallSection
  cell: BidSectionScore | undefined
  focus: boolean
  onOpenQuote?: (documentId: string, quote: string) => void
}) {
  const [open, setOpen] = useState(focus)
  const [focused, setFocused] = useState(focus)
  if (focus !== focused) {
    setFocused(focus)
    if (focus) setOpen(true)
  }
  const button = useRef<HTMLButtonElement>(null)
  const bodyId = `section-${bid.id}-${section.id}`
  useEffect(() => {
    if (!focus) return
    // After the sheet's own opening focus.
    const timer = window.setTimeout(() => {
      button.current?.focus({ preventScroll: true })
      button.current?.scrollIntoView({ block: 'start' })
    }, 50)
    return () => window.clearTimeout(timer)
  }, [focus])

  const facts = cell?.hidden
    ? 'Hidden until you submit'
    : [
        cell?.score != null ? `${formatPoints(cell.score)} / 100` : null,
        cell ? progressText(cell.progress) : null,
      ]
        .filter(Boolean)
        .join(' · ')

  return (
    <li className="flex flex-col">
      <h4 className="text-sm font-medium text-primary">
        <button
          ref={button}
          type="button"
          aria-expanded={open}
          aria-controls={bodyId}
          onClick={() => setOpen((value) => !value)}
          className="flex w-full flex-wrap items-center gap-x-3 gap-y-1 px-4 py-3 text-left hover:bg-subtle"
        >
          <ChevronRight
            aria-hidden="true"
            className={cn(
              'size-4 shrink-0 text-muted transition-transform duration-150',
              open && 'rotate-90',
            )}
          />
          <span className="min-w-0 flex-1">
            {section.title} <span className="font-normal text-muted">· {section.weight}%</span>
          </span>
          {cell?.disagreement && !cell.hidden && (
            <Badge variant="warning">
              <TriangleAlert aria-hidden="true" /> Disagree
            </Badge>
          )}
          <span className="text-sm font-normal text-secondary tabular-nums">
            {cell?.hidden && <Lock aria-hidden="true" className="mr-1 inline size-3.5" />}
            {facts}
          </span>
        </button>
      </h4>
      {open && (
        <div id={bodyId} className="border-t border-subtle px-4 py-3">
          <SectionResultsBody bid={bid} section={section} call={call} onOpenQuote={onOpenQuote} />
        </div>
      )}
    </li>
  )
}
