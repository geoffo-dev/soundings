import {
  ArrowRight,
  CircleAlert,
  CircleCheck,
  CloudOff,
  FileText,
  Lock,
  TriangleAlert,
} from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'

import {
  useBid,
  useBids,
  useMyBidAssessment,
  useSaveMyBidAssessment,
  useSectionAssessments,
} from '@/api/bids'
import { describeError, hasErrorCode, isApiError } from '@/api/errors'
import type {
  BidCall,
  BidCallQuestion,
  BidCallSection,
  BidCallView,
  BidDetail,
  BidDocument,
  MyBidAssessment,
} from '@/api/types'
import { AiBadge } from '@/components/ui/ai-badge'
import { Avatar } from '@/components/ui/avatar'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Callout } from '@/components/ui/callout'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { EmptyState } from '@/components/ui/empty-state'
import { RelativeTime } from '@/components/ui/relative-time'
import { SegmentedControl, type SegmentedOption } from '@/components/ui/segmented-control'
import {
  Sheet,
  SheetBody,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Skeleton, SkeletonGroup } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'
import { toast } from '@/components/ui/toaster'
import { useIdeaPage } from '@/features/idea/idea-context'
import { LiveRegion, useLiveRegion } from '@/features/idea/live-region'
import { useMediaQuery } from '@/lib/media'
import { visibleText } from '@/lib/visible-text'
import { cn } from '@/lib/utils'

import { formatPoints, formatPrice } from './bid-copy'
import { pricingAudience } from './bid-documents'
import { DocumentText, DocumentTextDialog } from './document-text'
import { Evidence } from './must-haves'

type CallWithView = BidCallView & { call: NonNullable<BidCallView['call']> }

const LG_UP = '(min-width: 64rem)'
const SCORES = [0, 1, 2, 3, 4, 5] as const

interface Entry {
  score: number | null
  comment: string
}
type Answers = Record<string, Entry>

function answersOf(section: BidCallSection, mine: MyBidAssessment | undefined): Answers {
  const saved = new Map((mine?.answers ?? []).map((a) => [a.question_id, a]))
  const out: Answers = {}
  for (const q of section.questions) {
    if (q.type === 'price') continue
    const a = saved.get(q.id)
    out[q.id] = { score: a?.score ?? null, comment: a?.comment ?? '' }
  }
  return out
}

function sameAnswers(a: Answers, b: Answers): boolean {
  const keys = Object.keys(a)
  return keys.every((k) => a[k]?.score === b[k]?.score && a[k]?.comment === b[k]?.comment)
}

/**
 * Your assessment of one section of one bid (contract-phase10 §7.2), opened with
 * `?tab=bids&bid=<id>&assess=<section>`: each question with its guidance and the call's
 * 0-5 anchors, a comment, Save draft and Submit. On wide screens the bid's documents and
 * their text sit beside it; on phones they open over it. Blind: nobody else's scores show
 * until you submit this section for this bid; then you see theirs and the AI's.
 */
export function AssessmentSheet({
  view,
  bidId,
  sectionId,
  onOpenChange,
  onSwitch,
}: {
  view: CallWithView
  bidId: string | undefined
  sectionId: string | undefined
  onOpenChange: (open: boolean) => void
  onSwitch: (bidId: string, sectionId: string) => void
}) {
  const { ideaKey } = useIdeaPage()
  const open = Boolean(bidId && sectionId)
  const section = view.call.template.sections.find((s) => s.id === sectionId)
  const mine = useMyBidAssessment(ideaKey, bidId ?? null, sectionId ?? null, { enabled: open })
  const bid = useBid(ideaKey, bidId ?? null, { enabled: open })
  const guard = useRef<(() => boolean) | null>(null)
  const [leaving, setLeaving] = useState<null | (() => void)>(null)

  // Closing with unsaved changes asks first (the form registers its check).
  const close = (next: boolean) => {
    if (next) {
      onOpenChange(true)
      return
    }
    if (guard.current?.()) setLeaving(() => () => onOpenChange(false))
    else onOpenChange(false)
  }
  const error = mine.error ?? bid.error
  const missing = isApiError(error) && (error.status === 404 || error.status === 403)

  return (
    <Sheet open={open} onOpenChange={close}>
      <SheetContent size="xl" aria-describedby={undefined}>
        {section && mine.data && bid.data ? (
          <AssessmentForm
            key={`${bid.data.id}:${section.id}`}
            view={view}
            bid={bid.data}
            section={section}
            mine={mine.data}
            guardRef={guard}
            onSwitch={(nextBid, nextSection) => {
              if (guard.current?.()) setLeaving(() => () => onSwitch(nextBid, nextSection))
              else onSwitch(nextBid, nextSection)
            }}
          />
        ) : error || (open && !section) ? (
          <>
            <SheetHeader>
              <SheetTitle>
                {missing || !section ? 'Assessment not found' : 'Couldn’t load the assessment'}
              </SheetTitle>
            </SheetHeader>
            <SheetBody>
              <EmptyState
                role="alert"
                size="compact"
                icon={<CloudOff />}
                title={
                  missing || !section
                    ? 'You can’t assess this any more'
                    : 'We couldn’t load your assessment'
                }
                description={
                  missing || !section
                    ? 'The bid may have been rejected or deleted, or you no longer assess this section.'
                    : describeError(error).title
                }
                action={
                  missing || !section ? (
                    <Button variant="secondary" onClick={() => onOpenChange(false)}>
                      Back to the bids
                    </Button>
                  ) : (
                    <Button
                      variant="secondary"
                      onClick={() => {
                        void mine.refetch()
                        void bid.refetch()
                      }}
                    >
                      Try again
                    </Button>
                  )
                }
              />
            </SheetBody>
          </>
        ) : (
          <>
            <SheetHeader>
              <SheetTitle className="sr-only">Loading the assessment</SheetTitle>
              <Skeleton className="h-5 w-64" />
              <Skeleton className="h-3.5 w-40" />
            </SheetHeader>
            <SheetBody>
              <SkeletonGroup label="Loading the assessment" className="flex flex-col gap-6">
                {[0, 1, 2].map((i) => (
                  <div key={i} className="flex flex-col gap-2">
                    <Skeleton className="h-4 w-3/5" />
                    <Skeleton className="h-9 w-full" />
                  </div>
                ))}
              </SkeletonGroup>
            </SheetBody>
          </>
        )}
      </SheetContent>
      <Dialog open={leaving !== null} onOpenChange={(next) => !next && setLeaving(null)}>
        <DialogContent size="sm">
          <DialogHeader>
            <DialogTitle>Leave without saving?</DialogTitle>
            <DialogDescription>
              Your changes to this assessment haven’t been saved. Save a draft first to keep them.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setLeaving(null)}>
              Keep editing
            </Button>
            <Button
              variant="destructive"
              onClick={() => {
                const then = leaving
                guard.current = null
                setLeaving(null)
                then?.()
              }}
            >
              Discard changes
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Sheet>
  )
}

function AssessmentForm({
  view,
  bid,
  section,
  mine,
  guardRef,
  onSwitch,
}: {
  view: CallWithView
  bid: BidDetail
  section: BidCallSection
  mine: MyBidAssessment
  guardRef: React.RefObject<(() => boolean) | null>
  onSwitch: (bidId: string, sectionId: string) => void
}) {
  const { ideaKey } = useIdeaPage()
  const { call } = view
  const save = useSaveMyBidAssessment(ideaKey)
  const bids = useBids(ideaKey)
  const wide = useMediaQuery(LG_UP)
  const { message, announce } = useLiveRegion()
  const [baseline, setBaseline] = useState(() => answersOf(section, mine))
  const [answers, setAnswers] = useState(baseline)
  const [tried, setTried] = useState(false)
  const [reading, setReading] = useState<BidDocument | null>(null)
  const formRef = useRef<HTMLDivElement>(null)
  const dirty = !sameAnswers(answers, baseline)
  const submitted = mine.state === 'submitted'
  const editable = mine.can_edit
  useEffect(() => {
    guardRef.current = () => dirty && editable
    return () => {
      guardRef.current = null
    }
  }, [dirty, editable, guardRef])

  const scoreQuestions = section.questions.filter((q) => q.type === 'score')
  const unscored = scoreQuestions.filter((q) => answers[q.id]?.score === null)
  const scoredCount = scoreQuestions.length - unscored.length

  // The next item of your queue (bids in the order received, your sections in order).
  const next = useMemo(() => {
    const rows = (bids.data?.items ?? [])
      .filter((b) => b.status !== 'rejected')
      .flatMap((b) => b.my_sections.map((s) => ({ bid: b, section: s })))
    const at = rows.findIndex((r) => r.bid.id === bid.id && r.section.section.id === section.id)
    const after = [...rows.slice(at + 1), ...rows.slice(0, Math.max(at, 0))]
    return after.find((r) => r.section.state !== 'submitted')
  }, [bids.data, bid.id, section.id])

  const send = (submit: boolean) => {
    setTried(submit)
    if (submit && unscored.length > 0) {
      announce(
        `${unscored.length} ${unscored.length === 1 ? 'question needs' : 'questions need'} a score.`,
      )
      const first = unscored[0]
      if (first) {
        formRef.current
          ?.querySelector<HTMLElement>(`[data-question="${first.id}"] [role="radio"]`)
          ?.focus()
      }
      return
    }
    const body = {
      answers: Object.entries(answers).map(([question_id, entry]) => ({
        question_id,
        score: entry.score,
        comment: entry.comment.trim(),
      })),
      submit: submit || submitted,
    }
    save.mutate(
      { bidId: bid.id, sectionId: section.id, body },
      {
        onSuccess: (saved) => {
          const fresh = answersOf(section, saved)
          setBaseline(fresh)
          setAnswers(fresh)
          setTried(false)
          if (submitted) {
            toast.success('Changes saved')
          } else if (saved.state === 'submitted') {
            toast.success(`${section.title} submitted for ${bid.bidder}`, {
              description: 'You can now see the other assessors’ scores for it.',
            })
            announce('Submitted. The other assessors’ scores are shown below.')
          } else {
            toast.success('Draft saved', { description: 'Only you can see it.' })
          }
        },
      },
    )
  }

  const error = save.error
  const problem =
    error &&
    (hasErrorCode(error, 'assessment_incomplete')
      ? 'Score every question to submit.'
      : (() => {
          const { title, description } = describeError(error)
          return description ? `${title}. ${description}` : title
        })())

  return (
    <>
      <SheetHeader>
        <SheetTitle className="pr-8 break-words">
          {section.title} <span className="font-normal text-muted">· {bid.bidder}</span>
        </SheetTitle>
        <SheetDescription asChild>
          <div className="flex flex-wrap items-center gap-2 text-sm text-muted">
            {submitted ? (
              <Badge variant="success">
                <CircleCheck aria-hidden="true" /> Submitted
              </Badge>
            ) : mine.state === 'draft' ? (
              <Badge variant="neutral">Draft</Badge>
            ) : (
              <Badge variant="neutral">Not started</Badge>
            )}
            {mine.submitted_at && (
              <span>
                Submitted <RelativeTime date={mine.submitted_at} />
                {mine.edited_at && (
                  <>
                    , edited <RelativeTime date={mine.edited_at} />
                  </>
                )}
              </span>
            )}
            <span className="tabular-nums">
              {scoredCount} of {scoreQuestions.length} scored
            </span>
          </div>
        </SheetDescription>
      </SheetHeader>
      <SheetBody
        className={cn('flex flex-col gap-8', wide && 'grid grid-cols-2 gap-6 overflow-hidden py-0')}
      >
        <div
          ref={formRef}
          className={cn('flex flex-col gap-6', wide && 'min-h-0 overflow-y-auto py-5 pr-1')}
        >
          {!editable && !submitted && (
            <Callout tone="info" icon={<Lock />} title="You can’t assess this now">
              {call.status === 'assessing'
                ? 'This bid is rejected.'
                : 'Assessments open once the call is closed to new bids.'}
            </Callout>
          )}
          {problem && <Callout tone="danger" role="alert" title={problem} />}
          {section.guidance && <p className="text-sm text-secondary">{section.guidance}</p>}
          <ol className="flex flex-col gap-6" aria-label="Questions">
            {section.questions.map((question) => (
              <QuestionField
                key={question.id}
                call={call}
                bid={bid}
                question={question}
                entry={answers[question.id]}
                readOnly={!editable}
                missing={tried && question.type === 'score' && answers[question.id]?.score === null}
                onChange={(entry) => setAnswers((all) => ({ ...all, [question.id]: entry }))}
              />
            ))}
          </ol>
          {submitted ? (
            <SectionResults bidId={bid.id} section={section} call={call} bid={bid} />
          ) : (
            <p className="flex items-start gap-2 text-sm text-muted">
              <Lock aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
              The other assessors’ scores for this section stay hidden from you until you submit.
            </p>
          )}
          {!wide && <DocumentList call={call} bid={bid} onRead={setReading} />}
        </div>
        {wide && <DocumentsPane ideaKey={ideaKey} call={call} bid={bid} />}
      </SheetBody>
      <SheetFooter className="flex-wrap justify-between">
        <div className="min-w-0">
          {submitted && next && !dirty && (
            <Button
              variant="ghost"
              onClick={() => onSwitch(next.bid.id, next.section.section.id)}
              aria-label={`Next: ${next.bid.bidder}, ${next.section.section.title}`}
            >
              Next: {next.bid.bidder} <ArrowRight />
            </Button>
          )}
        </div>
        {editable && (
          <div className="flex gap-2">
            {submitted ? (
              <Button
                variant="primary"
                disabled={!dirty}
                loading={save.isPending}
                onClick={() => send(true)}
              >
                Save changes
              </Button>
            ) : (
              <>
                <Button
                  variant="outline"
                  disabled={!dirty && mine.state !== 'invited'}
                  loading={save.isPending && !tried}
                  onClick={() => send(false)}
                >
                  Save draft
                </Button>
                <Button
                  variant="primary"
                  loading={save.isPending && tried}
                  onClick={() => send(true)}
                >
                  Submit
                </Button>
              </>
            )}
          </div>
        )}
      </SheetFooter>
      <LiveRegion message={message} />
      <DocumentTextDialog
        ideaKey={ideaKey}
        bidId={bid.id}
        document={reading}
        onOpenChange={(open) => !open && setReading(null)}
      />
    </>
  )
}

function QuestionField({
  call,
  bid,
  question,
  entry,
  readOnly,
  missing,
  onChange,
}: {
  call: BidCall
  bid: BidDetail
  question: BidCallQuestion
  entry: Entry | undefined
  readOnly: boolean
  missing: boolean
  onChange: (entry: Entry) => void
}) {
  const nameId = `q-${question.id}`
  const errorId = `q-${question.id}-error`
  const guidanceId = `q-${question.id}-guidance`
  if (question.type === 'price') {
    return (
      <li data-question={question.id} className="flex flex-col gap-1.5">
        <h3 id={nameId} className="text-base font-medium text-primary">
          {question.text}
        </h3>
        <p className="text-sm text-muted">
          Scored automatically: the lowest qualified price ÷ this bid’s price × 5.{' '}
          {bid.price_hidden
            ? `Only ${pricingAudience(call)} see the price.`
            : bid.price !== null
              ? `This bid: ${formatPrice(bid.price, call.currency)}.`
              : 'No price was entered for this bid.'}
        </p>
      </li>
    )
  }
  const value = entry ?? { score: null, comment: '' }
  const options: SegmentedOption<`${number}`>[] = SCORES.map((score) => ({
    value: `${score}`,
    label: String(score),
    description: call.template.scale[score] ?? '',
  }))
  return (
    <li data-question={question.id} className="flex flex-col gap-2.5">
      <div className="flex items-start justify-between gap-4">
        <div className="flex min-w-0 flex-col gap-0.5">
          <h3 id={nameId} className="text-base font-medium text-primary">
            {question.text}
          </h3>
          {question.guidance && (
            <p id={guidanceId} className="text-sm text-muted">
              {question.guidance}
            </p>
          )}
        </div>
        {question.type === 'score' && (
          <span className="shrink-0 pt-0.5 text-xs text-muted tabular-nums">
            × {question.weight}
          </span>
        )}
      </div>
      {question.type === 'score' && (
        <>
          <SegmentedControl
            variant="accent"
            size="score"
            fullWidth
            aria-labelledby={nameId}
            aria-describedby={
              [question.guidance ? guidanceId : null, missing ? errorId : null]
                .filter(Boolean)
                .join(' ') || undefined
            }
            options={options}
            value={value.score === null ? null : `${value.score}`}
            onValueChange={(score) => onChange({ ...value, score: Number(score) })}
            guidancePlaceholder="Hover or focus a score to see what it means"
            disabled={readOnly}
            className={cn(
              missing &&
                '[&_[data-slot=segmented-control]]:ring-2 [&_[data-slot=segmented-control]]:ring-danger',
            )}
          />
          {missing && (
            <p id={errorId} className="-mt-1 flex items-center gap-1.5 text-sm text-danger">
              <CircleAlert aria-hidden="true" className="size-3.5 shrink-0" />
              Pick a score
            </p>
          )}
        </>
      )}
      <Textarea
        aria-label={
          question.type === 'comment'
            ? `Your answer: ${question.text}`
            : `Comment on ${question.text} (optional)`
        }
        placeholder={
          question.type === 'comment' ? 'Your answer (optional)' : 'Why this score? (optional)'
        }
        value={value.comment}
        maxLength={2000}
        minRows={2}
        maxRows={8}
        disabled={readOnly}
        onChange={(event) => onChange({ ...value, comment: event.target.value })}
      />
    </li>
  )
}

/** After you submit: everyone's submitted scores for the section, the spread and the AI's. */
function SectionResults({
  bidId,
  section,
  call,
  bid,
}: {
  bidId: string
  section: BidCallSection
  call: BidCall
  bid: BidDetail
}) {
  const { ideaKey } = useIdeaPage()
  const results = useSectionAssessments(ideaKey, bidId, section.id)
  const questions = new Map(section.questions.map((q) => [q.id, q]))
  const documents = new Map(bid.documents.map((d) => [d.id, d]))

  return (
    <section
      aria-labelledby={`results-${section.id}`}
      className="flex flex-col gap-4 border-t border-subtle pt-6"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 id={`results-${section.id}`} className="text-base font-semibold text-primary">
          Everyone’s scores
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
      {results.isPending ? (
        <SkeletonGroup label="Loading the scores" className="flex flex-col gap-2">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
        </SkeletonGroup>
      ) : results.isError ? (
        <div role="alert" className="flex flex-wrap items-center gap-3 text-sm text-secondary">
          We couldn’t load the scores.
          <Button size="sm" variant="outline" onClick={() => void results.refetch()}>
            Try again
          </Button>
        </div>
      ) : results.data.hidden ? (
        <p className="text-sm text-muted">Hidden until you submit.</p>
      ) : (
        <>
          <ul className="flex flex-col gap-2">
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
                    </span>
                    {stats.min !== null && stats.max !== null && stats.min !== stats.max && (
                      <span className="text-muted">
                        ({stats.min}-{stats.max})
                      </span>
                    )}
                    <span className="text-xs text-muted">
                      {stats.count} {stats.count === 1 ? 'score' : 'scores'}
                    </span>
                  </span>
                </li>
              )
            })}
          </ul>
          <ul
            className="flex flex-col divide-y divide-subtle rounded-lg border"
            aria-label="Assessments"
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
                  <span className="font-medium text-primary">
                    {assessment.assessor.display_name}
                  </span>
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
                          <span className="whitespace-pre-wrap text-secondary">
                            {answer.comment}
                          </span>
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
                      <Evidence evidence={score.evidence} documents={documents} />
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
          {call.status === 'assessing' && (
            <p className="text-xs text-muted">
              Totals and the ranking are for the call’s managers.
            </p>
          )}
        </>
      )}
    </section>
  )
}

/** Phones and narrow windows: the bid's documents, each opening its text over the sheet. */
function DocumentList({
  call,
  bid,
  onRead,
}: {
  call: BidCall
  bid: BidDetail
  onRead: (document: BidDocument) => void
}) {
  return (
    <section
      aria-labelledby={`docs-${bid.id}`}
      className="flex flex-col gap-2 border-t border-subtle pt-6"
    >
      <h3 id={`docs-${bid.id}`} className="text-base font-semibold text-primary">
        The bid’s documents
      </h3>
      {bid.documents.length === 0 ? (
        <p className="text-sm text-muted">No documents.</p>
      ) : (
        <ul className="flex flex-col divide-y divide-subtle rounded-lg border">
          {bid.documents.map((document) => (
            <li key={document.id} className="flex items-center gap-3 px-3 py-2">
              <FileText aria-hidden="true" className="size-4 shrink-0 text-muted" />
              <span className="min-w-0 flex-1 text-sm break-all text-primary">
                {document.filename}
              </span>
              <Button
                size="sm"
                variant="ghost"
                disabled={document.extraction.state !== 'done'}
                onClick={() => onRead(document)}
                aria-label={`Read the text of ${document.filename}`}
              >
                Read
              </Button>
            </li>
          ))}
        </ul>
      )}
      {bid.restricted_document_count > 0 && (
        <p className="flex items-start gap-2 text-sm text-muted">
          <Lock aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
          Pricing documents are present (restricted): only {pricingAudience(call)} can open them.
        </p>
      )}
    </section>
  )
}

/** Wide screens: the bid's documents beside the questions, one at a time. */
function DocumentsPane({ ideaKey, call, bid }: { ideaKey: string; call: BidCall; bid: BidDetail }) {
  const readable = bid.documents
  const [chosen, setChosen] = useState<string | null>(readable[0]?.id ?? null)
  const document = readable.find((d) => d.id === chosen) ?? readable[0]
  return (
    <aside
      aria-label="The bid’s documents"
      className="flex min-h-0 flex-col gap-3 border-l border-subtle py-5 pl-6"
    >
      <h3 className="text-base font-semibold text-primary">The bid’s documents</h3>
      {readable.length === 0 ? (
        <p className="text-sm text-muted">No documents.</p>
      ) : (
        <>
          <Select value={document?.id} onValueChange={setChosen}>
            <SelectTrigger aria-label="Document to read">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {readable.map((d) => (
                <SelectItem key={d.id} value={d.id}>
                  {d.filename}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {document && (
            <DocumentText
              key={document.id}
              ideaKey={ideaKey}
              bidId={bid.id}
              document={document}
              className="min-h-0 flex-1"
            />
          )}
        </>
      )}
      {bid.restricted_document_count > 0 && (
        <p className="flex items-start gap-2 text-xs text-muted">
          <Lock aria-hidden="true" className="mt-0.5 size-3.5 shrink-0" />
          Pricing documents are present (restricted): only {pricingAudience(call)} can open them.
        </p>
      )}
    </aside>
  )
}
