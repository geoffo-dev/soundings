import { Link } from '@tanstack/react-router'
import { useId, useRef, useState } from 'react'

import { useSsoConfig, useTestGroupMapping } from '@/api/admin'
import { describeError, hasErrorCode } from '@/api/errors'
import type { MappingTestResult, UserSearchResult } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Callout } from '@/components/ui/callout'
import { Field } from '@/components/ui/field'
import { Textarea } from '@/components/ui/textarea'
import { PersonPicker } from '@/features/project/settings/person-picker'
import { describeSources, roleLabel } from '@/features/project/settings/access'
import { cn } from '@/lib/utils'

import {
  mappingHeadline,
  mappingRows,
  parseClaims,
  summariseMappingTest,
  syncModeLabel,
  type MappingRow,
} from './mapping'

/** Example claims using the configured claim path (nested paths become nested objects). */
function exampleClaims(claim: string | null): string {
  const groups = ['/innovation/members', '/tools/members']
  const path = claim ?? 'groups'
  const nested = path.split('.').reduceRight<unknown>((inner, key) => ({ [key]: inner }), groups)
  const body = {
    sub: 'f3c9a1e2-0000-4000-8000-000000000001',
    email: 'carol@example.com',
    email_verified: true,
    ...(path.includes('.') ? (nested as Record<string, unknown>) : { [path]: groups }),
  }
  return JSON.stringify(body, null, 2)
}

/** What's typed into the box: kept by the page, so closing the sheet doesn't lose it. */
export interface MappingTestDraft {
  claims: string
  person: UserSearchResult | null
}

export const EMPTY_MAPPING_TEST: MappingTestDraft = { claims: '', person: null }

/**
 * The "Test mapping" box (contract-phase2 §3.12): paste a claim set (a decoded
 * ID token), optionally pick a person, and see what signing in would do: the
 * values found, the groups they'd join, leave or stay in (diff-style), and the
 * project roles that result. Same code as sign-in on the server; nothing is
 * stored or logged. Shown in the "Test mapping" sheet (mapping-test-sheet.tsx).
 */
export function MappingTestPanel({
  draft,
  onDraftChange,
  highlightGroupId,
}: {
  draft: MappingTestDraft
  onDraftChange: (draft: MappingTestDraft) => void
  highlightGroupId?: string
}) {
  const id = useId()
  const sso = useSsoConfig()
  const test = useTestGroupMapping()
  const { claims, person } = draft
  const setClaims = (next: string) => onDraftChange({ ...draft, claims: next })
  const setPerson = (next: UserSearchResult | null) => onDraftChange({ ...draft, person: next })
  const claimsRef = useRef<HTMLTextAreaElement>(null)
  const [inputError, setInputError] = useState<string | null>(null)
  const [ran, setRan] = useState<{ claims: string; personId: string | null } | null>(null)
  const result = test.data
  const stale = ran !== null && (ran.claims !== claims || ran.personId !== (person?.id ?? null))

  const run = () => {
    const parsed = parseClaims(claims)
    if (!parsed.ok) {
      setInputError(parsed.message)
      // Straight to the field to fix (the message is its description).
      claimsRef.current?.focus()
      return
    }
    setInputError(null)
    test.mutate(
      { claims: parsed.claims, user_id: person?.id ?? null },
      { onSuccess: () => setRan({ claims, personId: person?.id ?? null }) },
    )
  }

  const apiError = test.error
    ? hasErrorCode(test.error, 'user_not_found')
      ? 'We couldn’t find that person. Pick someone else, or test without a person.'
      : describeError(test.error).title
    : null

  return (
    <div className="flex flex-col gap-5">
      <form
        noValidate
        className="flex flex-col gap-4"
        onSubmit={(event) => {
          event.preventDefault()
          run()
        }}
      >
        <Field
          label="Claims"
          description={
            <>
              Paste a decoded ID token as JSON (in Keycloak: Client scopes → Evaluate → Generated ID
              token). Nothing is stored or logged.{' '}
              <button
                type="button"
                className="text-accent underline-offset-4 hover:underline"
                onClick={() => {
                  setClaims(exampleClaims(sso.data?.groups_claim ?? null))
                  setInputError(null)
                }}
              >
                Insert an example
              </button>
            </>
          }
          error={inputError}
          id={`${id}-claims`}
        >
          <Textarea
            ref={claimsRef}
            value={claims}
            rows={7}
            spellCheck={false}
            autoCapitalize="none"
            placeholder="Paste the claims as JSON…"
            className="font-mono text-sm sm:text-sm"
            onChange={(event) => {
              setClaims(event.target.value)
              if (inputError) setInputError(null)
            }}
          />
        </Field>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
          <Field
            label="Person (optional)"
            description="Compare with their current groups and roles."
            className="min-w-0 flex-1"
          >
            <PersonPicker
              value={person}
              onChange={setPerson}
              placeholder="Anyone (no current groups)"
            />
          </Field>
          <div className="flex gap-2 sm:pb-6">
            {person && (
              <Button type="button" variant="ghost" onClick={() => setPerson(null)}>
                Clear person
              </Button>
            )}
            <Button type="submit" variant="primary" loading={test.isPending}>
              Test mapping
            </Button>
          </div>
        </div>
      </form>

      {apiError && <Callout role="alert" tone="danger" title={apiError} />}
      {result !== undefined && (
        <MappingResult
          result={result}
          withUser={ran?.personId != null}
          highlightGroupId={highlightGroupId}
          stale={stale}
        />
      )}
    </div>
  )
}

function MappingResult({
  result,
  withUser,
  highlightGroupId,
  stale,
}: {
  result: MappingTestResult
  withUser: boolean
  highlightGroupId?: string
  stale: boolean
}) {
  const summary = summariseMappingTest(result)
  const rows = mappingRows(result, highlightGroupId)
  const headline = mappingHeadline(result, withUser)

  return (
    <section
      aria-label="Test result"
      aria-live="polite"
      className={cn(
        'flex flex-col gap-4 rounded-lg border p-4 transition-opacity',
        stale && 'opacity-60',
      )}
    >
      <Callout
        tone={summary.tone === 'warning' ? 'warning' : summary.tone === 'info' ? 'info' : 'neutral'}
        title={summary.title}
      >
        {summary.detail}
        {stale && <span className="block">The claims changed: test again to update.</span>}
      </Callout>

      {result.values.length > 0 && (
        <div className="flex flex-col gap-1.5">
          <h4 className="text-xs font-medium text-muted">Values (normalised)</h4>
          <ul className="flex flex-wrap gap-1" aria-label="Values found">
            {result.values.map((value) => (
              <li
                key={value}
                className="inline-flex h-6 items-center rounded-sm bg-subtle px-1.5 font-mono text-sm text-secondary"
              >
                {value}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="flex flex-col gap-2">
        <h4 className="text-sm font-medium text-primary">{headline}</h4>
        {rows.length > 0 ? (
          <ul
            aria-label="Groups"
            className="divide-y divide-subtle overflow-hidden rounded-md border"
          >
            {rows.map((row) => (
              <MappingRowItem key={row.group.id} row={row} />
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted">
            No group is mapped to these values. Groups the claims don’t touch aren’t listed.
          </p>
        )}
      </div>

      {(withUser || result.project_roles.length > 0) && (
        <div className="flex flex-col gap-2">
          <h4 className="text-sm font-medium text-primary">Project roles after signing in</h4>
          {result.project_roles.length === 0 ? (
            <p className="text-sm text-muted">No project roles.</p>
          ) : (
            <ul className="flex flex-col gap-1.5" aria-label="Project roles after signing in">
              {result.project_roles.map((entry) => (
                <li
                  key={entry.project.id}
                  className="flex flex-wrap items-baseline gap-x-2 text-sm"
                >
                  <span className="font-medium text-primary">{entry.project.name}</span>
                  <Badge variant="outline">{roleLabel(entry.role)}</Badge>
                  <span className="text-muted">{describeSources(entry.sources, entry.role)}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  )
}

const ROW_TONE: Record<MappingRow['tone'], { symbol: string; label: string }> = {
  success: { symbol: 'bg-success-subtle text-success', label: 'text-success' },
  danger: { symbol: 'bg-danger-subtle text-danger', label: 'text-danger' },
  neutral: { symbol: 'bg-subtle text-muted', label: 'text-secondary' },
}

function MappingRowItem({ row }: { row: MappingRow }) {
  const tone = ROW_TONE[row.tone]
  return (
    <li className={cn('flex items-start gap-3 px-3 py-2.5', row.highlighted && 'bg-subtle')}>
      <span
        aria-hidden="true"
        className={cn(
          'mt-0.5 inline-flex size-5 shrink-0 items-center justify-center rounded-sm font-mono text-sm font-semibold',
          tone.symbol,
        )}
      >
        {row.symbol}
      </span>
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
          <span className={cn('font-medium', tone.label)}>{row.label}</span>
          <Link
            to="/settings/groups/$groupId"
            params={{ groupId: row.group.id }}
            className="font-medium text-primary hover:underline"
          >
            {row.group.name}
          </Link>
          <Badge variant="outline">{syncModeLabel(row.syncMode)}</Badge>
          {row.highlighted && <Badge variant="neutral">This group</Badge>}
        </div>
        <p className="text-sm text-muted">{row.note}</p>
      </div>
    </li>
  )
}
