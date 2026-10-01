import { CloudOff } from 'lucide-react'

import { useProjectBranding } from '@/api/branding'
import type { Project } from '@/api/types'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'
import { SettingsSection } from '@/features/project/settings/settings-layout'

import { BrandingSettingsForm } from './branding-settings-form'
import { BrandingSkeleton } from './global-branding-page'

/**
 * Project settings → Branding (project admins; contract-phase4 §3.10): an
 * optional override of the global branding where the project faces outward
 * (its public form and tracking pages, its emails to submitters, its exported
 * proposals). Inside Soundings everyone keeps seeing the global branding.
 */
export function ProjectBrandingSettings({
  project,
  active,
}: {
  project: Project
  active: boolean
}) {
  const settings = useProjectBranding(project.slug)
  return (
    <SettingsSection
      title="Branding"
      description="Optional: how this project presents itself outside Soundings, on its public form, in emails to people who send ideas and on exported proposals. Empty fields use the global branding; inside the app everyone sees the global branding."
    >
      {settings.data ? (
        <BrandingSettingsForm
          scope={{ kind: 'project', slug: project.slug }}
          settings={settings.data}
          active={active}
          projectName={project.name}
          readOnly={Boolean(project.archived_at)}
        />
      ) : settings.isError ? (
        <EmptyState
          role="alert"
          size="compact"
          headingLevel={3}
          icon={<CloudOff />}
          title="We couldn’t load the branding"
          description="Check your connection and try again."
          action={
            <Button variant="primary" onClick={() => void settings.refetch()}>
              Try again
            </Button>
          }
        />
      ) : (
        <BrandingSkeleton />
      )}
    </SettingsSection>
  )
}
