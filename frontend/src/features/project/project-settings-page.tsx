import { Link, useNavigate } from '@tanstack/react-router'
import { useEffect, useRef } from 'react'
import { ArrowLeft } from 'lucide-react'

import { useProject } from '@/api/projects'
import type { Project } from '@/api/types'
import { Page, PageHeader } from '@/components/layout/page'
import { Button } from '@/components/ui/button'
import { ProjectSettingsSkeleton } from '@/features/project/project-page-states'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { GeneralSettings, GeneralSummary } from '@/features/project/settings/general-settings'
import { MembersSettings } from '@/features/project/settings/members-settings'
import { RubricEditor, RubricSummary } from '@/features/project/settings/rubric-editor'
import { UnsavedChangesGuard } from '@/features/project/settings/settings-layout'
import { StatusLabelsSettings } from '@/features/project/settings/status-labels-settings'
import {
  ADMIN_SETTINGS_TABS,
  SETTINGS_TABS,
  type SettingsTab,
} from '@/features/project/settings/settings-tabs'
import { ProjectBrandingSettings } from '@/features/branding/project-branding-settings'
import { PublicFormSettingsSection } from '@/features/public/public-form-settings'

const TAB_LABELS: Record<SettingsTab, string> = {
  general: 'General',
  members: 'Members',
  rubric: 'Rubric',
  'public-form': 'Public form',
}

/**
 * Project settings (SPEC §5 screen 7, wireframe 07): General (with the status
 * labels), Members, Rubric and Public form (with the project's branding), short
 * forms each with its own Save. Admins edit; everyone else with access sees the
 * same information read-only.
 */
export function ProjectSettingsPage({
  slug,
  tab = 'general',
}: {
  slug: string
  tab?: SettingsTab
}) {
  const project = useProject(slug)
  if (!project.data) return <ProjectSettingsSkeleton />
  return <SettingsContent key={slug} project={project.data} tab={tab} />
}

function SettingsContent({ project, tab }: { project: Project; tab: SettingsTab }) {
  const navigate = useNavigate()
  const canManage = project.permissions.can_manage
  // The public form (and branding) are admin-only forms.
  const tabs: readonly SettingsTab[] = canManage
    ? SETTINGS_TABS
    : SETTINGS_TABS.filter((t) => !ADMIN_SETTINGS_TABS.includes(t))
  const current = tabs.includes(tab) ? tab : 'general'
  // On phones the tab row scrolls sideways: keep the current tab in view.
  const tabsRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    tabsRef.current
      ?.querySelector<HTMLElement>('[role="tab"][data-state="active"]')
      ?.scrollIntoView({ block: 'nearest', inline: 'nearest' })
  }, [current])

  return (
    <Page>
      <PageHeader
        title="Project settings"
        description={`${project.name} · ${canManage ? 'Changes apply to everyone in the project.' : 'Only project admins can change these settings.'}`}
        actions={
          <Button asChild variant="ghost" size="sm" className="text-secondary">
            <Link to="/p/$slug" params={{ slug: project.slug }}>
              <ArrowLeft /> Back to ideas
            </Link>
          </Button>
        }
      />
      <UnsavedChangesGuard>
        <Tabs
          value={current}
          onValueChange={(next) =>
            void navigate({
              to: '/p/$slug/settings',
              params: { slug: project.slug },
              search: { tab: next === 'general' ? undefined : (next as SettingsTab) },
              replace: true,
            })
          }
          className="flex flex-col gap-6"
        >
          <TabsList ref={tabsRef} aria-label="Settings">
            {tabs.map((value) => (
              <TabsTrigger key={value} value={value}>
                {TAB_LABELS[value]}
              </TabsTrigger>
            ))}
          </TabsList>
          {/* Forms stay mounted, so switching tabs never loses unsaved edits. */}
          <TabsContent
            value="general"
            forceMount
            className="flex flex-col gap-12 pt-0 data-[state=inactive]:hidden"
          >
            {canManage ? (
              <>
                <GeneralSettings project={project} active={current === 'general'} />
                <div id="status-labels" className="scroll-mt-6">
                  <StatusLabelsSettings project={project} active={current === 'general'} />
                </div>
              </>
            ) : (
              <GeneralSummary project={project} />
            )}
          </TabsContent>
          <TabsContent value="members" forceMount className="pt-0 data-[state=inactive]:hidden">
            <MembersSettings project={project} />
          </TabsContent>
          <TabsContent value="rubric" forceMount className="pt-0 data-[state=inactive]:hidden">
            {canManage ? (
              <RubricEditor project={project} active={current === 'rubric'} />
            ) : (
              <RubricSummary project={project} />
            )}
          </TabsContent>
          {canManage && (
            <TabsContent
              value="public-form"
              forceMount
              className="flex flex-col gap-12 pt-0 data-[state=inactive]:hidden"
            >
              <PublicFormSettingsSection project={project} active={current === 'public-form'} />
              <div id="branding" className="scroll-mt-6">
                <ProjectBrandingSettings project={project} active={current === 'public-form'} />
              </div>
            </TabsContent>
          )}
        </Tabs>
      </UnsavedChangesGuard>
    </Page>
  )
}
