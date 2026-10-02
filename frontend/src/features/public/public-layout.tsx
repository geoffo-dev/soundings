import type { ReactNode } from 'react'

import { useEffectiveBranding } from '@/api/branding'
import type { EffectiveBranding } from '@/api/types'
import { LogoMark } from '@/components/layout/logo'
import { Skeleton } from '@/components/ui/skeleton'
import { useBrandingOverride } from '@/features/branding/runtime-branding'
import { useAppBranding } from '@/lib/branding'
import { cn } from '@/lib/utils'

/**
 * The frame of the public pages (the form, /track and /verify): no app shell
 * and no sign-in, just the project's branding (logo or mark, app name) above
 * one calm column. `branding` undefined = still loading (a neutral header, so
 * nothing flashes in the wrong colours); null = use the global branding.
 * `projectName` names a project's own logo for screen readers (below).
 */
export function PublicLayout({
  branding,
  projectName,
  children,
  footer,
  width = 'form',
}: {
  branding: EffectiveBranding | null | undefined
  projectName?: string
  children: ReactNode
  footer?: ReactNode
  width?: 'form' | 'narrow'
}) {
  useBrandingOverride(branding)
  return (
    // Public pages are the project's own: all their text is in its brand font.
    <div className="flex min-h-dvh flex-col bg-background font-brand">
      <header className="px-4 pt-6 pb-4 sm:pt-12 sm:pb-6">
        <div className="mx-auto flex h-8 max-w-xl items-center justify-center">
          {branding === undefined ? (
            <span className="flex items-center gap-2" aria-hidden="true">
              <Skeleton className="size-6 rounded-md" />
              <Skeleton className="h-4 w-28" />
            </span>
          ) : (
            <PublicBrand projectName={projectName} />
          )}
        </div>
      </header>
      <main
        id="main"
        className={cn(
          'mx-auto flex w-full flex-1 flex-col gap-6 px-4 pb-12',
          width === 'form' ? 'max-w-xl' : 'max-w-md',
        )}
      >
        {children}
      </main>
      {footer && (
        <footer className="mx-auto w-full max-w-xl px-5 pb-10 text-sm text-muted">{footer}</footer>
      )}
    </div>
  )
}

/**
 * The applied (project or global) logo, or the mark and app name: the store follows the
 * override above. A logo stands alone (it is the brand; the PDF cover shows it alone too).
 * A project's own logo with no app name of its own is the project's brand, so screen
 * readers hear the project's name, not the instance's (as its emails and PDF name it).
 */
export function PublicBrand({ projectName }: { projectName?: string }) {
  const { app_name, logo_url } = useAppBranding()
  const global = useEffectiveBranding().data
  if (logo_url) {
    const projectLogo =
      Boolean(projectName) &&
      global !== undefined &&
      logo_url !== global.logo_url &&
      app_name === global.app_name
    return (
      <span className="inline-flex min-w-0 items-center">
        <LogoMark className="h-8 max-w-60" />
        <span className="sr-only">{projectLogo ? projectName : app_name}</span>
      </span>
    )
  }
  return (
    <span className="inline-flex min-w-0 items-center gap-2">
      <LogoMark className="h-8 max-w-48" />
      <span className="truncate text-lg font-semibold tracking-tight text-primary">{app_name}</span>
    </span>
  )
}

/** A white panel on the canvas: the form, the receipt, the tracking details. */
export function PublicCard({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={cn('flex flex-col gap-5 rounded-xl border bg-surface p-4 sm:p-6', className)}>
      {children}
    </div>
  )
}
