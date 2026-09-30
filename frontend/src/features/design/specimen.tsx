import type { ReactNode } from 'react'

import { cn } from '@/lib/utils'

export interface DesignSectionProps {
  id: string
  title: string
  description?: ReactNode
  children: ReactNode
}

/** A top-level section on the /design page (anchored for the table of contents). */
export function DesignSection({ id, title, description, children }: DesignSectionProps) {
  return (
    <section id={id} aria-labelledby={`${id}-title`} className="flex scroll-mt-20 flex-col gap-5">
      <div className="flex flex-col gap-1">
        <h2 id={`${id}-title`} className="text-xl font-semibold text-primary">
          {title}
        </h2>
        {description && <p className="max-w-2xl text-base text-muted">{description}</p>}
      </div>
      {children}
    </section>
  )
}

export interface SpecimenProps {
  title: string
  description?: ReactNode
  children: ReactNode
  /** Classes for the preview area (layout of the examples). */
  className?: string
  /** Remove preview padding (for full-bleed examples like tables). */
  flush?: boolean
}

/** A bordered example box with a small caption. */
export function Specimen({
  title,
  description,
  children,
  className,
  flush = false,
}: SpecimenProps) {
  return (
    <div className="flex min-w-0 flex-col overflow-hidden rounded-lg border bg-surface">
      <div className="flex flex-col gap-0.5 border-b border-subtle px-4 py-2.5">
        <h3 className="text-sm font-medium text-primary">{title}</h3>
        {description && <p className="text-sm text-muted">{description}</p>}
      </div>
      <div className={cn(flush ? '' : 'p-5', 'min-w-0 flex-1 content-start', className)}>
        {children}
      </div>
    </div>
  )
}

/** Labelled example inside a specimen, e.g. a button state. */
export function Example({
  label,
  children,
  className,
}: {
  label: string
  children: ReactNode
  className?: string
}) {
  return (
    <div className={cn('flex min-w-0 flex-col items-start gap-2', className)}>
      {children}
      <span className="font-mono text-xs text-muted">{label}</span>
    </div>
  )
}

export function Code({ children }: { children: ReactNode }) {
  return (
    <code className="rounded-sm bg-subtle px-1 py-0.5 font-mono text-xs text-secondary">
      {children}
    </code>
  )
}
