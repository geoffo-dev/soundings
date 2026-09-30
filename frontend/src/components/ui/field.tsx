import { CircleAlert } from 'lucide-react'
import { createContext, use, useId, type ReactNode } from 'react'

import { Label } from '@/components/ui/label'
import { cn } from '@/lib/utils'

interface FieldContextValue {
  controlId: string
  labelId: string
  describedBy: string | undefined
  invalid: boolean
  required: boolean
  disabled: boolean
}

const FieldContext = createContext<FieldContextValue | null>(null)

export interface FieldProps {
  label?: ReactNode
  /** Help text shown under the control and announced with it. */
  description?: ReactNode
  /** Validation message. Marks the control aria-invalid and is announced. */
  error?: ReactNode
  required?: boolean
  disabled?: boolean
  /** Keep the label for screen readers only. */
  hideLabel?: boolean
  /** Put the control before the label (checkboxes, switches). */
  inline?: boolean
  id?: string
  className?: string
  children: ReactNode
}

/**
 * Wires a label, description and error to the control inside it. Every
 * form control in components/ui reads this context (via useFieldControl), so:
 *   <Field label="Title" error={errors.title}><Input /></Field>
 * is fully labelled and described without passing ids around.
 */
export function Field({
  label,
  description,
  error,
  required = false,
  disabled = false,
  hideLabel = false,
  inline = false,
  id,
  className,
  children,
}: FieldProps) {
  const autoId = useId()
  const controlId = id ?? `field-${autoId}`
  const descriptionId = description ? `${controlId}-description` : undefined
  const errorId = error ? `${controlId}-error` : undefined
  const describedBy = [descriptionId, errorId].filter(Boolean).join(' ') || undefined
  const value: FieldContextValue = {
    controlId,
    labelId: `${controlId}-label`,
    describedBy,
    invalid: Boolean(error),
    required,
    disabled,
  }

  const labelNode = label ? (
    <Label
      id={value.labelId}
      htmlFor={controlId}
      className={cn(hideLabel && 'sr-only', inline && 'font-normal')}
    >
      {label}
      {required && (
        <span aria-hidden="true" className="text-danger">
          *
        </span>
      )}
    </Label>
  ) : null

  const messages = (
    <>
      {description && (
        <p id={descriptionId} className="text-sm text-muted">
          {description}
        </p>
      )}
      {error && (
        <p id={errorId} className="flex items-start gap-1.5 text-sm text-danger">
          <CircleAlert aria-hidden="true" className="mt-0.5 size-3.5 shrink-0" />
          <span>{error}</span>
        </p>
      )}
    </>
  )

  return (
    <FieldContext value={value}>
      {inline ? (
        // Control on the left; label and messages share one column so they align.
        <div
          data-slot="field"
          data-invalid={error ? true : undefined}
          className={cn('grid grid-cols-[auto_minmax(0,1fr)] gap-x-2.5 gap-y-0.5', className)}
        >
          <div className="flex h-5 items-center">{children}</div>
          <div className="flex min-h-5 flex-col gap-0.5">
            {labelNode}
            {messages}
          </div>
        </div>
      ) : (
        <div
          data-slot="field"
          data-invalid={error ? true : undefined}
          className={cn('flex flex-col gap-1.5', className)}
        >
          {labelNode}
          {children}
          {messages}
        </div>
      )}
    </FieldContext>
  )
}

export function useFieldContext(): FieldContextValue | null {
  return use(FieldContext)
}

interface ControlAriaProps {
  id?: string
  disabled?: boolean
  required?: boolean
  'aria-describedby'?: string
  'aria-invalid'?: boolean | 'true' | 'false' | 'grammar' | 'spelling'
}

/** Merges Field context into a control's props; explicit props always win. */
export function useFieldControl<P extends ControlAriaProps>(props: P): P {
  const field = use(FieldContext)
  if (!field) return props
  return {
    ...props,
    id: props.id ?? field.controlId,
    disabled: props.disabled ?? (field.disabled || undefined),
    required: props.required ?? (field.required || undefined),
    'aria-describedby':
      [field.describedBy, props['aria-describedby']].filter(Boolean).join(' ') || undefined,
    'aria-invalid': props['aria-invalid'] ?? (field.invalid || undefined),
  }
}
