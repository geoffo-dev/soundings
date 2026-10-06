import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useParams } from '@tanstack/react-router'
import { defaultFilter } from 'cmdk'
import {
  Bell,
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
import { CommandPalette, type CommandGroupData } from '@/components/ui/command-palette'
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

/** Admin settings pages in the palette (features/admin). */
const ADMIN_PAGES = [
  { id: 'users', label: 'Users', to: '/settings/users', keywords: ['people', 'accounts'] },
  { id: 'groups', label: 'Groups', to: '/settings/groups', keywords: ['mapping', 'sync'] },
  { id: 'sso', label: 'Sign-in (SSO)', to: '/settings/sso', keywords: ['oidc', 'login'] },
  { id: 'email', label: 'Email', to: '/settings/email', keywords: ['smtp', 'outbox', 'mail'] },
  {
    id: 'all-api-keys',
    label: 'All API keys',
    to: '/settings/all-api-keys',
    keywords: ['keys', 'tokens', 'mcp', 'agents', 'revoke'],
  },
  {
    id: 'ai-agents',
    label: 'AI agents',
    to: '/settings/ai-agents',
    keywords: ['kagent', 'ai', 'agents', 'a2a', 'evaluator', 'research'],
  },
  { id: 'audit', label: 'Audit log', to: '/settings/audit', keywords: ['history', 'log'] },
] as const

const AppCommandsContext = createContext<AppCommands | null>(null)

/**
 * Global keyboard layer and ⌘K palette: "n" new idea, "?" shortcuts, "g m" My
 * work, "g i" notifications. Pages add context actions with `useCommands()` (lib/command-registry).
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

  // The session ended with the palette open: don't leave it over /login.
  const [wasSignedIn, setWasSignedIn] = useState(signedIn)
  if (wasSignedIn !== signedIn) {
    setWasSignedIn(signedIn)
    if (!signedIn) setPaletteOpen(false)
  }

  useShortcut('commandPalette', () => setPaletteOpen((open) => !open))
  useShortcut('shortcutSheet', () => setShortcutsOpen(true))
  useShortcut('newIdea', commands.newIdea, { enabled: canCreateIdeas })
  useShortcut('goToMyWork', () => void navigate({ to: '/' }), { enabled: signedIn })
  useShortcut('goToNotifications', () => void navigate({ to: '/notifications' }), {
    enabled: signedIn,
  })

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
              {
                id: 'notifications',
                label: 'Notifications',
                icon: <Bell />,
                shortcut: SHORTCUTS.goToNotifications.keys,
                keywords: ['inbox', 'bell', 'unread', 'mentions'],
                onSelect: () => void navigate({ to: '/notifications' }),
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
              {
                id: 'email-preferences',
                label: 'Email preferences',
                hint: 'Settings',
                icon: <Settings />,
                keywords: ['notifications', 'digest', 'unsubscribe', 'email'],
                onSelect: () => void navigate({ to: '/settings/notifications' }),
              },
              {
                id: 'api-keys',
                label: 'API keys',
                hint: 'Settings',
                icon: <Settings />,
                keywords: ['tokens', 'mcp', 'claude', 'assistant', 'integration'],
                onSelect: () => void navigate({ to: '/settings/api-keys' }),
              },
              // Admin settings (platform admins only; the pages are a 404 for anyone else).
              ...(me.data?.is_platform_admin
                ? ADMIN_PAGES.map((page) => ({
                    id: `settings-${page.id}`,
                    label: page.label,
                    hint: 'Admin',
                    icon: <Settings />,
                    keywords: ['admin', 'settings', ...page.keywords],
                    onSelect: () => void navigate({ to: page.to }),
                  }))
                : []),
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
    // Still typing, or the previous query's results while this one loads.
    pending: results.query !== query || results.isPlaceholderData,
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

  // Commands and projects (instant, local) above the ideas (server, late): the top
  // row, which Enter opens, doesn't move when the ideas arrive underneath.
  const groups: CommandGroupData[] = [
    ...rankGroups(
      [
        ...contextGroups.map((group) => ({ heading: group.heading, actions: group.actions })),
        ...staticGroups,
      ],
      query,
    ),
    ideaResults,
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

/**
 * Word starts and prefixes score 0.15 and up ("n" → New idea, "tools" → Internal
 * Tools); letters scattered across the words score about 0.03 or less.
 */
const MIN_SCORE = 0.1

/**
 * cmdk's fuzzy scoring for the local actions (server results are already ranked):
 * drops weak matches, sorts each group, and puts the group with the best match first
 * ("sign" → Sign out before Design system). Page actions come first on a tie.
 */
export function rankGroups(groups: CommandGroupData[], query: string): CommandGroupData[] {
  if (!query) return groups
  return groups
    .map((group) => {
      const scored = group.actions
        .map((action) => ({
          action,
          score: defaultFilter(`${action.label} ${action.hint ?? ''}`, query, action.keywords),
        }))
        // Drop scattered matches ("whats" in "My work … evaluations"): they would sit
        // above the ideas that do match.
        .filter(({ score }) => score >= MIN_SCORE)
        .sort((a, b) => b.score - a.score)
      return {
        group: { ...group, actions: scored.map(({ action }) => action) },
        best: scored[0]?.score ?? 0,
      }
    })
    .sort((a, b) => b.best - a.best)
    .map(({ group }) => group)
}

export function useAppCommands(): AppCommands {
  const context = use(AppCommandsContext)
  if (!context) throw new Error('useAppCommands must be used inside <AppCommandsProvider>')
  return context
}
