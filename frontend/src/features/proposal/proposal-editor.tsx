import { useQueryClient } from '@tanstack/react-query'
import { useBlocker } from '@tanstack/react-router'
import { FileDown, FileText, Info, MessageSquarePlus } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react'

import {
  saveProposalSection,
  storeProposalSection,
  useProposalSuggestions,
  useProposalThreads,
} from '@/api/proposals'
import type {
  CurrentUser,
  IdeaDetail,
  Proposal,
  ProposalPermissions,
  ProposalSectionKey,
  ProposalSuggestion,
  ProposalThread,
} from '@/api/types'
import { Button } from '@/components/ui/button'
import { Callout } from '@/components/ui/callout'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { SM_UP, useMediaQuery } from '@/lib/media'
import type { CommandAction } from '@/components/ui/command-palette'
import { useCommands } from '@/lib/command-registry'
import { readDrafts, writeDraft } from '@/lib/drafts'
import { SHORTCUTS, useShortcut } from '@/lib/shortcuts'

import {
  ProposalEditorProvider,
  type ProposalEditorContextValue,
  type SectionMode,
} from './editor-context'
import { EditorBar, useExportRunner } from './editor-bar'
import { Outline } from './outline'
import { RemovedSections } from './removed-sections'
import { ResearchAppendix } from './research-appendix'
import { ProposalSaveStore } from './save-store'
import { SectionRow } from './section'
import { CommentsSheet } from './threads'
import { hasContent, sectionDomId } from './text'

const NO_SUGGESTION_RIGHTS = { can_suggest: false, can_decide: false } as const

/** Tailwind's `lg`: margin comments beside each section from here up. */
const LG_UP = '(min-width: 64rem)'

export interface ProposalEditorProps {
  ideaKey: string
  idea: IdeaDetail
  me: CurrentUser
  proposal: Proposal
  permissions: ProposalPermissions
}

/**
 * The proposal: a bar (save state, export), the outline (sticky on wide
 * screens, a jump list below), then one row per template section — its text
 * (an auto-growing textarea with Write / Preview for editors, rendered
 * Markdown for everyone else) and its margin threads.
 */
export function ProposalEditor({ ideaKey, idea, me, proposal, permissions }: ProposalEditorProps) {
  const queryClient = useQueryClient()
  const keptPrefix = `proposal-removed:${ideaKey.toUpperCase()}:`
  const [store] = useState(() => {
    const created = new ProposalSaveStore(
      proposal.sections,
      (key, bodyMd, baseVersion, options) =>
        saveProposalSection(queryClient, ideaKey, key, bodyMd, baseVersion, options),
      (section) => storeProposalSection(queryClient, ideaKey, section),
      {
        // Phase 8: text of a section removed from the template meanwhile, kept locally.
        keep: (key, title, text) =>
          writeDraft(me.id, `${keptPrefix}${key}`, JSON.stringify({ title, text })),
        forget: (key) => writeDraft(me.id, `${keptPrefix}${key}`, null),
      },
    )
    for (const [name, value] of readDrafts(me.id, keptPrefix)) {
      try {
        const kept = JSON.parse(value) as { title?: unknown; text?: unknown }
        if (typeof kept.title === 'string' && typeof kept.text === 'string') {
          created.restoreKept(name.slice(keptPrefix.length), kept.title, kept.text)
        }
      } catch {
        // Not ours: leave it.
      }
    }
    return created
  })
  // Newer text from a refetch (someone else saved) where nothing is unsaved here.
  useEffect(() => store.receive(proposal.sections), [store, proposal.sections])
  // Leaving the tab sends what is waiting instead of dropping it.
  useEffect(() => {
    store.resume()
    return () => store.dispose()
  }, [store])
  useLeaveWarning(store)

  const threadsQuery = useProposalThreads(ideaKey)
  const threads = useMemo(() => {
    if (!threadsQuery.data) return undefined
    const map = new Map<ProposalSectionKey, ProposalThread[]>()
    for (const thread of threadsQuery.data.items) {
      const list = map.get(thread.section_key) ?? []
      list.push(thread)
      map.set(thread.section_key, list)
    }
    return map
  }, [threadsQuery.data])

  // Phase 5: suggestions from people, MCP clients and AI agents, shown by their section.
  const suggestionsQuery = useProposalSuggestions(ideaKey)
  const suggestions = useMemo(() => {
    const map = new Map<ProposalSectionKey, ProposalSuggestion[]>()
    for (const suggestion of suggestionsQuery.data?.items ?? []) {
      const list = map.get(suggestion.section_key) ?? []
      list.push(suggestion)
      map.set(suggestion.section_key, list)
    }
    return map
  }, [suggestionsQuery.data])
  const suggestionPermissions = suggestionsQuery.data?.permissions ?? NO_SUGGESTION_RIGHTS

  const [modes, setModes] = useState<ReadonlyMap<ProposalSectionKey, SectionMode>>(new Map())
  const [composingIn, setComposingIn] = useState<ProposalSectionKey | null>(null)
  const [sheetFor, setSheetFor] = useState<ProposalSectionKey | null>(null)
  const firstKey = proposal.sections[0]?.key ?? 'summary'
  const [current, setCurrent] = useState<ProposalSectionKey>(firstKey)
  const wide = useMediaQuery(LG_UP)

  const setMode = useCallback((key: ProposalSectionKey, mode: SectionMode) => {
    setModes((previous) => new Map(previous).set(key, mode))
  }, [])
  // Phones read first (editing works, but isn't the target): written sections open in Preview.
  const phone = !useMediaQuery(SM_UP)
  const modeOf = useCallback(
    (key: ProposalSectionKey) =>
      modes.get(key) ?? (phone && hasContent(store.get(key)?.saved ?? '') ? 'preview' : 'write'),
    [modes, phone, store],
  )
  const toggleSectionMode = useCallback(
    (key: ProposalSectionKey) => {
      const next = modeOf(key) === 'write' ? 'preview' : 'write'
      setMode(key, next)
      requestAnimationFrame(() => {
        const section = document.getElementById(sectionDomId(key))
        const target =
          next === 'write'
            ? section?.querySelector<HTMLElement>('textarea[data-section-text]')
            : document.getElementById(`${sectionDomId(key)}-preview`)
        target?.focus()
      })
    },
    [modeOf, setMode],
  )

  // While a smooth scroll to a section runs, it passes other sections: the scroll spy
  // waits for it to end, so j/k/c carry on from the section asked for.
  const navigation = useRef<{ settle: () => void } | null>(null)
  const focusSection = useCallback(
    (key: ProposalSectionKey) => {
      setCurrent(key)
      const section = document.getElementById(sectionDomId(key))
      if (!section) return
      navigation.current?.settle()
      const scroller = document.getElementById('main')
      const settle = () => {
        window.clearTimeout(timer)
        scroller?.removeEventListener('scrollend', settle)
        if (navigation.current?.settle === settle) navigation.current = null
      }
      // `scrollend` doesn't fire when there is nothing to scroll: a timer ends it too.
      const timer = window.setTimeout(settle, 1000)
      scroller?.addEventListener('scrollend', settle)
      navigation.current = { settle }
      section.scrollIntoView({ block: 'start', behavior: 'smooth' })
      // Editors land in the text; readers on the heading (it is focusable).
      const field = section.querySelector<HTMLTextAreaElement>('textarea[data-section-text]')
      const target = field ?? section.querySelector<HTMLElement>('[data-section-heading]')
      target?.focus({ preventScroll: true })
    },
    [setCurrent],
  )

  const startComment = useCallback(
    (key: ProposalSectionKey) => {
      if (!permissions.can_comment) return
      setCurrent(key)
      if (wide) setComposingIn(key)
      else setSheetFor(key)
    },
    [permissions.can_comment, wide],
  )

  const keys = proposal.sections.map((section) => section.key)
  const move = (step: 1 | -1) => {
    const index = keys.indexOf(current)
    const next = keys[Math.min(keys.length - 1, Math.max(0, index + step))]
    if (next) focusSection(next)
  }
  useShortcut('proposalNextSection', () => move(1))
  useShortcut('proposalPreviousSection', () => move(-1))
  useShortcut('proposalComment', () => startComment(current), {
    enabled: permissions.can_comment,
  })
  useShortcut('proposalSave', () => void store.flush(), { enabled: permissions.can_edit })
  // ⌘↵ in a section's text or preview (comment boxes use it to post, and stop it first).
  useShortcut(
    'proposalPreview',
    (event) => {
      const body = (event.target as Element | null)?.closest('[data-section-body]')
      const key = body?.closest('[data-section-key]')?.getAttribute('data-section-key')
      if (!key) return
      event.preventDefault()
      toggleSectionMode(key)
    },
    { enabled: permissions.can_edit, preventDefault: false },
  )

  useScrollSpy(keys, setCurrent, navigation)

  const exporting = useExportRunner(ideaKey, store)
  const actions: CommandAction[] = []
  if (permissions.can_comment) {
    actions.push({
      id: 'proposal-comment',
      label: 'Comment on this section',
      icon: <MessageSquarePlus />,
      shortcut: SHORTCUTS.proposalComment.keys,
      keywords: ['comment', 'margin', 'thread'],
      onSelect: () => startComment(current),
    })
  }
  if (permissions.can_export) {
    actions.push(
      {
        id: 'proposal-export-pdf',
        label: 'Export proposal as PDF',
        icon: <FileDown />,
        keywords: ['download', 'pdf', 'export', 'print'],
        onSelect: () => exporting.run('pdf'),
      },
      {
        id: 'proposal-export-markdown',
        label: 'Export proposal as Markdown',
        icon: <FileText />,
        keywords: ['download', 'markdown', 'export'],
        onSelect: () => exporting.run('markdown'),
      },
    )
  }
  useCommands({ id: 'proposal', heading: 'Proposal', actions })

  const context: ProposalEditorContextValue = {
    ideaKey,
    idea,
    me,
    permissions,
    store,
    threads,
    threadsError: threadsQuery.isError,
    retryThreads: () => void threadsQuery.refetch(),
    suggestions,
    // Kept while a refetch fails: only a list that never loaded is an error here.
    suggestionsError: suggestionsQuery.isError && !suggestionsQuery.data,
    retrySuggestions: () => void suggestionsQuery.refetch(),
    suggestionPermissions,
    modeOf,
    setMode,
    toggleSectionMode,
    composingIn,
    setComposingIn,
    sheetFor,
    setSheetFor,
    startComment,
    focusSection,
    exporting,
    current,
    setCurrent,
  }

  const readOnlyBecauseOfStatus =
    !permissions.can_edit &&
    idea.status !== 'shortlisted' &&
    idea.status !== 'proposal' &&
    idea.status !== 'research'

  return (
    <ProposalEditorProvider value={context}>
      <div className="flex flex-col" data-testid="proposal-editor">
        <EditorBar proposal={proposal} />
        {readOnlyBecauseOfStatus && (
          <Callout
            role="status"
            icon={<Info />}
            className="mt-4"
            title="This proposal is read-only while the idea isn’t Shortlisted or in Proposal"
          >
            It stays readable, commentable and exportable. Move the idea back to Shortlisted or
            Proposal to edit it again.
          </Callout>
        )}
        <div className="grid gap-x-10 xl:grid-cols-[12rem_minmax(0,1fr)]">
          <Outline sections={proposal.sections} className="hidden xl:flex" />
          <div className="flex min-w-0 flex-col">
            {proposal.sections.map((section, index) => (
              <SectionRow key={section.key} section={section} index={index} />
            ))}
            <RemovedSections store={store} activeKeys={keys} />
            <ResearchAppendix ideaKey={ideaKey} />
          </div>
        </div>
      </div>
      <CommentsSheet sections={proposal.sections} />
      <UnsavedNavigationGuard store={store} />
    </ProposalEditorProvider>
  )
}

/** The browser's "Leave site?" prompt while something isn't saved. */
function useLeaveWarning(store: ProposalSaveStore) {
  useEffect(() => {
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      if (!store.hasUnsaved()) return
      // Try once more on the way out; the prompt gives it time.
      void store.flush({ keepalive: true })
      event.preventDefault()
    }
    window.addEventListener('beforeunload', onBeforeUnload)
    return () => window.removeEventListener('beforeunload', onBeforeUnload)
  }, [store])
}

/**
 * In-app navigation (another page, another tab of the idea) while a section
 * failed to save or waits for a conflict decision: ask first. Pending saves
 * don't block: they are sent as the editor goes.
 */
function UnsavedNavigationGuard({ store }: { store: ProposalSaveStore }) {
  const stuck = useSyncExternalStore(store.subscribe, () =>
    store.all().some(([, state]) => state.status === 'error' || state.status === 'conflict'),
  )
  const blocker = useBlocker({
    shouldBlockFn: () => true,
    disabled: !stuck,
    withResolver: true,
  })
  return (
    <Dialog
      open={blocker.status === 'blocked'}
      onOpenChange={(open) => {
        if (!open) blocker.reset?.()
      }}
    >
      <DialogContent size="sm" role="alertdialog">
        <DialogHeader>
          <DialogTitle>Leave without saving?</DialogTitle>
          <DialogDescription>
            Some of your proposal text hasn’t been saved. If you leave now, it will be lost.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter className="pt-5">
          <Button variant="ghost" onClick={() => blocker.reset?.()}>
            Keep editing
          </Button>
          <Button variant="destructive" onClick={() => blocker.proceed?.()}>
            Discard changes
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/**
 * The section near the top of the scroll area is "current" (outline highlight, j/k, c),
 * except while `navigation` scrolls to the section that was asked for.
 */
function useScrollSpy(
  keys: ProposalSectionKey[],
  setCurrent: (key: ProposalSectionKey) => void,
  navigation: { readonly current: unknown },
) {
  const joined = keys.join(',')
  useEffect(() => {
    if (typeof IntersectionObserver === 'undefined') return
    const root = document.getElementById('main')
    const observer = new IntersectionObserver(
      (entries) => {
        if (navigation.current) return
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0]
        const key = visible?.target.getAttribute('data-section-key')
        if (key) setCurrent(key)
      },
      { root, rootMargin: '-15% 0px -70% 0px' },
    )
    for (const key of joined.split(',')) {
      const element = document.getElementById(sectionDomId(key))
      if (element) observer.observe(element)
    }
    return () => observer.disconnect()
  }, [joined, setCurrent, navigation])
}
