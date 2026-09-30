import { useState } from 'react'

import { Card } from '@/components/ui/card'
import { Field } from '@/components/ui/field'
import { Markdown } from '@/components/ui/markdown'
import { StatusBadge } from '@/components/ui/status-badge'
import { Switch } from '@/components/ui/switch'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'

import { BoardExample, EvaluateExample, EvaluateSheet, IdeaListRow, IdeaSidebar } from './patterns'
import { IDEAS, SAMPLE_MARKDOWN } from './sample-data'
import { Code, DesignSection, Specimen } from './specimen'

export function PatternsSection() {
  const [blind, setBlind] = useState(false)
  return (
    <>
      <DesignSection
        id="shell"
        title="App shell"
        description={
          <>
            Sidebar (collapse with <Code>[</Code>), top bar with breadcrumbs and ⌘K search, and an
            inset content panel. On phones the sidebar becomes a drawer. This is the live app at{' '}
            <Code>/</Code>.
          </>
        }
      >
        <div className="overflow-hidden rounded-lg border shadow-overlay">
          <iframe
            src="/"
            title="App shell preview"
            className="block h-[34rem] w-full bg-background"
          />
        </div>
      </DesignSection>

      <DesignSection
        id="idea-list"
        title="Idea list & board"
        description="The project page toggles between a dense List and a Board grouped by status. Owners and admins can drag cards between columns."
      >
        <Specimen title="List rows" flush>
          {IDEAS.map((idea) => (
            <IdeaListRow key={idea.id} idea={idea} />
          ))}
        </Specimen>
        <Specimen
          title="Board columns & cards"
          description="The tilted card shows the dragging state (shadow-raised)."
        >
          <BoardExample />
        </Specimen>
      </DesignSection>

      <DesignSection
        id="evaluate"
        title="Evaluate"
        description="One row per criterion: name, one-line description, a 1–5 segmented control with hover guidance and an optional comment. The full flow lives in a side sheet (a bottom sheet on phones)."
      >
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_16rem]">
          <Card className="p-5">
            <EvaluateExample />
          </Card>
          <Specimen title="Open the real thing" className="flex flex-col items-start gap-3">
            <p className="text-sm text-muted">
              All five criteria, recommendation, progress and Submit — try it at phone width too.
            </p>
            <EvaluateSheet />
          </Specimen>
        </div>
      </DesignSection>

      <DesignSection
        id="idea-sidebar"
        title="Idea page"
        description="Content on the left, facts on the right. Scores stay locked until you submit, then reveal with a short animation."
      >
        <Card className="overflow-hidden">
          <div className="flex items-center justify-between gap-4 border-b border-subtle px-5 py-3">
            <Field label="Preview as an evaluator who hasn’t submitted" inline>
              <Switch checked={blind} onCheckedChange={setBlind} />
            </Field>
          </div>
          <div className="grid lg:grid-cols-[minmax(0,1fr)_20rem]">
            <div className="flex min-w-0 flex-col gap-4 p-5 lg:p-8">
              <div className="flex items-center gap-2 text-sm text-muted">
                <span className="tabular-nums">CI-42</span>
                <StatusBadge status="evaluating" variant="plain" />
              </div>
              <h3 className="text-2xl font-semibold text-primary">
                Self-serve returns portal for business customers
              </h3>
              <p className="text-lg text-secondary">
                Let account admins start and track returns without calling support.
              </p>
              <Tabs defaultValue="overview" className="mt-2">
                <TabsList>
                  <TabsTrigger value="overview">Overview</TabsTrigger>
                  <TabsTrigger value="evaluations">Evaluations</TabsTrigger>
                  <TabsTrigger value="proposal">Proposal</TabsTrigger>
                </TabsList>
                <TabsContent value="overview">
                  <Markdown>{SAMPLE_MARKDOWN}</Markdown>
                </TabsContent>
                <TabsContent value="evaluations" className="text-sm text-muted">
                  Individual evaluations appear here after you submit yours.
                </TabsContent>
                <TabsContent value="proposal" className="text-sm text-muted">
                  Available once the idea is shortlisted.
                </TabsContent>
              </Tabs>
            </div>
            <div className="border-t border-subtle p-5 lg:border-t-0 lg:border-l lg:p-6">
              <IdeaSidebar key={String(blind)} blind={blind} />
            </div>
          </div>
        </Card>
      </DesignSection>
    </>
  )
}
