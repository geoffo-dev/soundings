import { Folder, Inbox, LayoutGrid, Moon, Sun } from 'lucide-react'
import { useEffect, useRef, useState, type ReactNode } from 'react'

import { LogoMark } from '@/components/layout/logo'
import { useTheme } from '@/components/theme-provider'
import { SegmentedControl } from '@/components/ui/segmented-control'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  brandPreviewProperties,
  loadBrandFont,
  readableOn,
  setElementProperties,
} from '@/lib/branding'
import type { ResolvedTheme } from '@/lib/theme'
import { cn } from '@/lib/utils'

import type { PreviewBranding } from './branding-form'

/**
 * Live previews of a branding form before it is saved (contract-phase4 §3.10):
 * the values are applied to a preview pane only (scoped CSS variables), never
 * to the app. Previews are pictures: not focusable, hidden from screen readers
 * (the form itself says everything), each with a visible caption.
 */
export function BrandingPreview({
  branding,
  surfaces,
  projectName,
}: {
  branding: PreviewBranding
  /** Which previews to show: the app shell only for the global branding. */
  surfaces: ('app' | 'public' | 'email')[]
  projectName: string
}) {
  const { resolvedTheme } = useTheme()
  const [theme, setTheme] = useState<ResolvedTheme>(resolvedTheme)
  const [tab, setTab] = useState(surfaces[0] ?? 'public')

  useEffect(() => {
    void loadBrandFont(branding.font)
  }, [branding.font])

  return (
    <section aria-labelledby="branding-preview-heading" className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 id="branding-preview-heading" className="text-base font-semibold text-primary">
          Preview
        </h3>
        <SegmentedControl
          aria-label="Preview theme"
          size="sm"
          value={theme}
          onValueChange={setTheme}
          options={[
            { value: 'light', label: <Sun aria-hidden="true" />, ariaLabel: 'Light' },
            { value: 'dark', label: <Moon aria-hidden="true" />, ariaLabel: 'Dark' },
          ]}
        />
      </div>
      <Tabs value={tab} onValueChange={(next) => setTab(next as typeof tab)}>
        <TabsList aria-label="Preview of">
          {surfaces.map((surface) => (
            <TabsTrigger key={surface} value={surface}>
              {surface === 'app' ? 'App' : surface === 'public' ? 'Public form' : 'Email'}
            </TabsTrigger>
          ))}
        </TabsList>
        {surfaces.includes('app') && (
          <TabsContent value="app" className="pt-3">
            <PreviewFrame
              branding={branding}
              theme={theme}
              caption="The sidebar, links and buttons"
            >
              <AppPreview branding={branding} />
            </PreviewFrame>
          </TabsContent>
        )}
        <TabsContent value="public" className="pt-3">
          <PreviewFrame branding={branding} theme={theme} caption={`The public form at /…/submit`}>
            <PublicFormPreview branding={branding} projectName={projectName} />
          </PreviewFrame>
        </TabsContent>
        {surfaces.includes('email') && (
          <TabsContent value="email" className="pt-3">
            <PreviewFrame
              branding={branding}
              theme="light"
              caption="Emails (always light; no images, so the app name is the wordmark)"
            >
              <EmailPreview branding={branding} projectName={projectName} />
            </PreviewFrame>
          </TabsContent>
        )}
      </Tabs>
    </section>
  )
}

/** Applies the branding's tokens to its own subtree, in `theme`. */
function PreviewFrame({
  branding,
  theme,
  caption,
  children,
}: {
  branding: PreviewBranding
  theme: ResolvedTheme
  caption: string
  children: ReactNode
}) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!ref.current) return
    return setElementProperties(ref.current, brandPreviewProperties(branding, theme))
  }, [branding, theme])
  return (
    <figure className="flex flex-col gap-2">
      <div
        ref={ref}
        inert
        aria-hidden="true"
        data-testid="branding-preview"
        className={cn(theme, 'overflow-hidden rounded-lg border bg-background text-primary')}
      >
        {children}
      </div>
      <figcaption className="text-xs text-muted">{caption}</figcaption>
    </figure>
  )
}

/** The logo at its own proportions (wide logos stay wide), or the mark. */
function PreviewLogo({ url }: { url: string | null }) {
  return url ? (
    <img src={url} alt="" className="h-5 w-auto max-w-24 shrink-0 logo-plate object-contain" />
  ) : (
    <LogoMark src={null} className="size-5" />
  )
}

function FakeButton({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <span
      className={cn(
        'inline-flex h-7 items-center rounded-md bg-accent px-2.5 text-sm font-medium text-accent-foreground',
        className,
      )}
    >
      {children}
    </span>
  )
}

function AppPreview({ branding }: { branding: PreviewBranding }) {
  const nav = [
    { icon: <LayoutGrid />, label: 'My work', selected: true },
    { icon: <Inbox />, label: 'Notifications', selected: false },
    { icon: <Folder />, label: 'Customer Innovation', selected: false },
  ]
  return (
    <div className="flex h-56">
      <div className="flex w-40 shrink-0 flex-col gap-1 border-r bg-background p-2 max-sm:w-32">
        <span className="flex min-w-0 items-center gap-1.5 px-1.5 py-1">
          <PreviewLogo url={branding.logo_url} />
          <span className="truncate text-sm font-semibold">{branding.app_name}</span>
        </span>
        {nav.map((item) => (
          <span
            key={item.label}
            className={cn(
              'flex items-center gap-2 rounded-md px-1.5 py-1 text-xs [&_svg]:size-3.5',
              item.selected ? 'bg-accent-subtle text-primary' : 'text-secondary',
            )}
          >
            {item.icon}
            <span className="truncate">{item.label}</span>
          </span>
        ))}
      </div>
      <div className="flex min-w-0 flex-1 flex-col gap-2 bg-surface p-3">
        <span className="text-base font-semibold">My work</span>
        <span className="text-xs text-secondary">
          3 evaluations due. <span className="font-medium text-accent">See all</span>
        </span>
        <span className="flex flex-col gap-1 rounded-md border p-2 text-xs">
          <span className="font-medium">Print-free returns</span>
          <span className="text-muted">CUST-12 · Evaluating</span>
        </span>
        <span className="mt-auto flex justify-end">
          <FakeButton>New idea</FakeButton>
        </span>
      </div>
    </div>
  )
}

function PublicFormPreview({
  branding,
  projectName,
}: {
  branding: PreviewBranding
  projectName: string
}) {
  return (
    <div className="flex flex-col items-center gap-3 px-4 py-4">
      {/* Like the real form: a logo stands alone; without one, the mark and the name. */}
      <span className="flex min-w-0 items-center gap-1.5">
        <PreviewLogo url={branding.logo_url} />
        {!branding.logo_url && (
          <span className="truncate text-sm font-semibold">{branding.app_name}</span>
        )}
      </span>
      <div className="flex w-full max-w-xs flex-col gap-2 rounded-lg border bg-surface p-3">
        <span className="text-sm font-semibold">Share an idea with {projectName}</span>
        <span className="text-xs font-medium">Title</span>
        <span className="h-7 rounded-md border border-input bg-surface" />
        <span className="text-xs text-muted">
          You’ll get a <span className="font-medium text-accent">private link</span> to follow it.
        </span>
        <FakeButton className="justify-center">Send idea</FakeButton>
      </div>
    </div>
  )
}

/** Emails: the primary colour as a band with contrast-checked text, the footer below. */
function EmailPreview({
  branding,
  projectName,
}: {
  branding: PreviewBranding
  projectName: string
}) {
  const band = useRef<HTMLDivElement>(null)
  const button = useRef<HTMLSpanElement>(null)
  useEffect(() => {
    const { color } = readableOn(branding.primary_color)
    const undo = [band.current, button.current].map((element) =>
      element
        ? setElementProperties(element, {
            'background-color': branding.primary_color,
            color,
          })
        : () => undefined,
    )
    return () => undo.forEach((fn) => fn())
  }, [branding.primary_color])
  return (
    <div className="p-3">
      <div className="mx-auto flex max-w-sm flex-col overflow-hidden rounded-md border bg-surface">
        <div ref={band} className="px-4 py-2.5 text-sm font-semibold">
          {branding.app_name}
        </div>
        <div className="flex flex-col gap-2 px-4 py-3 text-xs">
          <span className="text-sm font-semibold">Your idea is now Shortlisted</span>
          <span className="text-secondary">
            “Print-free returns” moved forward in {projectName}. Follow it on your tracking page.
          </span>
          <span>
            <span ref={button} className="inline-flex rounded-md px-2.5 py-1 font-medium">
              Open the tracking page
            </span>
          </span>
          {branding.email_footer && (
            <span className="border-t border-subtle pt-2 whitespace-pre-line text-muted">
              {branding.email_footer}
            </span>
          )}
        </div>
      </div>
    </div>
  )
}
