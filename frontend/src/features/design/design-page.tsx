import { Link } from '@tanstack/react-router'
import { ArrowUpRight, Gauge, Keyboard, Monitor, Moon, Smile, Sun } from 'lucide-react'
import type { ReactNode } from 'react'

import { Logo } from '@/components/layout/logo'
import { useTheme } from '@/components/theme-provider'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { SegmentedControl } from '@/components/ui/segmented-control'
import { Separator } from '@/components/ui/separator'
import { isThemePreference } from '@/lib/theme'

import { ButtonsSection, FormsSection, SegmentedSection } from './controls-section'
import { BadgesSection, ContentSection, ScoresSection, TableSection } from './display-section'
import { FeedbackSection } from './feedback-section'
import { OverlaysSection } from './overlays-section'
import { PatternsSection } from './patterns-section'
import { TokensSection } from './tokens-section'

const TOC: { title: string; items: [id: string, label: string][] }[] = [
  {
    title: 'Foundations',
    items: [
      ['colour', 'Colour'],
      ['typography', 'Typography'],
      ['spacing', 'Spacing & elevation'],
    ],
  },
  {
    title: 'Components',
    items: [
      ['buttons', 'Buttons'],
      ['forms', 'Form controls'],
      ['segmented', 'Segmented control'],
      ['badges', 'Badges & avatars'],
      ['scores', 'Scores & progress'],
      ['table', 'Table & filters'],
      ['content', 'Content & navigation'],
      ['overlays', 'Overlays'],
      ['states', 'Empty & loading'],
    ],
  },
  {
    title: 'Patterns',
    items: [
      ['shell', 'App shell'],
      ['idea-list', 'List & board'],
      ['evaluate', 'Evaluate'],
      ['idea-sidebar', 'Idea page'],
    ],
  },
]

const PRINCIPLES: { icon: ReactNode; title: string; body: string }[] = [
  {
    icon: <Smile />,
    title: 'Calm',
    body: 'Neutral greys, one accent, colour only for status and scores. Whitespace over boxes.',
  },
  {
    icon: <Gauge />,
    title: 'Fast',
    body: 'Skeletons not spinners, optimistic updates with Undo, short 120–200ms motion.',
  },
  {
    icon: <Keyboard />,
    title: 'Obvious',
    body: 'One primary action per view, ⌘K for everything, full keyboard and screen-reader support.',
  },
]

export default function DesignPage() {
  const { preference, setPreference } = useTheme()

  return (
    <div className="min-h-dvh bg-background text-primary">
      <header
        aria-label="Design system"
        className="sticky top-0 z-30 border-b bg-background/85 backdrop-blur-md"
      >
        <div className="mx-auto flex h-14 max-w-7xl items-center gap-3 px-4 sm:px-6">
          <Link to="/" className="rounded-md">
            <Logo />
          </Link>
          <Separator orientation="vertical" className="hidden h-5 sm:block" />
          <span className="hidden text-sm font-medium text-secondary sm:inline">Design system</span>
          <Badge variant="outline" className="hidden sm:inline-flex">
            Dev only
          </Badge>
          <div className="ml-auto flex items-center gap-2">
            <SegmentedControl
              size="sm"
              aria-label="Theme"
              value={preference}
              onValueChange={(value) => {
                if (isThemePreference(value)) setPreference(value)
              }}
              options={[
                {
                  value: 'light',
                  label: (
                    <>
                      <Sun className="size-3.5" /> <span className="hidden sm:inline">Light</span>
                    </>
                  ),
                  ariaLabel: 'Light',
                },
                {
                  value: 'dark',
                  label: (
                    <>
                      <Moon className="size-3.5" /> <span className="hidden sm:inline">Dark</span>
                    </>
                  ),
                  ariaLabel: 'Dark',
                },
                {
                  value: 'system',
                  label: (
                    <>
                      <Monitor className="size-3.5" />{' '}
                      <span className="hidden sm:inline">System</span>
                    </>
                  ),
                  ariaLabel: 'System',
                },
              ]}
            />
            <Button asChild variant="ghost" size="sm" className="hidden md:inline-flex">
              <Link to="/">
                Open app <ArrowUpRight />
              </Link>
            </Button>
          </div>
        </div>
      </header>

      <div className="mx-auto flex max-w-7xl gap-10 px-4 sm:px-6">
        <nav
          aria-label="Design system sections"
          className="sticky top-14 hidden h-[calc(100dvh-3.5rem)] w-44 shrink-0 overflow-y-auto py-10 lg:block"
        >
          {TOC.map((group) => (
            <div key={group.title} className="mb-6">
              <h2 className="mb-1.5 px-2 text-xs font-medium text-muted">{group.title}</h2>
              <ul className="flex flex-col gap-px">
                {group.items.map(([id, label]) => (
                  <li key={id}>
                    <a
                      href={`#${id}`}
                      className="block rounded-md px-2 py-1 text-sm text-secondary transition-colors hover:bg-subtle hover:text-primary"
                    >
                      {label}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </nav>

        <main
          id="main"
          aria-label="Design system documentation"
          className="flex min-w-0 flex-1 flex-col gap-16 py-10 pb-24"
        >
          <div className="flex flex-col gap-6">
            <div className="flex flex-col gap-2">
              <h1 className="text-3xl font-semibold">Soundings design system</h1>
              <p className="max-w-2xl text-lg text-secondary">
                Tokens, components and patterns for every screen. Build from{' '}
                <code className="font-mono text-base">src/components/ui</code> and the tokens below
                — no one-off colours or spacing.
              </p>
            </div>
            <div className="grid gap-4 md:grid-cols-3">
              {PRINCIPLES.map((principle) => (
                <div
                  key={principle.title}
                  className="flex flex-col gap-2 rounded-lg border bg-surface p-4"
                >
                  <span className="flex size-8 items-center justify-center rounded-md bg-accent-subtle text-accent [&_svg]:size-4">
                    {principle.icon}
                  </span>
                  <h2 className="text-base font-semibold">{principle.title}</h2>
                  <p className="text-sm text-muted">{principle.body}</p>
                </div>
              ))}
            </div>
          </div>

          <TokensSection />
          <ButtonsSection />
          <FormsSection />
          <SegmentedSection />
          <BadgesSection />
          <ScoresSection />
          <TableSection />
          <ContentSection />
          <OverlaysSection />
          <FeedbackSection />
          <PatternsSection />
        </main>
      </div>
    </div>
  )
}
