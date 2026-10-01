import type { GroupSyncMode, MappingEffect, MappingTestGroup, MappingTestResult } from '@/api/types'

/**
 * Group mapping helpers (contract-phase2 §3.5, §3.12): the one normalisation
 * rule for IdP values (as `app.schemas.groups.normalise_idp_value`) for the
 * live preview, and the wording of the "Test mapping" result. The server is the
 * authority: these only present what it says.
 */

/** Trim, strip `/` at both ends, trim again, lower-case: "/Innovation/Admins " → "innovation/admins". */
export function normaliseIdpValue(value: string): string {
  return value
    .trim()
    .replace(/^\/+|\/+$/g, '')
    .trim()
    .toLowerCase()
}

/** At most 50 values per group, each at most 255 characters once normalised. */
export const MAX_IDP_VALUES = 50
export const MAX_IDP_VALUE_LENGTH = 255

export const SYNC_MODES: { value: GroupSyncMode; label: string; description: string }[] = [
  {
    value: 'managed',
    label: 'Managed',
    description:
      'Sign-in adds and removes members to match the identity provider. People added by hand stay.',
  },
  {
    value: 'additive',
    label: 'Additive',
    description:
      'Sign-in only adds members. Removing someone takes an admin; they come back while the identity provider still lists them.',
  },
]

export function syncModeLabel(mode: GroupSyncMode): string {
  return SYNC_MODES.find((m) => m.value === mode)?.label ?? mode
}

export type SummaryTone = 'neutral' | 'info' | 'warning'

export interface MappingSummary {
  tone: SummaryTone
  title: string
  detail?: string
}

/** One line about the claim: off, missing, empty, or what was found. */
export function summariseMappingTest(result: MappingTestResult): MappingSummary {
  const claim = result.groups_claim
  if (claim === null) {
    return {
      tone: 'warning',
      title: 'Group sync is off',
      detail:
        'No groups claim is configured (oidc.groupsClaim), so signing in never changes group memberships.',
    }
  }
  const removals = result.groups.filter((g) => g.effect === 'remove').length
  if (!result.claim_found) {
    return {
      tone: 'warning',
      title: `No “${claim}” claim in these claims`,
      detail:
        removals > 0
          ? 'A missing claim counts as no groups: this person would leave every managed group they were synced into.'
          : 'A missing claim counts as no groups: nobody would join a group, and synced members of managed groups would leave.',
    }
  }
  const ignored =
    result.ignored_count > 0
      ? ` ${result.ignored_count === 1 ? '1 entry was' : `${result.ignored_count} entries were`} ignored (not text, or empty).`
      : ''
  if (result.values.length === 0) {
    return {
      tone: 'neutral',
      title: `The “${claim}” claim has no usable values`,
      detail: `Nobody would join a group.${ignored}`,
    }
  }
  const count = result.values.length
  return {
    tone: 'info',
    title: `Found ${count === 1 ? '1 value' : `${count} values`} in “${claim}”`,
    detail: ignored.trim() || undefined,
  }
}

export interface MappingRow {
  group: MappingTestGroup['group']
  syncMode: GroupSyncMode
  effect: MappingEffect
  /** "+", "−" or "=" (diff style; the label says the same in words). */
  symbol: string
  /** "Joins", "Leaves", "Stays". */
  label: string
  tone: 'success' | 'danger' | 'neutral'
  matchedValues: string[]
  /** Why, in a short sentence. */
  note: string
  /** The group the page is about (group detail). */
  highlighted: boolean
}

const EFFECT_ORDER: Record<MappingEffect, number> = { add: 0, remove: 1, keep: 2 }

function noteFor(group: MappingTestGroup): string {
  const values = group.matched_values.join(', ')
  switch (group.effect) {
    case 'add':
      return group.manual
        ? `Matches ${values}. Already added by hand; becomes synced too.`
        : `Matches ${values}.`
    case 'remove':
      return group.manual
        ? 'No longer matches. Stays a member: they were also added by hand.'
        : 'No longer matches, so they leave this managed group.'
    case 'keep':
      if (group.matched_values.length === 0) {
        return 'No longer matches, but additive groups never remove anyone at sign-in.'
      }
      return `Matches ${values}. Already a synced member.`
  }
}

/** The result's groups as diff rows: joins, then leaves, then stays; by name within each. */
export function mappingRows(result: MappingTestResult, highlightGroupId?: string): MappingRow[] {
  return [...result.groups]
    .sort(
      (a, b) =>
        EFFECT_ORDER[a.effect] - EFFECT_ORDER[b.effect] ||
        a.group.name.localeCompare(b.group.name, undefined, { sensitivity: 'base' }),
    )
    .map((group) => ({
      group: group.group,
      syncMode: group.sync_mode,
      effect: group.effect,
      symbol: group.effect === 'add' ? '+' : group.effect === 'remove' ? '−' : '=',
      label: group.effect === 'add' ? 'Joins' : group.effect === 'remove' ? 'Leaves' : 'Stays',
      tone: group.effect === 'add' ? 'success' : group.effect === 'remove' ? 'danger' : 'neutral',
      matchedValues: group.matched_values,
      note: noteFor(group),
      highlighted: group.group.id === highlightGroupId,
    }))
}

/** "Joins 2 groups, leaves 1" — for the result heading and screen readers. */
export function mappingHeadline(result: MappingTestResult, withUser: boolean): string {
  const joins = result.groups.filter((g) => g.effect === 'add').length
  const leaves = result.groups.filter((g) => g.effect === 'remove').length
  const stays = result.groups.filter((g) => g.effect === 'keep').length
  const groups = (n: number) => (n === 1 ? '1 group' : `${n} groups`)
  const parts: string[] = []
  if (joins) parts.push(`joins ${groups(joins)}`)
  if (leaves) parts.push(`leaves ${groups(leaves)}`)
  if (stays) parts.push(`stays in ${groups(stays)}`)
  const who = withUser ? 'This person' : 'Someone with these claims'
  if (parts.length === 0) return `${who} would join no groups`
  const sentence = parts.join(', ').replace(/, ([^,]*)$/, ' and $1')
  return `${who} ${sentence}`
}

/** For the group page: what the test means for this group, if it is in the result at all. */
export function effectForGroup(
  result: MappingTestResult,
  groupId: string,
): MappingEffect | undefined {
  return result.groups.find((g) => g.group.id === groupId)?.effect
}

/** Parses the pasted claims: a JSON object, or a message saying what is wrong. */
export function parseClaims(
  raw: string,
): { ok: true; claims: Record<string, unknown> } | { ok: false; message: string } {
  const trimmed = raw.trim()
  if (!trimmed) return { ok: false, message: 'Paste the claims of an ID token as JSON.' }
  let value: unknown
  try {
    value = JSON.parse(trimmed)
  } catch {
    if (/^[\w-]+\.[\w-]+\.[\w-]*$/.test(trimmed)) {
      return {
        ok: false,
        message: 'That looks like an encoded token. Paste its decoded claims (the JSON) instead.',
      }
    }
    return { ok: false, message: 'That isn’t valid JSON. Check for missing quotes or commas.' }
  }
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    return { ok: false, message: 'The claims must be a JSON object, like { "groups": [ … ] }.' }
  }
  return { ok: true, claims: value as Record<string, unknown> }
}
