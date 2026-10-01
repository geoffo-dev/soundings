import { Link } from '@tanstack/react-router'
import { ArrowRight, CircleAlert, CloudOff, ExternalLink } from 'lucide-react'
import { useState } from 'react'

import { describeError, hasErrorCode } from '@/api/errors'
import { usePublicFormSettings, useUpdatePublicFormSettings } from '@/api/submissions'
import type { PublicFormSettings, PublicFormSettingsUpdate, Project } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Callout } from '@/components/ui/callout'
import { EmptyState } from '@/components/ui/empty-state'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Skeleton, SkeletonGroup } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { toast } from '@/components/ui/toaster'
import { CopyButton } from '@/features/admin/copy-button'
import { FormActions, SettingsSection } from '@/features/project/settings/settings-layout'
import { useShortcut } from '@/lib/shortcuts'

export const INTRO_MAX_LENGTH = 2_000

interface FormState {
  enabled: boolean
  moderation_required: boolean
  require_email_verification: boolean
  intro_md: string
}

const fromSettings = (settings: PublicFormSettings): FormState => ({
  enabled: settings.enabled,
  moderation_required: settings.moderation_required,
  require_email_verification: settings.require_email_verification,
  intro_md: settings.intro_md,
})

/** Only what changed (a PATCH), so a save never overwrites another admin's other edit. */
export function publicFormChanges(form: FormState, saved: FormState): PublicFormSettingsUpdate {
  const body: PublicFormSettingsUpdate = {}
  if (form.enabled !== saved.enabled) body.enabled = form.enabled
  if (form.moderation_required !== saved.moderation_required) {
    body.moderation_required = form.moderation_required
  }
  if (form.require_email_verification !== saved.require_email_verification) {
    body.require_email_verification = form.require_email_verification
  }
  if (form.intro_md.trim() !== saved.intro_md.trim()) body.intro_md = form.intro_md.trim()
  return body
}

/**
 * Project settings → Public form (contract-phase4 §2, §3.5–3.6; wireframe 07):
 * on or off, moderation, email confirmation, the intro text and the link to
 * share. Changes apply to new submissions only.
 */
export function PublicFormSettingsSection({
  project,
  active,
}: {
  project: Project
  active: boolean
}) {
  const settings = usePublicFormSettings(project.slug)
  return (
    <SettingsSection
      title="Public form"
      description="Let anyone send ideas to this project, without an account, through a page in the project’s branding. It shows only the project’s name and your intro."
    >
      {settings.data ? (
        <PublicFormForm project={project} settings={settings.data} active={active} />
      ) : settings.isError ? (
        <EmptyState
          role="alert"
          size="compact"
          headingLevel={3}
          icon={<CloudOff />}
          title="We couldn’t load the public form settings"
          description="Check your connection and try again."
          action={
            <Button variant="primary" onClick={() => void settings.refetch()}>
              Try again
            </Button>
          }
        />
      ) : (
        <SkeletonGroup
          label="Loading the public form settings"
          className="flex max-w-2xl flex-col gap-5"
        >
          {[0, 1, 2].map((i) => (
            <div key={i} className="flex items-start gap-3">
              <Skeleton className="h-5 w-9 rounded-full" />
              <div className="flex flex-1 flex-col gap-1.5">
                <Skeleton className="h-4 w-48" />
                <Skeleton className="h-3 w-full" />
              </div>
            </div>
          ))}
          <Skeleton className="h-24 w-full rounded-md" />
        </SkeletonGroup>
      )}
    </SettingsSection>
  )
}

function PublicFormForm({
  project,
  settings,
  active,
}: {
  project: Project
  settings: PublicFormSettings
  active: boolean
}) {
  const update = useUpdatePublicFormSettings(project.slug)
  const [saved, setSaved] = useState(() => fromSettings(settings))
  const [form, setForm] = useState(saved)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const body = publicFormChanges(form, saved)
  const dirty = Object.keys(body).length > 0
  const archived = Boolean(project.archived_at)
  const locked = archived || !settings.available

  const [seen, setSeen] = useState(settings)
  if (settings !== seen) {
    setSeen(settings)
    if (!dirty) {
      const fresh = fromSettings(settings)
      setSaved(fresh)
      setForm(fresh)
    }
  }

  const set = (patch: Partial<FormState>) => {
    setForm((current) => ({ ...current, ...patch }))
    setNotice(null)
    setError(null)
  }

  const save = () => {
    if (update.isPending) return
    if (!dirty) {
      setNotice('No changes to save.')
      return
    }
    if (form.intro_md.trim().length > INTRO_MAX_LENGTH) {
      setError(`The intro can be at most ${INTRO_MAX_LENGTH.toLocaleString('en')} characters.`)
      document.getElementById('public-form-intro')?.focus()
      return
    }
    update.mutate(body, {
      onSuccess: (next) => {
        const fresh = fromSettings(next)
        setSaved(fresh)
        setForm(fresh)
        toast.success(
          body.enabled === true
            ? 'The public form is on'
            : body.enabled === false
              ? 'The public form is off'
              : 'Public form saved',
          body.enabled === true ? { description: 'Share its link to start getting ideas.' } : {},
        )
      },
      onError: (failure) => {
        if (hasErrorCode(failure, 'smtp_not_configured')) {
          setError(
            'Email isn’t set up for this Soundings instance, so addresses can’t be confirmed.',
          )
        } else if (hasErrorCode(failure, 'public_submission_unavailable')) {
          setError('Public forms aren’t available for this project.')
        } else {
          const { title, description } = describeError(failure)
          setError(description ? `${title}. ${description}` : title)
        }
      },
    })
  }

  useShortcut('saveSettings', save, { enabled: active })

  return (
    <form
      noValidate
      aria-label="Public form"
      className="flex max-w-2xl flex-col gap-6"
      onSubmit={(event) => {
        event.preventDefault()
        save()
      }}
    >
      {!settings.available && (
        <Callout tone="warning" title="Public forms aren’t available for this project">
          {archived
            ? 'The project is archived.'
            : 'They are turned off for this Soundings instance (the Helm value features.publicSubmission), or the project’s address is one of the app’s own paths.'}
        </Callout>
      )}
      {error && (
        <p
          role="alert"
          className="flex items-start gap-2 rounded-md bg-danger-subtle px-3 py-2 text-sm text-danger"
        >
          <CircleAlert aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
          {error}
        </p>
      )}

      <Field
        inline
        label="Accept ideas through the public form"
        description="Anyone with the link can send an idea. Turning it off hides the form; tracking links keep working."
      >
        <Switch
          checked={form.enabled}
          disabled={locked && !form.enabled}
          onCheckedChange={(enabled) => set({ enabled })}
        />
      </Field>

      <div className="flex flex-col gap-1.5">
        <Field label="Link to share" id="public-form-url">
          <div className="flex items-center gap-1">
            <Input readOnly value={settings.form_url} className="font-mono text-sm" />
            <CopyButton value={settings.form_url} label="the form link" />
            {saved.enabled && settings.available && (
              <Button asChild variant="ghost" size="icon-sm" aria-label="Open the public form">
                <a href={`/${project.slug}/submit`} target="_blank" rel="noopener noreferrer">
                  <ExternalLink />
                </a>
              </Button>
            )}
          </div>
        </Field>
        <p className="text-sm text-muted">
          {saved.enabled
            ? 'The form is live at this address.'
            : 'The form is off: this link shows “This form isn’t available”.'}
        </p>
      </div>

      <Field
        inline
        label="Review new ideas before the team sees them"
        description="New ideas wait in a queue until an admin approves them (rejecting deletes the idea). Recommended."
      >
        <Switch
          checked={form.moderation_required}
          disabled={archived}
          onCheckedChange={(moderation_required) => set({ moderation_required })}
        />
      </Field>
      {settings.awaiting_moderation > 0 && (
        <Callout
          tone="info"
          title={`${settings.awaiting_moderation} ${settings.awaiting_moderation === 1 ? 'idea is' : 'ideas are'} waiting for review`}
          action={
            <Button asChild variant="link" size="sm">
              <Link to="/p/$slug/review" params={{ slug: project.slug }}>
                Review <ArrowRight aria-hidden="true" />
              </Link>
            </Button>
          }
        />
      )}

      <Field
        inline
        label="Ask people to confirm their email address"
        description={
          settings.email_available
            ? 'The email address becomes required, and an idea reaches the team only once its sender opens the link we email them (unconfirmed ideas are deleted after 3 days).'
            : 'Email isn’t set up for this Soundings instance, so the form can’t ask for an address.'
        }
      >
        <Switch
          checked={form.require_email_verification}
          disabled={archived || (!settings.email_available && !form.require_email_verification)}
          onCheckedChange={(require_email_verification) => set({ require_email_verification })}
        />
      </Field>

      <Field
        label="Intro"
        id="public-form-intro"
        description={
          form.intro_md.length >= INTRO_MAX_LENGTH * 0.8
            ? `${form.intro_md.length.toLocaleString('en')}/${INTRO_MAX_LENGTH.toLocaleString('en')} characters`
            : 'Shown above the form: what kind of ideas you’re after. Markdown works.'
        }
      >
        <Textarea
          value={form.intro_md}
          maxLength={INTRO_MAX_LENGTH}
          minRows={3}
          maxRows={10}
          disabled={archived}
          onChange={(event) => set({ intro_md: event.target.value })}
        />
      </Field>

      <p className="text-sm text-muted">Changes apply to ideas sent from now on.</p>

      <FormActions
        form="the public form"
        dirty={dirty}
        saving={update.isPending}
        notice={notice}
        onDiscard={() => {
          setForm(saved)
          setError(null)
          setNotice(null)
        }}
      />
    </form>
  )
}
