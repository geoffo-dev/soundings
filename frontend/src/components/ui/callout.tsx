import { cva, type VariantProps } from 'class-variance-authority'
import { CircleAlert, CircleCheck, Info, TriangleAlert } from 'lucide-react'
import type { ComponentProps, ReactNode } from 'react'

import { cn } from '@/lib/utils'

const calloutVariants = cva(
  'flex items-start gap-2.5 rounded-lg px-3 py-2.5 text-sm text-primary',
  {
    variants: {
      tone: {
        neutral: 'bg-subtle',
        info: 'bg-info-subtle',
        success: 'bg-success-subtle',
        warning: 'bg-warning-subtle',
        danger: 'bg-danger-subtle',
      },
    },
    defaultVariants: { tone: 'neutral' },
  },
)

const ICONS = {
  neutral: <Info />,
  info: <Info />,
  success: <CircleCheck />,
  warning: <TriangleAlert />,
  danger: <CircleAlert />,
} as const

const ICON_TONE = {
  neutral: 'text-muted',
  info: 'text-info',
  success: 'text-success',
  warning: 'text-warning',
  danger: 'text-danger',
} as const

export interface CalloutProps
  extends Omit<ComponentProps<'div'>, 'title'>, VariantProps<typeof calloutVariants> {
  /** One short sentence; the children (optional) say what to do next. */
  title: ReactNode
  /** Replaces the tone's icon (decorative). */
  icon?: ReactNode
  /** A small action at the end (a link or ghost button). */
  action?: ReactNode
}

/**
 * An inline message inside a page or form: a sign-in problem, a save that
 * failed, a note about what a setting means. Colour comes from the tone (the
 * icon too, so it is never colour alone); text stays primary for contrast.
 * Pass `role="alert"` for errors that appear after an action and `role="status"`
 * for calm notices. Toasts are for feedback on actions; this is for state.
 */
export function Callout({
  tone,
  title,
  icon,
  action,
  children,
  className,
  ...props
}: CalloutProps) {
  const key = tone ?? 'neutral'
  return (
    <div data-slot="callout" className={cn(calloutVariants({ tone }), className)} {...props}>
      <span aria-hidden="true" className={cn('mt-0.5 shrink-0 [&_svg]:size-4', ICON_TONE[key])}>
        {icon ?? ICONS[key]}
      </span>
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <p className="font-medium">{title}</p>
        {children && <div className="text-secondary">{children}</div>}
      </div>
      {action && <div className="shrink-0 self-center">{action}</div>}
    </div>
  )
}
