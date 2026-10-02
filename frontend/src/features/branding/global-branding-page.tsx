import { CloudOff } from 'lucide-react'

import { useGlobalBranding } from '@/api/branding'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'
import { Skeleton, SkeletonGroup } from '@/components/ui/skeleton'
import { AdminPageHeader } from '@/features/admin/settings-frame'
import { UnsavedChangesGuard } from '@/features/project/settings/settings-layout'

import { BrandingSettingsForm } from './branding-settings-form'

/**
 * Settings → Branding (platform admins; contract-phase4 §2 "Branding",
 * wireframe 07): the instance's name, logo, favicon, colours, font and email
 * footer, with a live preview. Projects may override it for their public
 * pages, their emails to submitters and their exported proposals.
 */
export function GlobalBrandingPage() {
  const settings = useGlobalBranding()
  return (
    <div className="flex flex-col gap-6">
      <AdminPageHeader
        title="Branding"
        description="How Soundings looks and introduces itself: the app, public forms, emails and exported proposals. Projects can override it for their public form, their emails to submitters and their PDFs."
      />
      {settings.data ? (
        // Leaving with unsaved changes asks first, as in project settings.
        <UnsavedChangesGuard>
          <BrandingSettingsForm
            scope={{ kind: 'global' }}
            settings={settings.data}
            projectName="your team"
          />
        </UnsavedChangesGuard>
      ) : settings.isError ? (
        <EmptyState
          role="alert"
          size="compact"
          headingLevel={2}
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
    </div>
  )
}

export function BrandingSkeleton() {
  return (
    <SkeletonGroup
      label="Loading the branding"
      className="grid gap-x-10 gap-y-8 xl:grid-cols-[minmax(0,1fr)_24rem]"
    >
      <div className="flex max-w-2xl flex-col gap-6">
        <div className="flex flex-col gap-1.5">
          <Skeleton className="h-4 w-24" />
          <Skeleton className="h-8 w-full rounded-md" />
        </div>
        <Skeleton className="h-20 w-full rounded-lg" />
        <Skeleton className="h-20 w-full rounded-lg" />
        <Skeleton className="h-24 w-full rounded-lg" />
        <Skeleton className="h-24 w-full rounded-lg" />
      </div>
      <Skeleton className="h-72 w-full rounded-lg" />
    </SkeletonGroup>
  )
}
