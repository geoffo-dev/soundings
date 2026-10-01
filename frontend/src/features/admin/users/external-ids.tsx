import { Plus, X } from 'lucide-react'
import { useId } from 'react'

import { isApiError } from '@/api/errors'
import type { ExternalId, ExternalIdIn } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'

/**
 * External IDs (contract-phase2 §3.4): `employee_no`, `gitlab`… one value per
 * kind, at most 20. Sign-in links a pre-created user when the configured claim
 * equals their ID of the configured kind (case-insensitively).
 */

export const KIND_PATTERN = /^[a-z][a-z0-9_]{0,39}$/
export const MAX_EXTERNAL_IDS = 20
const MAX_VALUE_LENGTH = 200

export interface ExternalIdRow {
  key: string
  kind: string
  value: string
}

export type RowErrors = Record<string, { kind?: string; value?: string }>

let nextKey = 0
export function newRow(kind = '', value = ''): ExternalIdRow {
  nextKey += 1
  return { key: `row-${nextKey}`, kind, value }
}

export function rowsFrom(ids: ExternalId[]): ExternalIdRow[] {
  return ids.map((id) => newRow(id.kind, id.value))
}

/** The rows with an ID (a row with only a kind, such as the suggested first row, is ignored). */
function filled(rows: ExternalIdRow[]): ExternalIdRow[] {
  return rows.filter((row) => row.value.trim())
}

/** Client-side checks, mirroring the API's: errors by row key, and the cleaned list. */
export function validateExternalIds(rows: ExternalIdRow[]): {
  errors: RowErrors
  ids: ExternalIdIn[]
} {
  const errors: RowErrors = {}
  const seen = new Set<string>()
  const used = filled(rows)
  for (const row of used) {
    const kind = row.kind.trim()
    const value = row.value.trim()
    const rowErrors: { kind?: string; value?: string } = {}
    if (!kind) rowErrors.kind = 'Enter a kind, e.g. employee_no'
    else if (!KIND_PATTERN.test(kind)) {
      rowErrors.kind = 'Lower-case letters, digits and _, starting with a letter'
    } else if (seen.has(kind)) rowErrors.kind = 'One ID per kind'
    if (value.length > MAX_VALUE_LENGTH) rowErrors.value = 'At most 200 characters'
    seen.add(kind)
    if (rowErrors.kind ?? rowErrors.value) errors[row.key] = rowErrors
  }
  return {
    errors,
    ids: used.map((row) => ({ kind: row.kind.trim(), value: row.value.trim() })),
  }
}

/** A 422's `external_ids[i].kind|value` errors, by row key (the i-th filled row). */
export function serverRowErrors(error: unknown, rows: ExternalIdRow[]): RowErrors {
  if (!isApiError(error)) return {}
  const used = filled(rows)
  const out: RowErrors = {}
  for (const entry of error.problem?.errors ?? []) {
    const [, field, index, part] = entry.loc
    if (field !== 'external_ids' || typeof index !== 'number') continue
    const row = used[index]
    if (!row) continue
    const key = part === 'value' ? 'value' : 'kind'
    out[row.key] = { ...out[row.key], [key]: entry.msg }
  }
  return out
}

/** True when the rows say the same as the saved IDs (order of kinds ignored). */
export function sameIds(rows: ExternalIdRow[], saved: ExternalId[]): boolean {
  const a = filled(rows)
    .map((row) => `${row.kind.trim()}=${row.value.trim()}`)
    .sort()
  const b = saved.map((id) => `${id.kind}=${id.value}`).sort()
  return a.join('\n') === b.join('\n')
}

/**
 * Rows of kind + value with remove buttons and "Add an external ID". Labels are
 * visible once (column headings) and repeated for screen readers per row.
 */
export function ExternalIdsEditor({
  rows,
  onChange,
  errors = {},
  kindPlaceholder = 'employee_no',
  disabled = false,
}: {
  rows: ExternalIdRow[]
  onChange: (rows: ExternalIdRow[]) => void
  errors?: RowErrors
  kindPlaceholder?: string
  disabled?: boolean
}) {
  const id = useId()
  const update = (key: string, patch: Partial<ExternalIdRow>) =>
    onChange(rows.map((row) => (row.key === key ? { ...row, ...patch } : row)))

  return (
    <div className="flex flex-col gap-2">
      {rows.length > 0 && (
        <div
          aria-hidden="true"
          className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_2rem] gap-2 text-xs font-medium text-muted"
        >
          <span>Kind</span>
          <span>ID</span>
        </div>
      )}
      <ul className="flex flex-col gap-2" aria-label="External IDs">
        {rows.map((row, index) => {
          const rowErrors = errors[row.key]
          const kindError = `${id}-${row.key}-kind-error`
          const valueError = `${id}-${row.key}-value-error`
          return (
            <li key={row.key} className="flex flex-col gap-1">
              <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_2rem] items-center gap-2">
                <Input
                  aria-label={`Kind of external ID ${index + 1}`}
                  value={row.kind}
                  placeholder={kindPlaceholder}
                  maxLength={40}
                  disabled={disabled}
                  autoCapitalize="none"
                  spellCheck={false}
                  aria-invalid={Boolean(rowErrors?.kind) || undefined}
                  aria-describedby={rowErrors?.kind ? kindError : undefined}
                  onChange={(event) => update(row.key, { kind: event.target.value })}
                />
                <Input
                  aria-label={`External ID ${index + 1}`}
                  value={row.value}
                  placeholder="E1042"
                  maxLength={MAX_VALUE_LENGTH}
                  disabled={disabled}
                  spellCheck={false}
                  aria-invalid={Boolean(rowErrors?.value) || undefined}
                  aria-describedby={rowErrors?.value ? valueError : undefined}
                  onChange={(event) => update(row.key, { value: event.target.value })}
                />
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-sm"
                  disabled={disabled}
                  aria-label={`Remove external ID ${index + 1}${row.kind ? ` (${row.kind})` : ''}`}
                  onClick={() => onChange(rows.filter((r) => r.key !== row.key))}
                >
                  <X />
                </Button>
              </div>
              {(rowErrors?.kind ?? rowErrors?.value) && (
                <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_2rem] gap-2 text-sm text-danger">
                  <span id={kindError}>{rowErrors.kind}</span>
                  <span id={valueError}>{rowErrors.value}</span>
                </div>
              )}
            </li>
          )
        })}
      </ul>
      <Button
        type="button"
        variant="ghost"
        size="sm"
        disabled={disabled || rows.length >= MAX_EXTERNAL_IDS}
        className={cn('self-start text-secondary', rows.length === 0 && '-ml-2.5')}
        onClick={() => onChange([...rows, newRow(rows.length === 0 ? kindPlaceholder : '')])}
      >
        <Plus />
        Add an external ID
      </Button>
    </div>
  )
}
