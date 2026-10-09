import { useLocation, useNavigate } from '@tanstack/react-router'
import { CloudOff, FolderPlus, Plus, Sprout } from 'lucide-react'
import { useEffect } from 'react'

import { describeError } from '@/api/errors'
import { useProjects } from '@/api/projects'
import { useMyWork } from '@/api/work'
import { useAppCommands } from '@/components/layout/app-commands'
import { Page, PageHeader } from '@/components/layout/page'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'
import { ariaKeys, ButtonShortcut } from '@/components/ui/kbd'
import { useCurrentUser } from '@/features/auth/current-user'
import { openCreateProject } from '@/lib/dialogs'
import { useListNavigation } from '@/lib/list-navigation'
import { SHORTCUTS, useShortcut } from '@/lib/shortcuts'

import { EvaluationsDueSection } from './evaluations-due'
import { OwnedIdeasSection } from './owned-ideas'
import { RecentIdeasSection } from './recent-ideas'
import { ResearchToDoSection } from './research-to-do'

/**
 * My work (SPEC §5 screen 1, wireframe 01): evaluations due, research to do (Phase
 * 8b), ideas I own by status, and what changed recently. j/k or ↑/↓ move between rows, Enter
 * opens, E evaluates the focused (or most urgent) due idea.
 */
export function MyWorkPage() {
  const work = useMyWork()
  const projects = useProjects()
  const user = useCurrentUser()
  const navigate = useNavigate()
  const { newIdea, canCreateIdeas } = useAppCommands()
  const noProjects = projects.data?.length === 0
  // Phase 8b: someone outside every project may still research an idea (a guest
  // researcher): My work is then just their "Research to do".
  const researching = (work.data?.research_to_do.length ?? 0) > 0
  const guestOnly = noProjects && researching
  // A fresh install, or someone no project has added yet: say how to start instead of
  // three empty sections.
  const firstRun = noProjects && !researching && !work.isPending
  const { listRef } = useListNavigation()
  const hash = useLocation({ select: (location) => location.hash })
  const due = work.data?.evaluations_due
  const hasDue = (due?.length ?? 0) > 0

  // Sidebar links (/#evaluations, /#research, /#owned) scroll once the sections exist.
  useEffect(() => {
    if (hash && work.data) document.getElementById(hash)?.scrollIntoView({ block: 'start' })
  }, [hash, work.data])

  useShortcut(
    'evaluate',
    () => {
      const focused = document.activeElement?.closest<HTMLElement>('[data-evaluate-key]')
      const key = focused?.dataset.evaluateKey ?? due?.[0]?.idea.key
      if (key) {
        void navigate({
          to: '/ideas/$ideaKey',
          params: { ideaKey: key },
          search: { evaluate: true },
        })
      }
    },
    { enabled: hasDue },
  )

  return (
    <Page>
      <PageHeader
        title="My work"
        description={
          guestOnly
            ? 'Research you’ve been asked to do.'
            : 'Evaluations waiting for you, ideas you own and what changed recently.'
        }
        actions={
          // The most urgent "Evaluate" is the primary action while evaluations are due.
          canCreateIdeas &&
          !firstRun &&
          !guestOnly && (
            <Button
              variant={hasDue ? 'outline' : 'primary'}
              onClick={newIdea}
              aria-keyshortcuts={ariaKeys(SHORTCUTS.newIdea.keys)}
            >
              <Plus />
              New idea
              <ButtonShortcut keys={SHORTCUTS.newIdea.keys} tone={hasDue ? 'default' : 'accent'} />
            </Button>
          )
        }
      />

      {firstRun ? (
        <div className="rounded-lg border">
          {user.is_platform_admin ? (
            <EmptyState
              headingLevel={2}
              icon={<Sprout />}
              title="Welcome to Soundings"
              description="Start with a project: a place for ideas, the people who weigh them and the rubric they score against. Press N to create one."
              action={
                <Button
                  variant="primary"
                  onClick={openCreateProject}
                  aria-keyshortcuts={ariaKeys(SHORTCUTS.newIdea.keys)}
                >
                  <FolderPlus />
                  Create a project
                </Button>
              }
            />
          ) : (
            <EmptyState
              headingLevel={2}
              icon={<Sprout />}
              title="You’re not in any project yet"
              description="Ask an admin to add you to a project. Its ideas, and anything you’re asked to evaluate, will show up here."
            />
          )}
        </div>
      ) : work.isError ? (
        <div className="rounded-lg border">
          <EmptyState
            role="alert"
            icon={<CloudOff />}
            title="We couldn’t load your work"
            description={describeError(work.error).description ?? 'Please try again in a moment.'}
            action={
              <Button
                variant="primary"
                loading={work.isFetching}
                onClick={() => void work.refetch()}
              >
                Try again
              </Button>
            }
          />
        </div>
      ) : guestOnly ? (
        <div ref={listRef} className="flex flex-col gap-10">
          <ResearchToDoSection
            items={work.data?.research_to_do}
            total={work.data?.counts.research_to_do}
            nextCursor={work.data?.research_to_do_next_cursor}
          />
          <p className="px-1 text-sm text-muted">
            You’re not in any project. You see only the ideas you’re asked to research, never their
            scores or proposals.
          </p>
        </div>
      ) : (
        <div ref={listRef} className="flex flex-col gap-10">
          <EvaluationsDueSection
            items={due}
            total={work.data?.counts.evaluations_due}
            nextCursor={work.data?.evaluations_due_next_cursor}
          />
          <ResearchToDoSection
            items={work.data?.research_to_do}
            total={work.data?.counts.research_to_do}
            nextCursor={work.data?.research_to_do_next_cursor}
          />
          <OwnedIdeasSection groups={work.data?.owned} openCount={work.data?.counts.owned_open} />
          <RecentIdeasSection recent={work.data?.recent} />
        </div>
      )}
    </Page>
  )
}
