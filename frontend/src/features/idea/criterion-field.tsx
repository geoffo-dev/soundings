import { CircleAlert, CircleHelp, MessageSquarePlus, ThumbsDown, ThumbsUp } from 'lucide-react'
import { useEffect, useId, useRef, useState, type KeyboardEvent } from 'react'

import type { Recommendation, RubricCriterion } from '@/api/types'
import { Button } from '@/components/ui/button'
import {
  SCORE_GUIDANCE_PLACEHOLDER,
  SegmentedControl,
  type SegmentedOption,
} from '@/components/ui/segmented-control'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/utils'

import {
  COMMENT_LIMITS,
  guidanceFor,
  RECOMMENDATION_HINTS,
  RECOMMENDATION_LABELS,
  RECOMMENDATIONS,
  SCORES,
  type CriterionEntry,
  type Score,
} from './evaluation-form'

/** "2" or "1.5" — rubric weights are 0.01–10. */
function formatWeight(weight: number): string {
  return Number.isInteger(weight) ? String(weight) : String(Number(weight.toFixed(2)))
}

export interface CriterionFieldProps {
  criterion: RubricCriterion
  entry: CriterionEntry
  onChange: (entry: CriterionEntry) => void
  /** Show the weight (only when the rubric's weights differ). */
  showWeight: boolean
  /** "Pick a score" after a submit attempt left it empty. */
  missing: boolean
  readOnly: boolean
  /** "Hover or focus a score to see what it means": once, under the first criterion. */
  showHint?: boolean
}

/**
 * One rubric criterion in the evaluate sheet: name, one line of description,
 * a 1–5 radio group with the rubric's guidance (hover/focus on desktop, tap on
 * touch; 1–5 and ←/→ from the keyboard) and an optional comment.
 */
export function CriterionField({
  criterion,
  entry,
  onChange,
  showWeight,
  missing,
  readOnly,
  showHint = true,
}: CriterionFieldProps) {
  const id = useId()
  const nameId = `${id}-name`
  const descriptionId = `${id}-description`
  const errorId = `${id}-error`
  const [commenting, setCommenting] = useState(() => entry.comment.trim() !== '')
  const commentRef = useRef<HTMLTextAreaElement>(null)
  const wantFocus = useRef(false)
  useEffect(() => {
    if (!commenting || !wantFocus.current) return
    wantFocus.current = false
    commentRef.current?.focus()
  }, [commenting])
  const guidance = guidanceFor(criterion)
  const options: SegmentedOption<`${Score}`>[] = SCORES.map((score) => ({
    value: `${score}`,
    label: String(score),
    description: guidance[score],
  }))

  return (
    <div
      data-criterion={criterion.id}
      className="flex scroll-mt-4 flex-col gap-2.5 border-b border-subtle py-5 first:pt-1"
    >
      <div className="flex items-start justify-between gap-4">
        <div className="flex min-w-0 flex-col gap-0.5">
          <h3 id={nameId} className="text-base font-medium text-primary">
            {criterion.name}
          </h3>
          <p id={descriptionId} className="text-sm text-muted">
            {criterion.description}
            {criterion.inverted && (
              <>
                {criterion.description ? ' ' : ''}
                <span className="text-secondary">
                  Lower is better: a high score counts against the idea.
                </span>
              </>
            )}
          </p>
        </div>
        {showWeight && (
          <span className="shrink-0 pt-0.5 text-xs text-muted tabular-nums">
            Weight {formatWeight(criterion.weight)}
          </span>
        )}
      </div>
      <SegmentedControl
        variant="accent"
        size="score"
        fullWidth
        aria-labelledby={nameId}
        aria-describedby={missing ? `${descriptionId} ${errorId}` : descriptionId}
        options={options}
        value={entry.score === null ? null : `${entry.score}`}
        onValueChange={(value) => onChange({ ...entry, score: Number(value) as Score })}
        guidancePlaceholder={showHint ? SCORE_GUIDANCE_PLACEHOLDER : undefined}
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
      {commenting || entry.comment ? (
        <Textarea
          ref={commentRef}
          aria-label={`Comment on ${criterion.name} (optional)`}
          placeholder="What drove this score? (optional)"
          value={entry.comment}
          maxLength={COMMENT_LIMITS.criterion}
          minRows={2}
          maxRows={6}
          disabled={readOnly}
          onChange={(event) => onChange({ ...entry, comment: event.target.value })}
        />
      ) : (
        !readOnly && (
          <Button
            variant="ghost"
            size="sm"
            className="-ml-2 self-start text-muted"
            aria-label={`Add a comment on ${criterion.name}`}
            onClick={() => {
              wantFocus.current = true
              setCommenting(true)
            }}
          >
            <MessageSquarePlus />
            Add comment
          </Button>
        )
      )}
    </div>
  )
}

const RECOMMENDATION_ICONS = {
  go: <ThumbsUp aria-hidden="true" />,
  maybe: <CircleHelp aria-hidden="true" />,
  no: <ThumbsDown aria-hidden="true" />,
} as const

const RECOMMENDATION_KEYS: Record<string, Recommendation> = { g: 'go', m: 'maybe', n: 'no' }

export interface RecommendationFieldProps {
  value: Recommendation | null
  onValueChange: (value: Recommendation) => void
  comment: string
  onCommentChange: (comment: string) => void
  missing: boolean
  readOnly: boolean
}

/** Go / Maybe / No (G, M, N while focused) and the optional overall comment. */
export function RecommendationField({
  value,
  onValueChange,
  comment,
  onCommentChange,
  missing,
  readOnly,
}: RecommendationFieldProps) {
  const id = useId()
  const labelId = `${id}-label`
  const errorId = `${id}-error`
  const options: SegmentedOption<Recommendation>[] = RECOMMENDATIONS.map((option) => ({
    value: option,
    label: (
      <>
        {RECOMMENDATION_ICONS[option]}
        {RECOMMENDATION_LABELS[option]}
      </>
    ),
    ariaLabel: RECOMMENDATION_LABELS[option],
    description: RECOMMENDATION_HINTS[option],
  }))

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (readOnly || event.metaKey || event.ctrlKey || event.altKey) return
    if (!(event.target instanceof HTMLElement) || event.target.getAttribute('role') !== 'radio')
      return
    const choice = RECOMMENDATION_KEYS[event.key.toLowerCase()]
    if (!choice) return
    event.preventDefault()
    onValueChange(choice)
    event.currentTarget.querySelector<HTMLElement>(`[role="radio"][value="${choice}"]`)?.focus()
  }

  return (
    <div data-recommendation="" className="flex scroll-mt-4 flex-col gap-2.5 pt-5 pb-2">
      <div className="flex flex-col gap-0.5">
        <h3 id={labelId} className="text-base font-medium text-primary">
          Overall recommendation
        </h3>
        <p className="text-sm text-muted">Would you take this idea forward?</p>
      </div>
      {/* G / M / N choose while the group has focus (radios handle the rest). */}
      {/* eslint-disable-next-line jsx-a11y/no-static-element-interactions */}
      <div onKeyDown={onKeyDown}>
        <SegmentedControl
          variant="accent"
          size="score"
          fullWidth
          aria-labelledby={labelId}
          aria-describedby={missing ? errorId : undefined}
          options={options}
          value={value}
          onValueChange={onValueChange}
          guidancePlaceholder="Go, Maybe or No? (G, M or N)"
          disabled={readOnly}
          className={cn(
            missing &&
              '[&_[data-slot=segmented-control]]:ring-2 [&_[data-slot=segmented-control]]:ring-danger',
          )}
        />
      </div>
      {missing && (
        <p id={errorId} className="-mt-1 flex items-center gap-1.5 text-sm text-danger">
          <CircleAlert aria-hidden="true" className="size-3.5 shrink-0" />
          Choose Go, Maybe or No
        </p>
      )}
      <Textarea
        aria-label="Overall comment (optional)"
        placeholder="Overall comment (optional): what should the owner know?"
        value={comment}
        maxLength={COMMENT_LIMITS.overall}
        minRows={2}
        maxRows={10}
        disabled={readOnly}
        onChange={(event) => onCommentChange(event.target.value)}
      />
    </div>
  )
}
