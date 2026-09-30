import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useParams } from '@tanstack/react-router'
import { defaultFilter } from 'cmdk'
import {
  FolderPlus,
  Inbox,
  Keyboard,
  Lightbulb,
  LogOut,
  Monitor,
  Moon,
  Palette,
  Settings,
  Sun,
} from 'lucide-react'
import { createContext, use, useMemo, useState, type ReactNode } from 'react'

import { meQueryOptions } from '@/api/auth'
import { findCachedIdea } from '@/api/cache'
import { projectsQueryOptions } from '@/api/projects'
import { useGlobalSearch } from '@/api/search'
import { ProjectTile } from '@/components/layout/project-tile'
import { ShortcutSheet } from '@/components/layout/shortcut-sheet'
import { useTheme } from '@/components/theme-provider'
import {
  CommandPalette,
  type CommandAction,
  type CommandGroupData,
} from '@/components/ui/command-palette'
import { StatusDot } from '@/components/ui/status-badge'
import { useSignOut } from '@/features/auth/use-sign-out'
import { useRegisteredCommands } from '@/lib/command-registry'
import { openCreateProject, openNewIdea } from '@/lib/dialogs'
import { designPageEnabled } from '@/lib/env'
import { SHORTCUTS, useShortcut } from '@/lib/shortcuts'
import { statusTone } from '@/lib/status'

interface AppCommands {
  openCommandPalette: () => void
  openShortcutSheet: () => void
  /** Opens the submit-idea dialog, preselecting the project in view. */
  newIdea: () => void
  /**
   * The user may submit ideas somewhere (`permissions.can_create_ideas` on at
   * least one project). Hide "New idea" buttons when false.
   */
  canCreateIdeas: boolean
}

const AppCommandsContext = createContext<AppCommands | null>(null)

/**
 * Global keyboard layer and ⌘K palette: "n" new idea, "?" shortcuts, "g m" My
 * work. Pages add context actions with `useCommands()` (lib/command-registry).
 * Signed-out pages (login, /design) get the static commands only.
 */
export function AppCommandsProvider({ children }: { children: ReactNode }) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const params: { slug?: string; ideaKey?: string } = useParams({ strict: false })
  const { resolvedTheme, setPreference } = useTheme()
  const signOut = useSignOut()
  const me = useQuery({ ...meQueryOptions(), enabled: false })
  const signedIn = Boolean(me.data)
  const projects = useQuery({ ...projectsQueryOptions(), enabled: signedIn })
  const [paletteOpen, setPaletteOpen] = useState(false)
  const [shortcutsOpen, setShortcutsOpen] = useState(false)
  const [search, setSearch] = useState('')
  const results = useGlobalSearch(paletteOpen && signedIn ? search : '')
  const contextGroups = useRegisteredCommands()
  // Optimistic while the projects load, so buttons don't flicker in.
  const canCreateIdeas =
    signedIn && (projects.data?.some((project) => project.permissions.can_create_ideas) ?? true)

  const commands = useMemo<AppCommands>(
    () => ({
      openCommandPalette: () => setPaletteOpen(true),
      openShortcutSheet: () => setShortcutsOpen(true),
      canCreateIdeas,
      newIdea: () => {
        if (!canCreateIdeas) return
        const slug =
          params.slug ??
          (params.ideaKey ? findCachedIdea(queryClient, params.ideaKey)?.project.slug : undefined)
        openNewIdea({ projectSlug: slug })
      },
    }),
    [canCreateIdeas, params.slug, params.ideaKey, queryClient],
  )

  useShortcut('commandPalette', () => setPaletteOpen((open) => !open))
  useShortcut('shortcutSheet', () => setShortcutsOpen(true))
  useShortcut('newIdea', commands.newIdea, { enabled: canCreateIdeas })
  useShortcut('goToMyWork', () => void navigate({ to: '/' }), { enabled: signedIn })

  const staticGroups: CommandGroupData[] = [
    {
      heading: 'Actions',
      actions: signedIn
        ? [
            ...(canCreateIdeas
              ? [
                  {
                    id: 'new-idea',
                    label: 'New idea',
                    icon: <Lightbulb />,
                    shortcut: SHORTCUTS.newIdea.keys,
                    keywords: ['create', 'submit', 'add'],
                    onSelect: commands.newIdea,
                  },
                ]
              : []),
            ...(me.data?.is_platform_admin
              ? [
                  {
                    id: 'new-project',
                    label: 'New project',
                    icon: <FolderPlus />,
                    keywords: ['create', 'add'],
                    onSelect: openCreateProject,
                  },
                ]
              : []),
          ]
        : [],
    },
    {
      heading: 'Go to',
      actions: [
        ...(signedIn
          ? [
              {
                id: 'my-work',
                label: 'My work',
                icon: <Inbox />,
                shortcut: SHORTCUTS.goToMyWork.keys,
                keywords: ['home', 'inbox', 'evaluations'],
                onSelect: () => void navigate({ to: '/' }),
              },
              ...(projects.data ?? []).map((project) => ({
                id: `project-${project.slug}`,
                label: project.name,
                hint: 'Project',
                icon: <ProjectTile name={project.name} className="size-4" />,
                keywords: ['project', project.slug, project.key],
                onSelect: () => void navigate({ to: '/p/$slug', params: { slug: project.slug } }),
              })),
              {
                id: 'settings',
                label: 'Settings',
                icon: <Settings />,
                onSelect: () => void navigate({ to: '/settings' }),
              },
            ]
          : []),
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
        resolvedTheme === 'dark'
          ? {
              id: 'theme-light',
              label: 'Switch to light theme',
              icon: <Sun />,
              keywords: ['appearance', 'toggle', 'theme', 'mode'],
              onSelect: () => setPreference('light'),
            }
          : {
              id: 'theme-dark',
              label: 'Switch to dark theme',
              icon: <Moon />,
              keywords: ['appearance', 'toggle', 'theme', 'mode'],
              onSelect: () => setPreference('dark'),
            },
        {
          id: 'theme-system',
          label: 'Use system theme',
          icon: <Monitor />,
          keywords: ['appearance', 'auto', 'theme'],
          onSelect: () => setPreference('system'),
        },
        {
          id: 'shortcuts',
          label: 'Keyboard shortcuts',
          icon: <Keyboard />,
          shortcut: SHORTCUTS.shortcutSheet.keys,
          keywords: ['help', 'keys'],
          onSelect: commands.openShortcutSheet,
        },
        ...(signedIn
          ? [
              {
                id: 'sign-out',
                label: 'Sign out',
                icon: <LogOut />,
                keywords: ['log out', 'logout'],
                onSelect: signOut,
              },
            ]
          : []),
      ],
    },
  ]

  const query = search.trim()
  const ideaResults: CommandGroupData = {
    heading: 'Ideas',
    actions: query
      ? (results.data?.ideas ?? []).map((idea) => ({
          id: `idea-${idea.id}`,
          label: idea.title,
          hint: `${idea.key} · ${idea.project.name}`,
          icon: <StatusDot tone={statusTone(idea.status, idea.resolution)} className="mx-1" />,
          onSelect: () => void navigate({ to: '/ideas/$ideaKey', params: { ideaKey: idea.key } }),
        }))
      : [],
  }

  const groups: CommandGroupData[] = [
    ...contextGroups.map((group) => ({
      heading: group.heading,
      actions: filterActions(group.actions, query),
    })),
    ideaResults,
    ...staticGroups.map((group) => ({ ...group, actions: filterActions(group.actions, query) })),
  ]

  return (
    <AppCommandsContext value={commands}>
      {children}
      <CommandPalette
        open={paletteOpen}
        onOpenChange={(open) => {
          setPaletteOpen(open)
          if (!open) setSearch('')
        }}
        groups={groups}
        search={search}
        onSearchChange={setSearch}
        shouldFilter={false}
        loading={Boolean(query) && results.isSearching && ideaResults.actions.length === 0}
        placeholder={signedIn ? 'Search ideas and projects, or type a command…' : undefined}
      />
      <ShortcutSheet open={shortcutsOpen} onOpenChange={setShortcutsOpen} />
    </AppCommandsContext>
  )
}

const MIN_SCORE = 0.02

/** cmdk's fuzzy scoring, applied to local actions (server results are already ranked). */
function filterActions(actions: CommandAction[], query: string): CommandAction[] {
  if (!query) return actions
  return (
    actions
      .map((action) => ({
        action,
        score: defaultFilter(`${action.label} ${action.hint ?? ''}`, query, action.keywords),
      }))
      // Drop scattered one-letter matches (e.g. "return" in "customer-innovation").
      .filter(({ score }) => score >= MIN_SCORE)
      .sort((a, b) => b.score - a.score)
      .map(({ action }) => action)
  )
}

export function useAppCommands(): AppCommands {
  const context = use(AppCommandsContext)
  if (!context) throw new Error('useAppCommands must be used inside <AppCommandsProvider>')
  return context
}
