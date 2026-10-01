import { CircleCheck, LinkIcon, MailQuestion } from 'lucide-react'
import { useEffect, useRef } from 'react'

import { isApiError } from '@/api/errors'
import { useVerifySubmissionEmail } from '@/api/public'
import type { EmailVerified } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Callout } from '@/components/ui/callout'

import { useFragmentToken, VERIFICATION_TOKEN } from './fragment-token'
import { PublicCard, PublicLayout } from './public-layout'

/**
 * /verify#<token> (contract-phase4 §3.7): confirm a public submitter's email
 * address. Opening the page changes nothing: mail security scanners open links
 * (some run JavaScript), so the token is posted only when the person clicks
 * "Confirm my email address". Before that the page can't know the project, so
 * it shows the global branding and fixed text; afterwards the project's.
 */
export function VerifyPage() {
  const token = useFragmentToken(VERIFICATION_TOKEN)
  const verify = useVerifySubmissionEmail()

  if (verify.data) {
    return (
      <PublicLayout branding={verify.data.branding} width="narrow">
        <Confirmed result={verify.data} />
      </PublicLayout>
    )
  }

  const invalid =
    !token ||
    (verify.isError && isApiError(verify.error) && [404, 422].includes(verify.error.status))

  return (
    <PublicLayout branding={null} width="narrow">
      <PublicCard>
        {invalid ? (
          <div role={token ? 'alert' : undefined} className="flex flex-col gap-2">
            <StateIcon>
              <LinkIcon />
            </StateIcon>
            <h1 className="text-xl font-semibold text-primary">
              This link has expired or isn’t valid
            </h1>
            <p className="text-base text-secondary">
              Confirmation links work for 3 days. Open your private tracking link (it’s in the same
              email) to send a new one.
            </p>
          </div>
        ) : (
          <>
            <div className="flex flex-col gap-2">
              <StateIcon>
                <MailQuestion />
              </StateIcon>
              <h1 className="text-xl font-semibold text-primary">Confirm your email address</h1>
              <p className="text-base text-secondary">
                Someone sent an idea and gave this email address. If it was you, confirm it: the
                team gets your idea, and you get status emails if you asked for them.
              </p>
            </div>
            {verify.isError && (
              <Callout role="alert" tone="danger" title="That didn’t work">
                {isApiError(verify.error) && verify.error.status === 429
                  ? 'Too many requests just now. Wait a minute, then try again.'
                  : 'Nothing changed. Check your connection and try again.'}
              </Callout>
            )}
            <Button
              variant="primary"
              size="lg"
              className="w-full"
              loading={verify.isPending}
              onClick={() => verify.mutate(token)}
            >
              Confirm my email address
            </Button>
            <p className="text-sm text-muted">
              Wasn’t you? Close this page: nothing more is sent unless the address is confirmed.
            </p>
          </>
        )}
      </PublicCard>
    </PublicLayout>
  )
}

function StateIcon({ children }: { children: React.ReactNode }) {
  return (
    <span
      aria-hidden="true"
      className="flex size-10 items-center justify-center rounded-xl border bg-surface text-muted [&_svg]:size-5"
    >
      {children}
    </span>
  )
}

function Confirmed({ result }: { result: EmailVerified }) {
  const heading = useRef<HTMLHeadingElement>(null)
  useEffect(() => heading.current?.focus(), [])
  return (
    <PublicCard>
      <div className="flex flex-col items-center gap-3 text-center">
        <span
          aria-hidden="true"
          className="flex size-10 items-center justify-center rounded-full bg-success-subtle text-success"
        >
          <CircleCheck className="size-5" />
        </span>
        <h1
          ref={heading}
          tabIndex={-1}
          className="text-xl font-semibold text-primary focus:outline-none"
        >
          Thanks, your address is confirmed
        </h1>
        <p className="text-base break-words text-secondary">
          “{result.title}” for {result.project.name}
        </p>
      </div>
      <Callout
        tone="neutral"
        title={
          result.held_for === 'moderation'
            ? 'The team reviews new ideas first'
            : 'The team has your idea now'
        }
      >
        Your private tracking link is in the email we sent: it shows what happens next.
      </Callout>
    </PublicCard>
  )
}
