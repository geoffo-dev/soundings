import { CircleAlert, RotateCcw } from 'lucide-react'
import { useState } from 'react'

import { useUpdateBranding, type BrandingScope } from '@/api/branding'
import type { BrandingSettings } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { RelativeTime } from '@/components/ui/relative-time'
import { Textarea } from '@/components/ui/textarea'
import { toast } from '@/components/ui/toaster'
import { FormActions } from '@/features/project/settings/settings-layout'
import { useShortcut } from '@/lib/shortcuts'

import {
  BRANDING_LIMITS,
  EMPTY_BRANDING_FORM,
  fromSettings,
  isEmptyProfile,
  previewBranding,
  sameProfile,
  saveErrors,
  toUpdate,
  validateBranding,
  type BrandingErrors,
  type BrandingForm,
} from './branding-form'
import { accentAdvice, primaryAdvice } from './contrast'
import { ColorField, FontField, ImageField } from './fields'
import { BrandingPreview } from './previews'

const FIELD_ORDER = ['app_name', 'primary_color', 'accent_color', 'email_footer'] as const

/**
 * One branding profile's form with a live preview (contract-phase4 §3.10):
 * the global branding (platform admins, /settings/branding) or a project's
 * override (project settings → Branding). Empty fields inherit; the preview
 * shows the result before Save. Images upload at once and go live with Save.
 */
export function BrandingSettingsForm({
  scope,
  settings,
  active = true,
  projectName,
  readOnly = false,
}: {
  scope: BrandingScope
  settings: BrandingSettings
  /** Bind ⌘S while this form is in view. */
  active?: boolean
  projectName: string
  readOnly?: boolean
}) {
  const global = scope.kind === 'global'
  const update = useUpdateBranding(scope)
  const [saved, setSaved] = useState(() => fromSettings(settings))
  const [form, setForm] = useState(saved)
  const [errors, setErrors] = useState<BrandingErrors>({})
  const [notice, setNotice] = useState<string | null>(null)
  const dirty = !sameProfile(form, saved)

  // Saved elsewhere (another tab, a refetch): follow the server unless there are edits here.
  const [seen, setSeen] = useState(settings)
  if (settings !== seen) {
    setSeen(settings)
    if (!dirty) {
      const fresh = fromSettings(settings)
      setSaved(fresh)
      setForm(fresh)
    }
  }

  const set = (patch: Partial<BrandingForm>) => {
    setForm((current) => ({ ...current, ...patch }))
    setNotice(null)
    const touched = new Set<string>(Object.keys(patch))
    if (errors.form || Object.keys(errors).some((key) => touched.has(key))) {
      setErrors((current) =>
        Object.fromEntries(
          Object.entries(current).filter(([key]) => key !== 'form' && !touched.has(key)),
        ),
      )
    }
  }

  const save = () => {
    if (update.isPending || readOnly) return
    if (!dirty) {
      setNotice('No changes to save.')
      return
    }
    const found = validateBranding(form)
    if (Object.keys(found).length > 0) {
      setErrors(found)
      const first = FIELD_ORDER.find((key) => found[key])
      if (first) document.getElementById(`branding-${first}`)?.focus()
      return
    }
    update.mutate(toUpdate(form), {
      onSuccess: (next) => {
        const fresh = fromSettings(next)
        setSaved(fresh)
        setForm(fresh)
        setErrors({})
        toast.success(global ? 'Branding saved' : 'Project branding saved', {
          description: global
            ? 'Everyone sees it the next time a page loads; you see it now.'
            : 'Its public form, emails to submitters and exported proposals use it now.',
        })
      },
      onError: (error) => setErrors(saveErrors(error)),
    })
  }

  useShortcut('saveSettings', save, { enabled: active && !readOnly })

  const inherited = settings.inherited
  const preview = previewBranding(form, inherited)
  const inheritedLabel = global ? 'Default' : 'From the global branding'
  const empty = isEmptyProfile(form)

  return (
    <div className="grid gap-x-10 gap-y-8 xl:grid-cols-[minmax(0,1fr)_24rem]">
      <form
        noValidate
        aria-label={global ? 'Branding' : 'Project branding'}
        className="flex max-w-2xl min-w-0 flex-col gap-6"
        onSubmit={(event) => {
          event.preventDefault()
          save()
        }}
      >
        {errors.form && (
          <p
            role="alert"
            className="flex items-start gap-2 rounded-md bg-danger-subtle px-3 py-2 text-sm text-danger"
          >
            <CircleAlert aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
            {errors.form}
          </p>
        )}
        <fieldset disabled={readOnly} className="flex min-w-0 flex-col gap-6">
          <legend className="sr-only">{global ? 'Branding' : 'Project branding'}</legend>
          <Field
            label="App name"
            id="branding-app_name"
            error={errors.app_name}
            description={
              global
                ? 'In the sidebar, the browser tab, emails and exported proposals.'
                : 'On this project’s public form, its emails to submitters and its exported proposals.'
            }
          >
            <Input
              value={form.app_name}
              placeholder={inherited.app_name}
              maxLength={BRANDING_LIMITS.appName + 10}
              autoComplete="off"
              onChange={(event) => set({ app_name: event.target.value })}
            />
          </Field>

          <div className="grid gap-6 md:grid-cols-2">
            <ImageField
              kind="logo"
              label="Logo"
              scope={scope}
              value={form.logo}
              inheritedUrl={inherited.logo?.url ?? null}
              emptyText="None: the app name is the wordmark."
              description="PNG or SVG, up to 512 KB. Emails never show images."
              error={errors.logo}
              disabled={readOnly}
              onChange={(logo) => set({ logo })}
            />
            <ImageField
              kind="favicon"
              label="Favicon"
              scope={scope}
              value={form.favicon}
              inheritedUrl={inherited.favicon?.url ?? null}
              emptyText="The Soundings icon."
              description={
                global
                  ? 'The browser tab icon. PNG up to 512 × 512, or SVG.'
                  : 'On this project’s public pages. PNG up to 512 × 512, or SVG.'
              }
              error={errors.favicon}
              disabled={readOnly}
              onChange={(favicon) => set({ favicon })}
            />
          </div>

          <ColorField
            id="branding-primary_color"
            label="Primary colour"
            description="Buttons, links, focus rings and selected items."
            value={form.primary_color}
            inherited={inherited.primary_color}
            inheritedLabel={inheritedLabel}
            error={errors.primary_color}
            advice={primaryAdvice}
            onChange={(primary_color) => set({ primary_color })}
          />
          <ColorField
            id="branding-accent_color"
            label="Accent colour"
            description="The logo mark (when there’s no logo) and small highlights."
            value={form.accent_color}
            inherited={inherited.accent_color}
            inheritedLabel={inheritedLabel}
            error={errors.accent_color}
            advice={accentAdvice}
            onChange={(accent_color) => set({ accent_color })}
          />

          <FontField
            value={form.font}
            inherited={inherited.font}
            onChange={(font) => set({ font })}
            description={
              global
                ? 'For the whole app, emails and exported proposals. Every font is bundled: nothing is downloaded from elsewhere.'
                : 'For the public form, emails to submitters and exported proposals.'
            }
          />

          <Field
            label="Email footer"
            id="branding-email_footer"
            error={errors.email_footer}
            description={
              inherited.email_footer && !global
                ? `Plain text under every email to submitters. Empty: “${inherited.email_footer.split('\n')[0] ?? ''}…” from the global branding.`
                : `Plain text under every email, such as your organisation’s name and address. Up to ${BRANDING_LIMITS.footerLines} lines.`
            }
          >
            <Textarea
              value={form.email_footer}
              placeholder={inherited.email_footer ?? ''}
              maxLength={BRANDING_LIMITS.footer}
              minRows={2}
              maxRows={6}
              onChange={(event) => set({ email_footer: event.target.value })}
            />
          </Field>
        </fieldset>

        {!readOnly && (
          <>
            <div className="flex flex-col gap-2 rounded-lg border px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex flex-col gap-0.5">
                <h3 className="text-sm font-medium text-primary">
                  {global ? 'Reset to the defaults' : 'Remove this project’s branding'}
                </h3>
                <p className="text-sm text-muted">
                  {global
                    ? 'Soundings’ own name, colours, font and icon. Takes effect when you save.'
                    : 'The project uses the global branding again. Takes effect when you save.'}
                </p>
              </div>
              <Button
                type="button"
                variant="outline"
                className="shrink-0"
                disabled={empty}
                onClick={() => {
                  set(EMPTY_BRANDING_FORM)
                  setNotice('Everything is back to the defaults. Save to apply.')
                }}
              >
                <RotateCcw aria-hidden="true" />
                {global ? 'Reset to defaults' : 'Use the global branding'}
              </Button>
            </div>
            <FormActions
              form={global ? 'the branding' : 'the project branding'}
              dirty={dirty}
              saving={update.isPending}
              notice={notice}
              saveLabel="Save branding"
              onDiscard={() => {
                setForm(saved)
                setErrors({})
                setNotice(null)
              }}
            />
          </>
        )}
        {settings.updated_at && (
          <p className="text-xs text-muted">
            Last changed {settings.updated_by ? `by ${settings.updated_by.display_name} ` : ''}
            <RelativeTime date={settings.updated_at} />
          </p>
        )}
      </form>
      <aside aria-label="Preview" className="min-w-0 xl:sticky xl:top-6 xl:self-start">
        <BrandingPreview
          branding={preview}
          surfaces={global ? ['app', 'public', 'email'] : ['public', 'email']}
          projectName={projectName}
        />
      </aside>
    </div>
  )
}
