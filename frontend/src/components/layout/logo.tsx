import { useAppBranding } from '@/lib/branding'
import { cn } from '@/lib/utils'

/**
 * Soundings mark: a sounding line — depth readings narrowing as they go down.
 * Coloured with --brand-accent so runtime branding recolours it. With an
 * uploaded logo (contract-phase4 §3.10) the image takes its place, always
 * through `<img src>` (never inline SVG: an image can't run script), on a light
 * plate in dark mode (`logo-plate`).
 */
export function LogoMark({ className, src }: { className?: string; src?: string | null }) {
  const branding = useAppBranding()
  const logo = src === undefined ? branding.logo_url : src
  if (logo) {
    return (
      <img
        src={logo}
        alt=""
        aria-hidden="true"
        className={cn('h-6 w-auto max-w-24 shrink-0 logo-plate object-contain', className)}
      />
    )
  }
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

/** The mark and the app name (the instance's branding unless a name is given). */
export function Logo({ name, className }: { name?: string; className?: string }) {
  const branding = useAppBranding()
  return (
    <span className={cn('inline-flex min-w-0 items-center gap-2', className)}>
      <LogoMark />
      <span className="truncate text-base font-semibold tracking-tight text-primary">
        {name ?? branding.app_name}
      </span>
    </span>
  )
}
