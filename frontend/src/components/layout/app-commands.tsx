import { useNavigate } from '@tanstack/react-router'
import { Inbox, Keyboard, Lightbulb, Monitor, Moon, Palette, Settings, Sun } from 'lucide-react'
import { createContext, use, useMemo, useState, type ReactNode } from 'react'

import { ProjectTile } from '@/components/layout/project-tile'
import { ShortcutSheet } from '@/components/layout/shortcut-sheet'
import { useShellData } from '@/components/layout/shell-data'
import { useTheme } from '@/components/theme-provider'
import { CommandPalette, type CommandGroupData } from '@/components/ui/command-palette'
import { toast } from '@/components/ui/toaster'
import { designPageEnabled } from '@/lib/env'
import { SHORTCUTS, useShortcut } from '@/lib/shortcuts'

interface AppCommands {
  openCommandPalette: () => void
  openShortcutSheet: () => void
  newIdea: () => void
}

const AppCommandsContext = createContext<AppCommands | null>(null)

/**
 * Global keyboard layer: ⌘K palette, "?" shortcut sheet, "n" new idea, "g m".
 * Mounted once in the root route; screens call useAppCommands() to trigger the
 * same actions from buttons.
 */
export function AppCommandsProvider({ children }: { children: ReactNode }) {
  const navigate = useNavigate()
  const { setPreference } = useTheme()
  const { projects } = useShellData()
  const [paletteOpen, setPaletteOpen] = useState(false)
  const [shortcutsOpen, setShortcutsOpen] = useState(false)

  const commands = useMemo<AppCommands>(
    () => ({
      openCommandPalette: () => setPaletteOpen(true),
      openShortcutSheet: () => setShortcutsOpen(true),
      // Phase 1 replaces this with the submit-idea dialog.
      newIdea: () =>
        toast.info('New idea', { description: 'Submitting ideas arrives in Phase 1.' }),
    }),
    [],
  )

  useShortcut('commandPalette', () => setPaletteOpen((open) => !open))
  useShortcut('shortcutSheet', () => setShortcutsOpen(true))
  useShortcut('newIdea', commands.newIdea)
  useShortcut('goToMyWork', () => void navigate({ to: '/' }))

  const groups: CommandGroupData[] = [
    {
      heading: 'Actions',
      actions: [
        {
          id: 'new-idea',
          label: 'New idea',
          icon: <Lightbulb />,
          shortcut: SHORTCUTS.newIdea.keys,
          onSelect: commands.newIdea,
        },
      ],
    },
    {
      heading: 'Go to',
      actions: [
        {
          id: 'my-work',
          label: 'My work',
          icon: <Inbox />,
          shortcut: SHORTCUTS.goToMyWork.keys,
          onSelect: () => void navigate({ to: '/' }),
        },
        ...projects.map((project) => ({
          id: `project-${project.id}`,
          label: project.name,
          hint: 'Project',
          icon: <ProjectTile name={project.name} className="size-4" />,
          keywords: ['project'],
          onSelect: () =>
            void navigate({ to: '/projects/$projectId', params: { projectId: project.id } }),
        })),
        {
          id: 'settings',
          label: 'Settings',
          icon: <Settings />,
          onSelect: () => void navigate({ to: '/settings' }),
        },
        ...(designPageEnabled
          ? [
              {
                id: 'design',
                label: 'Design system',
                hint: 'Dev only',
                icon: <Palette />,
                onSelect: () => void navigate({ to: '/design' }),
              },
            ]
          : []),
      ],
    },
    {
      heading: 'Preferences',
      actions: [
        {
          id: 'theme-light',
          label: 'Use light theme',
          icon: <Sun />,
          keywords: ['appearance'],
          onSelect: () => setPreference('light'),
        },
        {
          id: 'theme-dark',
          label: 'Use dark theme',
          icon: <Moon />,
          keywords: ['appearance'],
          onSelect: () => setPreference('dark'),
        },
        {
          id: 'theme-system',
          label: 'Use system theme',
          icon: <Monitor />,
          keywords: ['appearance', 'auto'],
          onSelect: () => setPreference('system'),
        },
        {
          id: 'shortcuts',
          label: 'Keyboard shortcuts',
          icon: <Keyboard />,
          shortcut: SHORTCUTS.shortcutSheet.keys,
          onSelect: commands.openShortcutSheet,
        },
      ],
    },
  ]

  return (
    <AppCommandsContext value={commands}>
      {children}
      <CommandPalette open={paletteOpen} onOpenChange={setPaletteOpen} groups={groups} />
      <ShortcutSheet open={shortcutsOpen} onOpenChange={setShortcutsOpen} />
    </AppCommandsContext>
  )
}

export function useAppCommands(): AppCommands {
  const context = use(AppCommandsContext)
  if (!context) throw new Error('useAppCommands must be used inside <AppCommandsProvider>')
  return context
}
