import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

import { Code, DesignSection, Specimen } from './specimen'

interface Swatch {
  name: string
  className: string
  note?: string
  kind?: 'fill' | 'border' | 'text' | 'ring'
}

const COLOR_GROUPS: { title: string; swatches: Swatch[] }[] = [
  {
    title: 'Surfaces · bg-*',
    swatches: [
      { name: 'background', className: 'bg-background', note: 'Canvas, sidebar' },
      { name: 'surface', className: 'bg-surface', note: 'Panels, cards' },
      { name: 'elevated', className: 'bg-elevated', note: 'Overlays' },
      { name: 'subtle', className: 'bg-subtle', note: 'Quiet fills' },
      { name: 'subtle-hover', className: 'bg-subtle-hover', note: 'Hover, selected' },
    ],
  },
  {
    title: 'Text · text-*',
    swatches: [
      { name: 'primary', className: 'text-primary', kind: 'text', note: 'Body, titles' },
      { name: 'secondary', className: 'text-secondary', kind: 'text', note: 'Supporting' },
      { name: 'muted', className: 'text-muted', kind: 'text', note: 'Meta, hints' },
      { name: 'accent', className: 'text-accent', kind: 'text', note: 'Links' },
    ],
  },
  {
    title: 'Borders',
    swatches: [
      { name: 'border-subtle', className: 'border-subtle', kind: 'border', note: 'Row dividers' },
      { name: 'border', className: 'border-border', kind: 'border', note: 'Cards, menus' },
      { name: 'border-strong', className: 'border-strong', kind: 'border', note: 'Emphasis' },
      { name: 'border-input', className: 'border-input', kind: 'border', note: 'Text fields, 3:1' },
      { name: 'border-control', className: 'border-control', kind: 'border', note: 'Checkboxes' },
    ],
  },
  {
    title: 'Accent (brand) · bg-*',
    swatches: [
      { name: 'accent', className: 'bg-accent', note: 'Primary action' },
      { name: 'accent-hover', className: 'bg-accent-hover', note: 'Hover' },
      { name: 'accent-subtle', className: 'bg-accent-subtle', note: 'Selected tint' },
      { name: 'ring-focus', className: 'ring-focus', kind: 'ring', note: 'Focus ring' },
    ],
  },
  {
    title: 'Feedback · bg-/text-*',
    swatches: [
      { name: 'danger', className: 'bg-danger', note: 'Destructive' },
      { name: 'warning', className: 'bg-warning', note: 'Attention' },
      { name: 'success', className: 'bg-success', note: 'Done, positive' },
      { name: 'info', className: 'bg-info', note: 'Neutral notice' },
      { name: 'danger-subtle', className: 'bg-danger-subtle', note: 'Tinted' },
    ],
  },
  {
    title: 'Idea status · bg-status-*',
    swatches: [
      { name: 'new', className: 'bg-status-new' },
      { name: 'evaluating', className: 'bg-status-evaluating' },
      { name: 'shortlisted', className: 'bg-status-shortlisted' },
      { name: 'proposal', className: 'bg-status-proposal' },
      { name: 'accepted', className: 'bg-status-accepted' },
      { name: 'rejected', className: 'bg-status-rejected' },
      { name: 'parked', className: 'bg-status-parked' },
    ],
  },
  {
    title: 'Scores 1 → 5 · bg-score-*',
    swatches: [
      { name: '1', className: 'bg-score-1', note: 'Very weak' },
      { name: '2', className: 'bg-score-2', note: 'Weak' },
      { name: '3', className: 'bg-score-3', note: 'Adequate' },
      { name: '4', className: 'bg-score-4', note: 'Strong' },
      { name: '5', className: 'bg-score-5', note: 'Exceptional' },
    ],
  },
]

function SwatchChip({ swatch }: { swatch: Swatch }) {
  const kind = swatch.kind ?? 'fill'
  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <div
        aria-hidden="true"
        className={cn(
          'flex h-9 items-center justify-center rounded-md',
          kind === 'fill' && [swatch.className, 'shadow-[inset_0_0_0_1px_var(--border-subtle)]'],
          kind === 'border' && ['border-2 bg-surface', swatch.className],
          kind === 'text' && ['border bg-surface text-lg font-semibold', swatch.className],
          kind === 'ring' && [
            'bg-surface ring-2 ring-offset-2 ring-offset-background',
            swatch.className,
          ],
        )}
      >
        {kind === 'text' ? 'Aa' : null}
      </div>
      <div className="flex flex-col">
        <span className="truncate font-mono text-xs text-primary">{swatch.name}</span>
        {swatch.note && <span className="truncate text-xs text-muted">{swatch.note}</span>}
      </div>
    </div>
  )
}

function ThemePanel({ theme }: { theme: 'light' | 'dark' }) {
  return (
    <div
      className={cn(theme, 'flex flex-col gap-5 rounded-lg border bg-background p-5 text-primary')}
    >
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold capitalize">{theme}</h3>
        <span className="text-xs text-muted">class=&quot;{theme}&quot;</span>
      </div>
      {COLOR_GROUPS.map((group) => (
        <div key={group.title} className="flex flex-col gap-2">
          <h4 className="text-xs font-medium text-muted">{group.title}</h4>
          <div className="grid grid-cols-[repeat(auto-fill,minmax(6.5rem,1fr))] gap-x-3 gap-y-3">
            {group.swatches.map((swatch) => (
              <SwatchChip key={swatch.name} swatch={swatch} />
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

const TYPE_SCALE = [
  { cls: 'text-3xl', size: '30 / 36', use: 'Rare: marketing-style headings' },
  { cls: 'text-2xl', size: '24 / 32', use: 'Page titles' },
  { cls: 'text-xl', size: '20 / 28', use: 'Section and dialog titles' },
  { cls: 'text-lg', size: '16 / 24', use: 'Card titles, emphasis, inputs on phones' },
  { cls: 'text-base', size: '14 / 22', use: 'Default UI and body text' },
  { cls: 'text-sm', size: '13 / 20', use: 'Buttons, table cells, secondary text' },
  { cls: 'text-xs', size: '12 / 16', use: 'Meta, captions, badges' },
] as const

const SPACING = [
  { step: '1', px: 4, cls: 'w-1' },
  { step: '2', px: 8, cls: 'w-2' },
  { step: '3', px: 12, cls: 'w-3' },
  { step: '4', px: 16, cls: 'w-4' },
  { step: '5', px: 20, cls: 'w-5' },
  { step: '6', px: 24, cls: 'w-6' },
  { step: '8', px: 32, cls: 'w-8' },
  { step: '10', px: 40, cls: 'w-10' },
  { step: '12', px: 48, cls: 'w-12' },
  { step: '16', px: 64, cls: 'w-16' },
] as const

const RADII = [
  { cls: 'rounded-sm', px: '4px', use: 'Badges, kbd' },
  { cls: 'rounded-md', px: '6px', use: 'Buttons, inputs' },
  { cls: 'rounded-lg', px: '8px', use: 'Cards, menus' },
  { cls: 'rounded-xl', px: '12px', use: 'Dialogs, sheets' },
  { cls: 'rounded-full', px: '∞', use: 'Avatars, dots' },
] as const

const SHADOWS = [
  { cls: 'shadow-overlay', use: 'Menus, popovers, tooltips, toasts' },
  { cls: 'shadow-dialog', use: 'Dialogs and sheets' },
  { cls: 'shadow-raised', use: 'A card while it is dragged' },
] as const

export function TokensSection() {
  const [replay, setReplay] = useState(0)
  return (
    <>
      <DesignSection
        id="colour"
        title="Colour"
        description={
          <>
            Neutral greys do the work; the brand accent marks the primary action and focus. Colour
            is otherwise reserved for status and scores. Tokens switch with the <Code>.light</Code>{' '}
            / <Code>.dark</Code> class — both are shown side by side.
          </>
        }
      >
        <div className="grid gap-4 xl:grid-cols-2">
          <ThemePanel theme="light" />
          <ThemePanel theme="dark" />
        </div>
      </DesignSection>

      <DesignSection
        id="typography"
        title="Typography"
        description={
          <>
            Inter (bundled) at a 14px UI base, like Linear. Weights: 400 body, 500 labels and
            buttons, 600 titles. Use <Code>tabular-nums</Code> for numbers that line up.
          </>
        }
      >
        <Specimen title="Type scale" flush>
          <div className="divide-y divide-subtle">
            {TYPE_SCALE.map((row) => (
              <div
                key={row.cls}
                className="grid gap-1 px-5 py-3 sm:grid-cols-[8rem_minmax(0,1fr)] sm:items-baseline sm:gap-6"
              >
                <div className="flex flex-col">
                  <span className="font-mono text-xs text-primary">{row.cls}</span>
                  <span className="text-xs text-muted">{row.size}</span>
                </div>
                <div className="flex min-w-0 flex-col">
                  <span className={cn(row.cls, 'truncate font-semibold text-primary')}>
                    Hear the best ideas first
                  </span>
                  <span className="text-xs text-muted">{row.use}</span>
                </div>
              </div>
            ))}
          </div>
        </Specimen>
        <div className="grid gap-4 md:grid-cols-3">
          {(
            [
              ['font-normal', '400', 'Body text and descriptions'],
              ['font-medium', '500', 'Labels, buttons, nav'],
              ['font-semibold', '600', 'Titles and numbers'],
            ] as const
          ).map(([cls, weight, use]) => (
            <Specimen key={cls} title={`${cls} · ${weight}`}>
              <p className={cn('text-lg text-primary', cls)}>Evaluate this idea</p>
              <p className="mt-1 text-sm text-muted">{use}</p>
            </Specimen>
          ))}
        </div>
      </DesignSection>

      <DesignSection
        id="spacing"
        title="Spacing, radii & elevation"
        description="A 4px grid (Tailwind’s default scale). Stick to the steps below; content never casts shadows — only overlays do."
      >
        <div className="grid gap-4 lg:grid-cols-2">
          <Specimen
            title="Spacing scale"
            description="Gaps inside controls 1.5–2 · between controls 2–3 · sections 6–8."
          >
            <div className="flex flex-col gap-2">
              {SPACING.map((space) => (
                <div key={space.step} className="flex items-center gap-3">
                  <span className="w-6 text-right font-mono text-xs text-primary">
                    {space.step}
                  </span>
                  <span className={cn('h-3 rounded-sm bg-accent/70', space.cls)} />
                  <span className="text-xs text-muted">{space.px}px</span>
                </div>
              ))}
            </div>
          </Specimen>
          <div className="flex flex-col gap-4">
            <Specimen title="Radii · rounded-*">
              <div className="grid grid-cols-3 gap-4 sm:grid-cols-5">
                {RADII.map((radius) => (
                  <div key={radius.cls} className="flex min-w-0 flex-col gap-1.5">
                    <div className={cn('h-12 border-2 border-strong bg-subtle', radius.cls)} />
                    <span className="font-mono text-xs text-primary">
                      {radius.cls.replace('rounded-', '')} · {radius.px}
                    </span>
                    <span className="text-xs text-muted">{radius.use}</span>
                  </div>
                ))}
              </div>
            </Specimen>
            <Specimen title="Elevation" className="bg-background">
              <div className="grid gap-4 sm:grid-cols-3">
                {SHADOWS.map((shadow) => (
                  <div
                    key={shadow.cls}
                    className={cn('flex flex-col gap-1 rounded-lg bg-elevated p-3', shadow.cls)}
                  >
                    <span className="font-mono text-xs text-primary">{shadow.cls}</span>
                    <span className="text-xs text-muted">{shadow.use}</span>
                  </div>
                ))}
              </div>
            </Specimen>
          </div>
        </div>
        <Specimen
          title="Motion"
          description="Short and calm: 120ms (fast) for hovers, 160ms (base) for overlays, 200ms (slow) for sheets. Reduced-motion users get instant changes."
        >
          <div className="flex flex-wrap items-center gap-6">
            <dl className="grid grid-cols-[auto_auto] gap-x-4 gap-y-1 text-sm">
              <dt className="font-mono text-xs text-primary">--duration-fast</dt>
              <dd className="text-muted">120ms</dd>
              <dt className="font-mono text-xs text-primary">--duration-base</dt>
              <dd className="text-muted">160ms</dd>
              <dt className="font-mono text-xs text-primary">--duration-slow</dt>
              <dd className="text-muted">200ms</dd>
              <dt className="font-mono text-xs text-primary">ease-out</dt>
              <dd className="text-muted">cubic-bezier(.16, 1, .3, 1)</dd>
            </dl>
            <div className="flex flex-wrap items-center gap-3">
              {(['animate-pop-in', 'animate-fade-in', 'animate-reveal'] as const).map(
                (animation) => (
                  <div
                    key={`${animation}-${replay}`}
                    className={cn(
                      'flex h-16 w-28 items-center justify-center rounded-lg border bg-elevated font-mono text-xs text-secondary shadow-overlay',
                      animation,
                    )}
                  >
                    {animation.replace('animate-', '')}
                  </div>
                ),
              )}
              <Button size="sm" variant="outline" onClick={() => setReplay((n) => n + 1)}>
                Replay
              </Button>
            </div>
          </div>
        </Specimen>
      </DesignSection>
    </>
  )
}
