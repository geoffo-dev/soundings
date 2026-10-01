import { cva } from 'class-variance-authority'
import { RadioGroup as RadioGroupPrimitive } from 'radix-ui'
import { useId, useRef, useState, type KeyboardEvent, type ReactNode } from 'react'

import { useFieldContext } from '@/components/ui/field'
import { useCoarsePointer } from '@/lib/pointer'
import { cn } from '@/lib/utils'

/** Guidance placeholder for 1–5 score controls: "Hover…" with a mouse, "Tap…" on touch. */
export const SCORE_GUIDANCE_PLACEHOLDER = {
  pointer: 'Hover or focus a score to see what it means',
  touch: 'Tap a score to see what it means',
} as const

const quietFocus = new WeakSet<Element>()

/**
 * Focus an option without previewing its guidance, for focus the person didn't
 * move there themselves (e.g. "this still needs a score" after Submit): the
 * preview would read as if that option had been chosen.
 */
export function focusWithoutPreview(element: HTMLElement): void {
  quietFocus.add(element)
  element.focus()
  quietFocus.delete(element)
}

export interface SegmentedOption<T extends string = string> {
  value: T
  label: ReactNode
  /** Accessible name when `label` isn't plain text (e.g. an icon). */
  ariaLabel?: string
  /** Guidance shown under the control while the option is hovered, focused or selected. */
  description?: string
  disabled?: boolean
}

export interface SegmentedControlProps<T extends string> {
  options: readonly SegmentedOption<T>[]
  value: T | null | undefined
  onValueChange: (value: T) => void
  /** `score`: 1–5 rows in forms people fill on a phone (36px with a mouse, 44px on touch). */
  size?: 'sm' | 'md' | 'lg' | 'score'
  /** `accent` fills the selected segment with the brand colour (scores); `neutral` for view toggles. */
  variant?: 'neutral' | 'accent'
  /** Stretch segments to fill the container (recommended on phones). */
  fullWidth?: boolean
  /**
   * Text shown in the guidance line before anything is hovered or chosen. Pass
   * `{ pointer, touch }` to word it for mouse vs touch ("Hover…" / "Tap…"),
   * e.g. `SCORE_GUIDANCE_PLACEHOLDER`.
   */
  guidancePlaceholder?: string | { pointer: string; touch: string }
  name?: string
  disabled?: boolean
  required?: boolean
  className?: string
  'aria-label'?: string
  'aria-labelledby'?: string
  /** Extra description ids (e.g. a criterion's text or an error), added to the Field's. */
  'aria-describedby'?: string
}

const segment = cva(
  [
    'relative inline-flex min-w-0 items-center justify-center gap-1.5 rounded-[5px] font-medium whitespace-nowrap',
    'text-secondary transition-[background-color,color,box-shadow] duration-150',
    'hover:text-primary focus-visible:z-10 focus-visible:outline-offset-1',
    'disabled:cursor-not-allowed disabled:opacity-50',
    "[&_svg:not([class*='size-'])]:size-4",
  ],
  {
    variants: {
      size: {
        sm: 'h-6 min-w-7 px-2 text-xs',
        md: 'h-7 min-w-9 px-3 text-sm pointer-coarse:h-10 pointer-coarse:min-w-11',
        lg: 'h-10 min-w-11 px-4 text-base',
        score: 'h-9 min-w-11 px-3 text-base pointer-coarse:h-11',
      },
      variant: {
        neutral:
          'hover:bg-subtle data-[state=checked]:bg-surface data-[state=checked]:text-primary data-[state=checked]:shadow-[0_0_0_1px_var(--border)]',
        accent:
          'hover:bg-subtle data-[state=checked]:bg-accent data-[state=checked]:text-accent-foreground data-[state=checked]:hover:bg-accent-hover',
      },
      fullWidth: { true: 'flex-1', false: '' },
    },
  },
)

/**
 * A row of mutually exclusive options (radio semantics). Arrow keys move and
 * select (roving focus), Home/End jump, and typing an option's single-character
 * value (e.g. "4") selects it directly — ideal for 1–5 scoring.
 */
export function SegmentedControl<T extends string>({
  options,
  value,
  onValueChange,
  size = 'md',
  variant = 'neutral',
  fullWidth = false,
  guidancePlaceholder,
  name,
  disabled,
  required,
  className,
  ...aria
}: SegmentedControlProps<T>) {
  const field = useFieldContext()
  const id = useId()
  const [preview, setPreview] = useState<T | null>(null)
  const itemRefs = useRef(new Map<T, HTMLButtonElement>())
  const hasGuidance = options.some((option) => option.description)
  const coarse = useCoarsePointer()
  const shown = options.find((option) => option.value === (preview ?? value))
  const placeholder =
    typeof guidancePlaceholder === 'object'
      ? guidancePlaceholder[coarse ? 'touch' : 'pointer']
      : guidancePlaceholder
  const guidance = shown?.description ?? placeholder

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.metaKey || event.ctrlKey || event.altKey) return
    const match = options.find((option) => option.value === event.key && !option.disabled)
    if (!match) return
    event.preventDefault()
    onValueChange(match.value)
    itemRefs.current.get(match.value)?.focus()
  }

  return (
    <div
      className={cn('flex flex-col gap-1.5', fullWidth ? 'w-full' : 'w-fit max-w-full', className)}
    >
      <RadioGroupPrimitive.Root
        data-slot="segmented-control"
        orientation="horizontal"
        loop={false}
        value={value ?? ''}
        onValueChange={(next) => onValueChange(next as T)}
        name={name}
        disabled={disabled}
        required={required}
        aria-labelledby={
          aria['aria-labelledby'] ?? (aria['aria-label'] ? undefined : field?.labelId)
        }
        aria-label={aria['aria-label']}
        aria-describedby={
          [field?.describedBy, aria['aria-describedby']].filter(Boolean).join(' ') || undefined
        }
        onKeyDown={onKeyDown}
        className={cn(
          'flex gap-0.5 rounded-md bg-subtle p-0.5',
          fullWidth ? 'w-full' : 'scrollbar-none w-fit max-w-full overflow-x-auto',
        )}
      >
        {options.map((option) => (
          <RadioGroupPrimitive.Item
            key={option.value}
            ref={(node) => {
              if (node) itemRefs.current.set(option.value, node)
              else itemRefs.current.delete(option.value)
            }}
            value={option.value}
            disabled={option.disabled}
            aria-label={option.ariaLabel}
            aria-describedby={option.description ? `${id}-${option.value}-guidance` : undefined}
            onPointerEnter={() => setPreview(option.value)}
            onPointerLeave={() => setPreview(null)}
            onFocus={(event) => {
              if (!quietFocus.has(event.currentTarget)) setPreview(option.value)
            }}
            onBlur={() => setPreview(null)}
            className={segment({ size, variant, fullWidth })}
          >
            {option.label}
            {option.description && (
              <span id={`${id}-${option.value}-guidance`} hidden>
                {option.description}
              </span>
            )}
          </RadioGroupPrimitive.Item>
        ))}
      </RadioGroupPrimitive.Root>
      {hasGuidance && (
        <p
          aria-hidden="true"
          data-slot="segmented-guidance"
          className={cn(
            'min-h-5 text-sm text-muted transition-colors duration-150',
            preview !== null && preview !== value && 'text-secondary',
          )}
        >
          {guidance}
        </p>
      )}
    </div>
  )
}

/** Default 1–5 options with rubric-agnostic guidance; pass per-criterion text when available. */
export function scoreOptions(guidance?: Partial<Record<1 | 2 | 3 | 4 | 5, string>>) {
  const defaults = {
    1: 'Very weak — clear problems',
    2: 'Weak — more concerns than strengths',
    3: 'Adequate — no strong case either way',
    4: 'Strong — a convincing case',
    5: 'Exceptional — among the best we have seen',
  }
  return ([1, 2, 3, 4, 5] as const).map((score) => ({
    value: String(score) as '1' | '2' | '3' | '4' | '5',
    label: String(score),
    description: `${score} · ${guidance?.[score] ?? defaults[score]}`,
  }))
}
