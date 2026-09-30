import { cn } from '@/lib/utils'

/**
 * Soundings mark: a sounding line — depth readings narrowing as they go down.
 * Coloured with --brand-accent so runtime branding recolours it.
 */
export function LogoMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" aria-hidden="true" className={cn('size-6 shrink-0', className)}>
      <rect width="32" height="32" rx="8" fill="var(--brand-accent)" />
      <g fill="none" stroke="white" strokeLinecap="round" strokeWidth="2.4">
        <path d="M9 12.5h14" />
        <path d="M11.5 17.5h9" />
        <path d="M14 22.5h4" />
      </g>
      <circle cx="16" cy="8" r="1.6" fill="white" />
    </svg>
  )
}

export function Logo({ name = 'Soundings', className }: { name?: string; className?: string }) {
  return (
    <span className={cn('inline-flex items-center gap-2', className)}>
      <LogoMark />
      <span className="text-base font-semibold tracking-tight text-primary">{name}</span>
    </span>
  )
}
