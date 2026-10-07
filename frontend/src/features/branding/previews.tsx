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
  titled = true,
}: {
  branding: PreviewBranding
  /** Which previews to show: the app shell only for the global branding. */
  surfaces: ('app' | 'public' | 'email')[]
  projectName: string
  /** Show the "Preview" heading (off inside the preview sheet, whose title says it). */
  titled?: boolean
}) {
  const { resolvedTheme } = useTheme()
  const [theme, setTheme] = useState<ResolvedTheme>(resolvedTheme)
  const [tab, setTab] = useState(surfaces[0] ?? 'public')

  useEffect(() => {
    void loadBrandFont(branding.font)
  }, [branding.font])

  return (
    <section aria-label="Preview" className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        {titled ? (
          <h3 className="text-base font-semibold text-primary">Preview</h3>
        ) : (
          <span className="text-sm text-muted">Before you save</span>
        )}
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
              theme={theme}
              caption={
                surfaces.includes('app')
                  ? 'An email to the team. Emails show no images, so the app name and its initial are the wordmark; mail apps in dark mode show the dark version.'
                  : 'An email to someone who sent an idea through the public form. No images: the name and its initial are the wordmark (the project’s name when it has its own logo but no app name).'
              }
            >
              <EmailPreview
                branding={branding}
                projectName={projectName}
                audience={surfaces.includes('app') ? 'staff' : 'submitter'}
              />
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
    <img src={url} alt="" className="logo-plate h-5 w-auto max-w-24 shrink-0 object-contain" />
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
          <span className="truncate font-brand text-sm font-semibold">{branding.app_name}</span>
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
        {/* Page titles and the wordmark take the brand font; UI text stays Inter. */}
        <span className="font-brand text-base font-semibold">My work</span>
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
    <div className="flex flex-col items-center gap-3 px-4 py-4 font-brand">
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

/**
 * An email, laid out as the real template is (backend `templates/email/_layout.html`):
 * no images, so the wordmark is the app name beside its initial on the primary
 * colour; a white card with the heading, text and the button in the primary
 * colour (text colour picked for contrast); the reason, links and footer lines
 * under the card. Mail apps in dark mode show the dark version (the theme toggle).
 * `audience`: staff get the instance's emails (global branding); a project's
 * branding reaches the people who sent it ideas through its public form.
 */
function EmailPreview({
  branding,
  projectName,
  audience,
}: {
  branding: PreviewBranding
  projectName: string
  audience: 'staff' | 'submitter'
}) {
  const tile = useRef<HTMLSpanElement>(null)
  const button = useRef<HTMLSpanElement>(null)
  useEffect(() => {
    const { color } = readableOn(branding.primary_color)
    const undo = [tile.current, button.current].map((element) =>
      element
        ? setElementProperties(element, { 'background-color': branding.primary_color, color })
        : () => undefined,
    )
    return () => undo.forEach((fn) => fn())
  }, [branding.primary_color])
  const initial = (branding.app_name.trim()[0] ?? 'S').toUpperCase()
  const footer = branding.email_footer
    ? branding.email_footer.split('\n').filter((line) => line.trim())
    : [`Sent by ${branding.app_name}.`]
  const staff = audience === 'staff'
  return (
    <div className="px-3 py-4 font-brand">
      <div className="mx-auto flex max-w-sm flex-col">
        <span className="flex min-w-0 items-center gap-2 px-1 pb-2.5">
          <span
            ref={tile}
            className="font-bold flex size-5 shrink-0 items-center justify-center rounded-md text-xs"
          >
            {initial}
          </span>
          <span className="truncate text-sm font-semibold">{branding.app_name}</span>
        </span>
        <div className="flex flex-col gap-2 rounded-lg border bg-surface px-4 py-3.5 text-xs">
          <span className="text-sm font-semibold">
            {staff ? 'Moved to Shortlisted' : 'Your idea is now Shortlisted'}
          </span>
          {staff ? (
            <>
              <span>
                Alice Anders moved this idea from <strong>Evaluating</strong> to{' '}
                <strong>Shortlisted</strong>:
              </span>
              <span className="flex flex-col gap-0.5 rounded-md border bg-subtle px-2.5 py-2">
                <span className="text-muted">CUST-24 · {projectName}</span>
                <span className="font-semibold">Print-free returns</span>
                <span className="text-muted">Status: Shortlisted</span>
              </span>
            </>
          ) : (
            <span>
              The idea you sent to {projectName}, <strong>Print-free returns</strong>, is now{' '}
              <strong>Shortlisted</strong>.
            </span>
          )}
          <span className="pt-1">
            <span ref={button} className="inline-flex rounded-md px-3 py-1.5 font-semibold">
              {staff ? 'Open the idea' : 'See where your idea stands'}
            </span>
          </span>
        </div>
        <div className="flex flex-col gap-1 px-1 pt-2.5 text-xs text-muted">
          <span>
            {staff
              ? 'You’re evaluating CUST-24.'
              : `You asked for updates on an idea you sent to ${projectName}.`}
          </span>
          {staff ? (
            <span className="underline">Email preferences · Unsubscribe from status changes</span>
          ) : (
            <span className="underline">Stop these emails</span>
          )}
          <span className="pt-1">
            {footer.map((line, index) => (
              <span key={index} className="block">
                {line}
              </span>
            ))}
          </span>
        </div>
      </div>
    </div>
  )
}
