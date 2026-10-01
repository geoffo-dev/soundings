import type { ReactNode } from 'react'

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
 */
export function PublicLayout({
  branding,
  children,
  footer,
  width = 'form',
}: {
  branding: EffectiveBranding | null | undefined
  children: ReactNode
  footer?: ReactNode
  width?: 'form' | 'narrow'
}) {
  useBrandingOverride(branding)
  return (
    <div className="flex min-h-dvh flex-col bg-background">
      <header className="px-4 pt-6 pb-4 sm:pt-12 sm:pb-6">
        <div className="mx-auto flex h-8 max-w-xl items-center justify-center">
          {branding === undefined ? (
            <span className="flex items-center gap-2" aria-hidden="true">
              <Skeleton className="size-6 rounded-md" />
              <Skeleton className="h-4 w-28" />
            </span>
          ) : (
            <PublicBrand />
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

/** The applied (project or global) logo and app name: the store follows the override above. */
function PublicBrand() {
  const { app_name } = useAppBranding()
  return (
    <span className="inline-flex min-w-0 items-center gap-2">
      <LogoMark className="h-7 max-w-32" />
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
