import { Link } from '@tanstack/react-router'
import { KeyRound, Lock, LockOpen } from 'lucide-react'
import type { ReactNode } from 'react'

import { useSsoConfig } from '@/api/admin'
import type { SsoConfig, SsoDiscovery } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Callout } from '@/components/ui/callout'
import { EmptyState } from '@/components/ui/empty-state'
import { RelativeTime } from '@/components/ui/relative-time'
import { Skeleton, SkeletonGroup } from '@/components/ui/skeleton'

import { CopyButton } from '@/features/admin/copy-button'
import { AdminPageHeader, AdminSection } from '@/features/admin/settings-frame'

/**
 * Admin settings → Sign-in (SSO) (contract-phase2 §3.10): the effective
 * configuration, read-only (one provider per instance, set by Helm values):
 * whether the provider answers, the client, the redirect URIs to register per
 * address, how sign-in finds an account, group sync, and the break-glass
 * account. Secrets are never shown, only whether they are set.
 */
export function SsoPage() {
  const query = useSsoConfig()
  return (
    <>
      <AdminPageHeader
        title="Sign-in (SSO)"
        description={
          <>
            Set in the Helm values (<Code>oidc.*</Code>); read-only here.
          </>
        }
      />
      {query.data ? (
        <SsoDetails config={query.data} />
      ) : query.isError ? (
        <EmptyState
          role="alert"
          size="compact"
          className="rounded-lg border"
          icon={<KeyRound />}
          title="Couldn’t load the sign-in settings"
          description="Check your connection and try again."
          action={
            <Button variant="secondary" onClick={() => void query.refetch()}>
              Try again
            </Button>
          }
        />
      ) : (
        <SkeletonGroup label="Loading sign-in settings" className="flex flex-col gap-8">
          <Skeleton className="h-16 w-full" />
          {[0, 1, 2].map((i) => (
            <div key={i} className="flex flex-col gap-2.5">
              <Skeleton className="h-4 w-32" />
              <Skeleton className="h-4 w-full max-w-lg" />
              <Skeleton className="h-4 w-full max-w-md" />
            </div>
          ))}
        </SkeletonGroup>
      )}
    </>
  )
}

function Code({ children }: { children: ReactNode }) {
  return <code className="font-mono text-secondary">{children}</code>
}

function SsoDetails({ config }: { config: SsoConfig }) {
  return (
    <div className="flex flex-col gap-10">
      <div className="flex flex-col gap-3">
        <StatusCallout config={config} />
        {config.dev_login && (
          <Callout tone="warning" title="The development login is on">
            Anyone who can open the sign-in page can sign in as any user. Never turn it on in
            production.
          </Callout>
        )}
      </div>

      {!config.enabled && <SetupChecklist />}

      {config.enabled && (
        <AdminSection id="provider" title="Identity provider">
          <dl className="grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-[10rem_minmax(0,1fr)]">
            <Row label="Issuer">
              <Copyable value={config.issuer ?? ''} label="issuer" />
            </Row>
            <Row label="Client ID">
              <Copyable value={config.client_id} label="client ID" />
            </Row>
            <Row label="Client secret">
              {config.client_secret_set ? (
                <span className="inline-flex items-center gap-1.5 text-sm text-secondary">
                  <Lock aria-hidden="true" className="size-3.5 text-muted" />
                  Set (never shown)
                </span>
              ) : (
                <span className="inline-flex items-center gap-1.5 text-sm text-secondary">
                  <LockOpen aria-hidden="true" className="size-3.5 text-muted" />
                  Not set: a public client (PKCE only)
                </span>
              )}
            </Row>
            <Row label="Scopes">
              <span className="flex flex-wrap gap-1">
                {config.scopes.map((scope) => (
                  <code
                    key={scope}
                    className="rounded-sm bg-subtle px-1.5 font-mono text-xs leading-5 text-secondary"
                  >
                    {scope}
                  </code>
                ))}
              </span>
            </Row>
          </dl>
        </AdminSection>
      )}

      <AdminSection
        id="redirect-uris"
        title="Redirect URIs"
        description={
          <>
            Register both on the identity provider’s client, for every address people use (
            <Code>baseUrls</Code> in the Helm values).
          </>
        }
      >
        {config.redirect_uris.length === 0 ? (
          <p className="text-sm text-muted">
            No base URLs are configured (<Code>baseUrls</Code>).
          </p>
        ) : (
          <ul className="flex flex-col gap-3">
            {config.redirect_uris.map((uri) => (
              <li key={uri.base_url} className="flex flex-col gap-2 rounded-lg border px-4 py-3">
                <span className="text-sm font-medium text-primary">{uri.base_url}</span>
                <dl className="grid grid-cols-1 gap-x-6 gap-y-2 sm:grid-cols-[10rem_minmax(0,1fr)]">
                  <Row label="Redirect URI">
                    <Copyable value={uri.redirect_uri} label={`redirect URI for ${uri.base_url}`} />
                  </Row>
                  <Row label="After sign-out">
                    <Copyable
                      value={uri.post_logout_redirect_uri}
                      label={`post-logout redirect URI for ${uri.base_url}`}
                    />
                  </Row>
                </dl>
              </li>
            ))}
          </ul>
        )}
      </AdminSection>

      {config.enabled && <SignInRules config={config} />}

      <AdminSection
        id="break-glass"
        title="Break-glass account"
        description="An emergency platform admin whose credentials come from the deployment (a Kubernetes Secret with the Helm chart). Every use is in the audit log."
      >
        <BreakGlass config={config} />
      </AdminSection>
    </div>
  )
}

/** How sign-in finds the account and syncs groups: only meaningful once SSO is configured. */
function SignInRules({ config }: { config: SsoConfig }) {
  return (
    <>
      <AdminSection
        id="matching"
        title="Finding the account"
        description="At each SSO sign-in, Soundings looks for the person’s account in this order. The first step that finds someone decides."
      >
        <ol className="flex flex-col divide-y divide-subtle rounded-lg border">
          <Step n={1} title="Linked SSO account" on>
            The identity provider’s issuer and subject (<Code>sub</Code>), linked at an earlier
            sign-in.
          </Step>
          <Step n={2} title="External ID" on={Boolean(config.external_id_claim)}>
            {config.external_id_claim ? (
              <>
                The <Code>{config.external_id_claim}</Code> claim, matched against each user’s{' '}
                <Code>{config.external_id_kind ?? config.external_id_claim}</Code> ID. People with
                an ID of that kind are linked only this way, never by email.
              </>
            ) : (
              <>
                Off (<Code>oidc.externalIdClaim</Code>). Turn it on to link pre-created people by an
                ID the identity provider manages, such as an employee number.
              </>
            )}
          </Step>
          {config.external_id_claim && (
            <li className="px-4 py-3">
              <Callout tone="neutral" title="Only an attribute your identity provider’s admins set">
                Whoever can choose the value of <Code>{config.external_id_claim}</Code> can sign in
                as the pre-created user who has it, platform admins included. In Keycloak, make the
                attribute admin-editable only and keep unmanaged attributes off; in Entra ID use{' '}
                <Code>oid</Code> or <Code>employeeid</Code>.
              </Callout>
            </li>
          )}
          <Step n={3} title="Verified email" on={config.match_verified_email}>
            {config.match_verified_email
              ? 'The email, when the identity provider marks it verified (email_verified). Keep this on only for a provider that verifies addresses.'
              : 'Off (oidc.matchVerifiedEmail): accounts are never linked by email.'}
          </Step>
          <Step n={4} title="Create an account" on={config.auto_create_users}>
            {config.auto_create_users
              ? 'Anyone else with a verified email gets a new account with no roles; access then comes from groups.'
              : 'Off (oidc.autoCreateUsers): add people in Users before they sign in.'}
          </Step>
          <Step n={5} title="Otherwise" on={null}>
            Sign-in is refused, and the attempt is in the audit log.
          </Step>
        </ol>
      </AdminSection>

      <AdminSection
        id="group-sync"
        title="Group sync"
        description="At each sign-in, mapped groups follow the identity provider’s groups claim (Settings → Groups)."
      >
        <dl className="grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-[10rem_minmax(0,1fr)]">
          <Row label="Groups claim">
            {config.groups_claim ? (
              <Copyable value={config.groups_claim} label="groups claim" />
            ) : (
              <span className="text-sm text-secondary">
                Off (<Code>oidc.groupsClaim</Code>): sign-in never changes group memberships.
              </span>
            )}
          </Row>
        </dl>
      </AdminSection>
    </>
  )
}

/** With no identity provider yet: what to do, in order (README "Single sign-on" has the details). */
function SetupChecklist() {
  return (
    <AdminSection
      id="setup"
      title="Set up single sign-on"
      description="Three steps. Until the last one, platform admins sign in with the break-glass account."
    >
      <ol className="flex flex-col divide-y divide-subtle rounded-lg border">
        <Step n={1} title="Register Soundings with your identity provider" on={null}>
          Create an OpenID Connect client (authorization code flow with PKCE) and add the redirect
          URIs below for every address people use.
        </Step>
        <Step n={2} title="Prepare access" on={null}>
          Add people in{' '}
          <Link to="/settings/users" className="text-accent underline underline-offset-4">
            Users
          </Link>{' '}
          and map{' '}
          <Link to="/settings/groups" className="text-accent underline underline-offset-4">
            Groups
          </Link>{' '}
          to your identity provider’s groups, so everyone gets the right projects at their first
          sign-in.
        </Step>
        <Step n={3} title="Set the Helm values and upgrade" on={null}>
          <Code>oidc.issuer</Code>, <Code>oidc.clientId</Code> and the client secret (
          <Code>oidc.existingSecret</Code>), then <Code>helm upgrade</Code>. Break-glass sign-in
          turns off as soon as the issuer is set.
        </Step>
      </ol>
    </AdminSection>
  )
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <dt className="text-sm text-muted sm:leading-8">{label}</dt>
      <dd className="flex min-h-8 min-w-0 items-center">{children}</dd>
    </>
  )
}

function Copyable({ value, label }: { value: string; label: string }) {
  return (
    <span className="flex min-w-0 items-center gap-1">
      <code className="min-w-0 truncate font-mono text-sm text-primary" title={value}>
        {value}
      </code>
      <CopyButton value={value} label={label} />
    </span>
  )
}

function Step({
  n,
  title,
  on,
  children,
}: {
  n: number
  title: string
  /** null: not a setting (the last step). */
  on: boolean | null
  children: ReactNode
}) {
  return (
    <li className="flex items-start gap-3 px-4 py-3">
      <span
        aria-hidden="true"
        className="mt-px inline-flex size-5 shrink-0 items-center justify-center rounded-full bg-subtle text-xs font-medium text-secondary tabular-nums"
      >
        {n}
      </span>
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <span className="flex flex-wrap items-center gap-2 text-sm font-medium text-primary">
          <span>
            <span className="sr-only">Step {n}: </span>
            {title}
          </span>
          {on !== null &&
            (on ? <Badge variant="success">On</Badge> : <Badge variant="outline">Off</Badge>)}
        </span>
        <p className="text-sm text-muted">{children}</p>
      </div>
    </li>
  )
}

const DISCOVERY: Record<
  Exclude<SsoDiscovery['status'], 'ok'>,
  { title: string; body: ReactNode }
> = {
  unreachable: {
    title: 'Soundings can’t reach the identity provider',
    body: (
      <>
        People see “Single sign-on isn’t available right now”. Check that <Code>oidc.issuer</Code>{' '}
        is right and that the cluster can reach it (network policy, proxy, DNS).
      </>
    ),
  },
  invalid: {
    title: 'The identity provider’s discovery document is incomplete',
    body: (
      <>
        Its <Code>/.well-known/openid-configuration</Code> must be JSON with the authorization,
        token and keys (JWKS) endpoints. People can’t sign in until it is.
      </>
    ),
  },
  issuer_mismatch: {
    title: 'The issuer doesn’t match',
    body: (
      <>
        The provider names itself differently from <Code>oidc.issuer</Code> (often a trailing
        slash). They must be identical; people can’t sign in until they are.
      </>
    ),
  },
}

function StatusCallout({ config }: { config: SsoConfig }) {
  if (!config.enabled) {
    return (
      <Callout tone="warning" title="Single sign-on isn’t configured">
        {config.break_glass.available
          ? 'Nobody can sign in with your organisation’s accounts yet: only the break-glass account works.'
          : 'Nobody can sign in with your organisation’s accounts yet.'}
      </Callout>
    )
  }
  const discovery = config.discovery
  if (discovery && discovery.status !== 'ok') {
    const problem = DISCOVERY[discovery.status]
    return (
      <Callout tone="danger" title={problem.title} role="status">
        {problem.body}{' '}
        <span className="text-muted">
          Checked <RelativeTime date={discovery.checked_at} />.
        </span>
      </Callout>
    )
  }
  return (
    <Callout tone="success" title="Single sign-on is on">
      The identity provider answered
      {discovery ? (
        <>
          {' '}
          (checked <RelativeTime date={discovery.checked_at} />)
        </>
      ) : null}
      .{' '}
      {discovery?.end_session_supported
        ? 'Signing out of Soundings also signs out of the identity provider.'
        : 'Signing out ends the Soundings session only: the provider has no sign-out endpoint.'}
    </Callout>
  )
}

function BreakGlass({ config }: { config: SsoConfig }) {
  const { enabled, credentials_set: credentials, available } = config.break_glass
  if (available) {
    return (
      <Callout tone="neutral" title="Available" icon={<KeyRound />}>
        Single sign-on isn’t configured, so the break-glass account can sign in. It turns off as
        soon as <Code>oidc.issuer</Code> is set.
      </Callout>
    )
  }
  if (enabled && credentials && config.enabled) {
    return (
      <Callout tone="neutral" title="Off while single sign-on is configured" icon={<KeyRound />}>
        For an identity provider outage, unset <Code>oidc.issuer</Code> (<Code>helm upgrade</Code>)
        to bring it back. That needs cluster access, on purpose.
      </Callout>
    )
  }
  if (enabled && !credentials) {
    return (
      <Callout tone="neutral" title="Enabled, but without credentials" icon={<KeyRound />}>
        Its username or password isn’t set in the Secret (<Code>breakGlass.existingSecret</Code>),
        so it can’t sign in.
      </Callout>
    )
  }
  return (
    <Callout tone="neutral" title="Turned off" icon={<KeyRound />}>
      <Code>breakGlass.enabled</Code> is false.
    </Callout>
  )
}
