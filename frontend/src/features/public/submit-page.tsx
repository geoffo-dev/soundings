import { CloudOff, FileQuestion } from 'lucide-react'
import { useRef, useState } from 'react'

import { isApiError } from '@/api/errors'
import { usePublicProject, useSubmitPublicIdea } from '@/api/public'
import type { PublicProject, PublicSubmissionReceipt } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Callout } from '@/components/ui/callout'
import { Checkbox } from '@/components/ui/checkbox'
import { EmptyState } from '@/components/ui/empty-state'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Markdown } from '@/components/ui/markdown'
import { Skeleton, SkeletonGroup } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'
import { ariaKeys } from '@/components/ui/kbd'
import { focusWhenRendered } from '@/lib/focus'
import { SHORTCUTS, useShortcut } from '@/lib/shortcuts'

import { HumanCheck } from './human-check'
import { PublicCard, PublicLayout } from './public-layout'
import { SubmissionReceipt } from './receipt'
import {
  EMPTY_PUBLIC_FORM,
  nearLimit,
  PUBLIC_FIELDS,
  PUBLIC_LIMITS,
  submitProblem,
  toSubmission,
  validatePublicForm,
  type PublicErrors,
  type PublicForm,
  type SubmitProblem,
} from './submit-form'
import { useAltcha, type AltchaSolver } from './use-altcha'

/**
 * /{slug}/submit (SPEC §5 screen 6, §10; contract-phase4 §3.5; wireframe 06):
 * the project's public form, in its branding, without the app shell or
 * sign-in. Shows only the project's name and intro. A form that is off,
 * archived, unknown or reserved reads the same: "This form isn't available".
 */
export function PublicSubmitPage({ slug, solver }: { slug: string; solver?: AltchaSolver }) {
  const project = usePublicProject(slug)

  if (project.isError) {
    const missing = isApiError(project.error) && project.error.status === 404
    return (
      <PublicLayout branding={null} width="narrow">
        <PublicCard>
          {missing ? (
            <FormUnavailable />
          ) : (
            <EmptyState
              role="alert"
              size="compact"
              headingLevel={1}
              icon={<CloudOff />}
              title="We couldn’t load this form"
              description="Check your connection and try again."
              action={
                <Button variant="primary" onClick={() => void project.refetch()}>
                  Try again
                </Button>
              }
            />
          )}
        </PublicCard>
      </PublicLayout>
    )
  }
  if (!project.data) return <SubmitSkeleton />
  return <SubmitContent key={slug} project={project.data} solver={solver} />
}

function FormUnavailable() {
  return (
    <EmptyState
      size="compact"
      headingLevel={1}
      icon={<FileQuestion />}
      title="This form isn’t available"
      description="The link may be mistyped, or the form has been turned off."
    />
  )
}

function SubmitSkeleton() {
  return (
    <PublicLayout branding={undefined}>
      <SkeletonGroup label="Loading the form" className="flex flex-col gap-6">
        <div className="flex flex-col gap-2">
          <Skeleton className="h-7 w-3/4" />
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-2/3" />
        </div>
        <div className="flex flex-col gap-5 rounded-xl border bg-surface p-4 sm:p-6">
          {[0, 1, 2].map((i) => (
            <div key={i} className="flex flex-col gap-1.5">
              <Skeleton className="h-4 w-24" />
              <Skeleton className="h-11 w-full rounded-md sm:h-9" />
            </div>
          ))}
          <Skeleton className="h-11 w-full rounded-md" />
        </div>
      </SkeletonGroup>
    </PublicLayout>
  )
}

const PRIVACY_NOTICE_TEXT =
  'We keep what you write here, and your name and email address only if you give them. We don’t store your IP address. An email address you don’t confirm is forgotten after 3 days, and your name and address are erased 180 days after your idea is closed. To remove them sooner, use “Delete my details” on your tracking page, or ask the team. Your idea itself stays with the team.'

function SubmitContent({ project, solver }: { project: PublicProject; solver?: AltchaSolver }) {
  const submit = useSubmitPublicIdea(project.slug)
  const altcha = useAltcha(project.slug, solver)
  const [form, setForm] = useState<PublicForm>(EMPTY_PUBLIC_FORM)
  const [errors, setErrors] = useState<PublicErrors>({})
  const [problem, setProblem] = useState<SubmitProblem | null>(null)
  const [sending, setSending] = useState(false)
  const [receipt, setReceipt] = useState<PublicSubmissionReceipt | null>(null)
  const [sentTitle, setSentTitle] = useState('')
  const problemRef = useRef<HTMLDivElement>(null)

  const set = (patch: Partial<PublicForm>) => {
    altcha.start()
    setForm((current) => ({ ...current, ...patch }))
    const touched = new Set<string>(Object.keys(patch))
    if (touched.has('wantsUpdates')) touched.add('email')
    if (Object.keys(errors).some((key) => touched.has(key))) {
      setErrors((current) =>
        Object.fromEntries(Object.entries(current).filter(([key]) => !touched.has(key))),
      )
    }
  }

  // The problem shows by the Send button (where the visitor is) and takes focus, so it is read out.
  const showProblem = (found: SubmitProblem) => {
    setProblem(found)
    focusWhenRendered(() => problemRef.current, { force: true })
  }

  const focusFirst = (found: PublicErrors) => {
    const first = PUBLIC_FIELDS.find((field) => found[field])
    if (first) document.getElementById(`public-${first}`)?.focus()
  }

  const send = async () => {
    if (sending) return
    setProblem(null)
    const found = validatePublicForm(form, project)
    if (Object.keys(found).length > 0) {
      setErrors(found)
      focusFirst(found)
      return
    }
    setSending(true)
    try {
      // A challenge refused by the server is fetched and solved again once (§3.5).
      for (let attempt = 0; attempt < 2; attempt++) {
        const payload = await altcha.getPayload()
        if (!payload) {
          showProblem({ kind: 'challenge' })
          return
        }
        try {
          const result = await submit.mutateAsync(toSubmission(form, project, payload))
          altcha.cancel()
          setSentTitle(form.title.trim())
          setReceipt(result)
          return
        } catch (error) {
          altcha.discard()
          const found = submitProblem(error)
          if (found.kind === 'challenge' && attempt === 0) continue
          if (found.kind === 'fields') {
            setErrors(found.errors)
            focusFirst(found.errors)
          } else {
            showProblem(found)
          }
          return
        }
      }
    } finally {
      setSending(false)
    }
  }

  useShortcut('submitForm', () => void send())

  if (problem?.kind === 'unavailable') {
    return (
      <PublicLayout branding={project.branding} projectName={project.name} width="narrow">
        <PublicCard>
          <FormUnavailable />
        </PublicCard>
      </PublicLayout>
    )
  }

  if (receipt) {
    return (
      <PublicLayout branding={project.branding} projectName={project.name} width="narrow">
        <SubmissionReceipt
          receipt={receipt}
          title={sentTitle}
          projectName={project.name}
          onAnother={() => {
            setReceipt(null)
            setForm(EMPTY_PUBLIC_FORM)
            setErrors({})
          }}
        />
      </PublicLayout>
    )
  }

  const fieldClass = 'h-11 sm:h-9'

  return (
    <PublicLayout branding={project.branding} projectName={project.name} footer={<PrivacyNotice />}>
      <div className="flex flex-col gap-2 px-1">
        <h1 className="text-2xl font-semibold text-balance text-primary">
          Share an idea with {project.name}
        </h1>
        {project.intro_md && (
          <div className="text-base text-secondary">
            <Markdown>{project.intro_md}</Markdown>
          </div>
        )}
        <p className="text-sm text-muted">
          {project.moderated
            ? 'The team reviews new ideas first. You’ll get a private link to follow yours.'
            : 'You’ll get a private link to follow your idea.'}
        </p>
      </div>

      <PublicCard>
        <form
          noValidate
          aria-label="Your idea"
          className="flex flex-col gap-5"
          onSubmit={(event) => {
            event.preventDefault()
            void send()
          }}
          onFocus={() => altcha.start()}
        >
          <Field
            label="Title"
            required
            requiredMark={false}
            id="public-title"
            error={errors.title}
            description={
              nearLimit(form.title, PUBLIC_LIMITS.title) ?? 'A short name for your idea.'
            }
          >
            <Input
              value={form.title}
              maxLength={PUBLIC_LIMITS.title}
              autoComplete="off"
              enterKeyHint="next"
              className={fieldClass}
              onChange={(event) => set({ title: event.target.value.replace(/[\r\n]+/g, ' ') })}
            />
          </Field>
          <Field
            label="Summary"
            required
            requiredMark={false}
            id="public-summary"
            error={errors.summary}
            description={
              nearLimit(form.summary, PUBLIC_LIMITS.summary) ??
              'One or two sentences: what and why.'
            }
          >
            <Textarea
              value={form.summary}
              maxLength={PUBLIC_LIMITS.summary}
              minRows={2}
              maxRows={6}
              onChange={(event) => set({ summary: event.target.value })}
            />
          </Field>
          <Field
            label="Description (optional)"
            id="public-description"
            error={errors.description}
            description={
              nearLimit(form.description, PUBLIC_LIMITS.description) ??
              'Anything that helps: who it’s for, what would change. Markdown works.'
            }
          >
            <Textarea
              value={form.description}
              maxLength={PUBLIC_LIMITS.description}
              minRows={3}
              maxRows={12}
              onChange={(event) => set({ description: event.target.value })}
            />
          </Field>

          <fieldset className="flex flex-col gap-4 border-t border-subtle pt-5">
            <legend className="sr-only">About you</legend>
            <p className="text-sm text-muted">
              {project.asks_for_email
                ? 'The team sees your name with your idea. Your email address is only for contacting you: it isn’t shown with your idea.'
                : 'Optional. The team sees your name with your idea.'}
            </p>
            <Field
              label="Your name (optional)"
              id="public-name"
              error={errors.name}
              description={nearLimit(form.name, PUBLIC_LIMITS.name)}
            >
              <Input
                value={form.name}
                maxLength={PUBLIC_LIMITS.name}
                autoComplete="name"
                className={fieldClass}
                onChange={(event) => set({ name: event.target.value })}
              />
            </Field>
            {project.asks_for_email && (
              <>
                <Field
                  label={project.email_required ? 'Your email' : 'Your email (optional)'}
                  required={project.email_required}
                  requiredMark={false}
                  id="public-email"
                  error={errors.email}
                  description={
                    project.email_required
                      ? 'We email you a link to confirm your idea; it reaches the team once you do.'
                      : 'Only to email you about this idea.'
                  }
                >
                  <Input
                    type="email"
                    inputMode="email"
                    value={form.email}
                    maxLength={PUBLIC_LIMITS.email}
                    autoComplete="email"
                    spellCheck={false}
                    className={fieldClass}
                    onChange={(event) => set({ email: event.target.value })}
                  />
                </Field>
                <Field
                  inline
                  label="Email me when the status changes"
                  description="Only about this idea. Stop any time from your tracking page."
                >
                  <Checkbox
                    checked={form.wantsUpdates}
                    onCheckedChange={(checked) => set({ wantsUpdates: checked === true })}
                  />
                </Field>
              </>
            )}
          </fieldset>

          <Honeypot value={form.honeypot} onChange={(honeypot) => set({ honeypot })} />

          <HumanCheck state={altcha.state} onRetry={() => void altcha.retry()} />

          {problem && <ProblemCallout problem={problem} ref={problemRef} />}

          <Button
            type="submit"
            variant="primary"
            size="lg"
            loading={sending}
            className="h-11 w-full sm:h-10"
            aria-keyshortcuts={ariaKeys(SHORTCUTS.submitForm.keys)}
          >
            {/* ⌘Enter works, but a public page shows no shortcut hints: calm for first-time visitors. */}
            {sending ? 'Sending…' : 'Send idea'}
          </Button>
        </form>
      </PublicCard>
    </PublicLayout>
  )
}

/** The fixed privacy notice under the form (contract-phase4 §3.5; not configurable). */
function PrivacyNotice() {
  return (
    <section aria-labelledby="privacy-heading" className="flex flex-col gap-1">
      <h2 id="privacy-heading" className="font-medium text-secondary">
        Your privacy
      </h2>
      <p>{PRIVACY_NOTICE_TEXT}</p>
    </section>
  )
}

/**
 * The honeypot (contract-phase4 §3.5): off-screen (not `display: none`), hidden
 * from assistive technology and the tab order, with a name and label that
 * browsers and password managers don't autofill. Sent as `website`.
 */
function Honeypot({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  return (
    <div aria-hidden="true" className="sr-only">
      <label htmlFor="hp_ref">Leave this empty</label>
      <input
        id="hp_ref"
        name="hp_ref"
        type="text"
        tabIndex={-1}
        autoComplete="off"
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    </div>
  )
}

function ProblemCallout({
  problem,
  ref,
}: {
  problem: SubmitProblem
  ref: React.Ref<HTMLDivElement>
}) {
  const copy =
    problem.kind === 'rate_limited'
      ? {
          title: 'You’ve sent several ideas in a short time',
          text: 'Try again in a few minutes. Nothing you wrote is lost.',
        }
      : problem.kind === 'challenge'
        ? {
            title: 'Your idea wasn’t sent',
            text: 'We couldn’t verify this browser. Press Retry above, then send again. Nothing you wrote is lost.',
          }
        : problem.kind === 'network'
          ? {
              title: 'We couldn’t send your idea',
              text: 'Check your connection and try again. Nothing you wrote is lost.',
            }
          : {
              title: 'Something went wrong on our side',
              text: 'Try again in a moment. Nothing you wrote is lost.',
            }
  return (
    <div ref={ref} tabIndex={-1} className="focus:outline-none">
      <Callout
        role="alert"
        tone={problem.kind === 'rate_limited' ? 'warning' : 'danger'}
        title={copy.title}
      >
        {copy.text}
      </Callout>
    </div>
  )
}
