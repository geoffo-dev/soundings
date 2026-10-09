/**
 * Test-only: renders idea-page pieces against the MSW mock API with a real
 * query client and the page context built from live queries (so a submit that
 * refetches the idea reveals scores as it does on the page).
 */
import { QueryClientProvider, type QueryClient } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import type { ReactNode } from 'react'
import { vi } from 'vitest'

import { useMe } from '@/api/auth'
import { api } from '@/api/client'
import { useIdea } from '@/api/ideas'
import { useProject } from '@/api/projects'
import type { CurrentUser, IdeaDetail } from '@/api/types'
import { TooltipProvider } from '@/components/ui/tooltip'

import { IdeaPageProvider, statusLabeller, type IdeaPageContextValue } from './idea-context'

export async function signInAs(userId: string) {
  await api.POST('/api/v1/auth/dev/login', { body: { user_id: userId } })
}

export type HarnessOverrides = Partial<
  Pick<IdeaPageContextValue, 'openEvaluate' | 'openDialog' | 'setTab'>
>

function Harness({
  ideaKey,
  overrides,
  children,
}: {
  ideaKey: string
  overrides: HarnessOverrides
  children: ReactNode
}) {
  const me = useMe()
  const idea = useIdea(ideaKey)
  if (!me.data || !idea.data) return <p>Loading harness…</p>
  return (
    <WithProject ideaKey={ideaKey} idea={idea.data} me={me.data} overrides={overrides}>
      {children}
    </WithProject>
  )
}

function WithProject({
  ideaKey,
  idea,
  me,
  overrides,
  children,
}: {
  ideaKey: string
  idea: IdeaDetail
  me: CurrentUser
  overrides: HarnessOverrides
  children: ReactNode
}) {
  const project = useProject(idea.project.slug)
  if (!project.data) return <p>Loading harness…</p>
  const value: IdeaPageContextValue = {
    ideaKey,
    idea,
    project: project.data,
    me,
    ownEvaluator: idea.evaluators.find((e) => e.user.id === me.id),
    archived: Boolean(project.data.archived_at),
    guest: !idea.permissions.can_view_project,
    researchStep: project.data.research_step,
    statusLabel: statusLabeller(project.data.status_labels),
    openDialog: vi.fn(),
    openEvaluate: vi.fn(),
    focusComment: vi.fn(),
    takeCommentFocus: () => false,
    commentFocusRequest: 0,
    setTab: vi.fn(),
    ...overrides,
  }
  return <IdeaPageProvider value={value}>{children}</IdeaPageProvider>
}

export function renderWithIdea(
  queryClient: QueryClient,
  ideaKey: string,
  ui: ReactNode,
  overrides: HarnessOverrides = {},
) {
  return render(
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <Harness ideaKey={ideaKey} overrides={overrides}>
          {ui}
        </Harness>
      </TooltipProvider>
    </QueryClientProvider>,
  )
}
