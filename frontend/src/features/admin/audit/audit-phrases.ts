import type { ApiKeyScope, AuditAction, AuditEntry, ProjectRole } from '@/api/types'
import { purposeWords, SECTION_TITLES } from '@/features/ai/ai-copy'
import { SCOPE_COPY } from '@/features/api-keys/key-rules'
import {
  CLOSED_RESOLUTIONS,
  defaultStatusLabel,
  IDEA_STATUSES,
  type ClosedResolution,
  type IdeaStatus,
} from '@/lib/status'

export {
  actionsFor,
  AUDIT_CATEGORIES,
  AUDIT_CATEGORY_IDS,
  type AuditCategory,
} from './audit-categories'

/**
 * The audit log in plain language (contract-phase2 §3.11): every entry becomes
 * one sentence, e.g. "Alice Anders added Bob Brown to group Innovation members".
 *
 * Entries hold ids, enum values and field names. The API resolves the actor,
 * the target and the project to names; ids inside `details` (a group member, a
 * new owner, the groups a sync joined) are left as `user` / `group` parts for the
 * screen to resolve (`AuditSentence`), and `auditText()` words them for tests and
 * accessible names. Older or unknown shapes fall back to something true rather
 * than something wrong.
 */

export type AuditPart =
  | { type: 'text'; text: string }
  /** A name the API resolved (shown emphasised). */
  | { type: 'name'; text: string }
  /** An identifier read character by character (a key's prefix, a tool): monospace. */
  | { type: 'code'; text: string }
  /** A user id from `details`, resolved by the screen. */
  | { type: 'user'; id: string }
  /** A group id from `details`, resolved by the screen. */
  | { type: 'group'; id: string }
  /** An idea id from `details`, resolved to its key; `fallback` until then (or if gone). */
  | { type: 'idea'; id: string; fallback: string }
  /** An AI agent's id (`ai_agents.id`) from `details`: "AI agent Idea evaluator", else "an AI agent". */
  | { type: 'agent'; id: string }

const text = (value: string): AuditPart => ({ type: 'text', text: value })
const name = (value: string): AuditPart => ({ type: 'name', text: value })
const mono = (value: string): AuditPart => ({ type: 'code', text: value })

type Details = Record<string, unknown>

function str(details: Details, key: string): string | undefined {
  const value = details[key]
  return typeof value === 'string' && value ? value : undefined
}

function num(details: Details, key: string): number | undefined {
  const value = details[key]
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined
}

function list(details: Details, key: string): string[] {
  const value = details[key]
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === 'string')
    : []
}

function plural(count: number, one: string, many = `${one}s`): string {
  return `${count.toLocaleString('en')} ${count === 1 ? one : many}`
}

/** "a, b and c". */
function joinWords(words: string[]): string {
  if (words.length <= 1) return words.join('')
  return `${words.slice(0, -1).join(', ')} and ${words.at(-1) ?? ''}`
}

/** Parts joined with commas and a final "and" (for lists of user/group parts). */
function joinParts(parts: AuditPart[]): AuditPart[] {
  return parts.flatMap((part, index) => {
    if (index === 0) return [part]
    return [text(index === parts.length - 1 ? ' and ' : ', '), part]
  })
}

const ROLE_WORDS: Record<ProjectRole, string> = {
  admin: 'admin',
  member: 'member',
  viewer: 'viewer',
}

function role(value: unknown): string {
  return typeof value === 'string' && value in ROLE_WORDS
    ? ROLE_WORDS[value as ProjectRole]
    : 'unknown'
}

function statusLabel(status: unknown, resolution: unknown): string {
  if (typeof status !== 'string' || !IDEA_STATUSES.includes(status as IdeaStatus)) return 'unknown'
  const res =
    typeof resolution === 'string' && CLOSED_RESOLUTIONS.includes(resolution as ClosedResolution)
      ? (resolution as ClosedResolution)
      : null
  return defaultStatusLabel(status as IdeaStatus, res)
}

/** Why a sign-in was denied (contract-phase2 §3.3, §3.2, §3.8 reasons). */
export const DENIAL_REASONS: Record<string, string> = {
  account_disabled: 'the account is deactivated',
  already_linked: 'the account is already linked to another SSO account',
  external_id_mismatch: 'the external ID in the token doesn’t match',
  external_id_missing: 'the token has no external ID',
  email_taken: 'another account has that email',
  email_not_verified: 'the email isn’t verified',
  groups_overage: 'the token lists too many groups',
  no_match: 'no matching account',
  login_expired: 'the sign-in expired or was already used',
  login_cancelled: 'it was cancelled at the identity provider',
  sso_failed: 'the identity provider’s answer couldn’t be verified',
  invalid_credentials: 'wrong username or password',
  too_many_attempts: 'too many attempts',
}

const PROJECT_FIELDS: Record<string, string> = {
  name: 'name',
  description: 'description',
  visibility: 'visibility',
  volunteering_enabled: 'volunteering',
  allow_volunteering: 'volunteering',
  evaluation_window_days: 'evaluation window',
  status_labels: 'status labels',
  archived: 'archive state',
  // Phase 4 (contract-phase4 §3.14): project branding and the public form.
  branding: 'branding',
  public_submission_enabled: 'public form',
  public_require_email_verification: 'public form email confirmation',
  public_moderation_required: 'public form moderation',
  public_intro_md: 'public form intro',
}

/** Global branding fields (`branding.update` details.fields). */
const BRANDING_FIELDS: Record<string, string> = {
  app_name: 'app name',
  primary_color: 'primary colour',
  accent_color: 'accent colour',
  font: 'font',
  email_footer: 'email footer',
  logo_asset_id: 'logo',
  favicon_asset_id: 'favicon',
  logo: 'logo',
  favicon: 'favicon',
}

/** AI agent fields (`ai_agent.update` details.changed). */
const AGENT_FIELDS: Record<string, string> = {
  display_name: 'name',
  description: 'description',
  protocol: 'protocol',
  purposes: 'purposes',
  project_ids: 'projects',
  enabled: 'state',
}

function fieldWords(fields: string[], words: Record<string, string>): string {
  return joinWords(fields.map((field) => words[field] ?? field.replaceAll('_', ' ')))
}

/** A key by its public prefix (`sdg_` + lookup id), or "a key" for older entries. */
function keyPrefix(details: Details): AuditPart {
  const prefix = str(details, 'prefix')
  return prefix ? mono(prefix) : text('(prefix not recorded)')
}

const KEY_DATE = new Intl.DateTimeFormat('en-GB', {
  day: 'numeric',
  month: 'short',
  year: 'numeric',
})

/**
 * "Read, Evaluate and AI assistants (MCP); 1 project; expires 2 Jan 2027" for
 * `api_key.create`: the scopes as the key screens name them.
 */
function keyTerms(details: Details): string {
  const scopes = list(details, 'scopes').map((scope) =>
    scope in SCOPE_COPY ? SCOPE_COPY[scope as ApiKeyScope].label : scope,
  )
  const projects = list(details, 'project_ids')
  const expires = str(details, 'expires_at')
  const date = expires ? new Date(expires) : null
  return [
    scopes.length ? joinWords(scopes) : 'no scopes',
    details.restricted === true
      ? projects.length
        ? plural(projects.length, 'project')
        : 'restricted to projects'
      : 'all projects',
    date && !Number.isNaN(date.getTime()) ? `expires ${KEY_DATE.format(date)}` : 'never expires',
  ].join('; ')
}

const MATCHED_BY: Record<string, string> = {
  external_id: 'by external ID',
  email: 'by verified email',
}

/** Describes one entry as sentence parts. */
export function describeAuditEntry(entry: AuditEntry): AuditPart[] {
  const details: Details = entry.details
  const actor: AuditPart = entry.actor
    ? name(entry.actor.display_name)
    : text(entry.actor_id ? 'A deleted user' : 'Someone')
  const target = (fallback: string): AuditPart =>
    entry.target_label ? name(entry.target_label) : text(fallback)
  const targetUser = target('a deleted user')
  /** "group Viewers", or "a deleted group" (never "group a deleted group"). */
  const theGroup: AuditPart[] = entry.target_label
    ? [text('group '), name(entry.target_label)]
    : [text('a deleted group')]
  const project: AuditPart = entry.project ? name(entry.project.name) : text('a deleted project')
  /** A user named in `details` (or the target, when the entry is about a user). */
  const detailUser = (key: string): AuditPart => {
    const id = str(details, key)
    if (id) return { type: 'user', id }
    return entry.target_type === 'user' ? targetUser : text('someone')
  }
  const idea = (): AuditPart => {
    if (entry.target_type === 'idea' && entry.target_label) return name(entry.target_label)
    // A rejected public idea is deleted: the entry keeps its key (contract-phase4 §3.14).
    const key = str(details, 'key')
    if (key) return name(key)
    const number = num(details, 'number')
    if (entry.project && number !== undefined) return name(`${entry.project.key}-${number}`)
    const fallback = entry.project ? `an idea in ${entry.project.name}` : 'an idea'
    const id = str(details, 'idea_id')
    return id ? { type: 'idea', id, fallback } : text(fallback)
  }
  /** The person an evaluator entry is about: the target (API) or `evaluator_id`. */
  const evaluator = (): AuditPart =>
    entry.target_type === 'user' ? targetUser : detailUser('evaluator_id')
  const sameAsActor = (id: string | undefined) => Boolean(id && id === entry.actor_id)

  switch (entry.action as AuditAction) {
    /* Sign-in and sessions ----------------------------------------- */
    case 'session.sign_in': {
      const method = str(details, 'method') ?? str(details, 'auth_method')
      if (method === 'break_glass') return [actor, text(' signed in with the break-glass account')]
      if (method === 'dev_login') return [actor, text(' signed in with the development login')]
      const matched = str(details, 'matched_by')
      if (matched === 'created') return [actor, text(' signed in with SSO for the first time')]
      const how = matched ? MATCHED_BY[matched] : undefined
      return [actor, text(` signed in with SSO${how ? `, linked ${how}` : ''}`)]
    }
    case 'session.sign_in_denied': {
      const reasonKey = str(details, 'reason') ?? ''
      const reason =
        DENIAL_REASONS[reasonKey] ?? (reasonKey.replaceAll('_', ' ') || 'no reason given')
      if (str(details, 'method') === 'break_glass') {
        if (reasonKey === 'too_many_attempts') {
          return [text('Break-glass sign-ins were paused: too many attempts from one address')]
        }
        return [text(`A break-glass sign-in was denied: ${reason}`)]
      }
      if (entry.target_type === 'user' && entry.target_id) {
        return [text('SSO sign-in denied for '), targetUser, text(`: ${reason}`)]
      }
      return [text(`An SSO sign-in was denied: ${reason}`)]
    }
    case 'session.sign_out':
      return [actor, text(' signed out')]

    /* Users -------------------------------------------------------- */
    case 'user.create': {
      const source = str(details, 'source')
      if (source === 'break_glass')
        return [text('The break-glass account was created at its first sign-in')]
      if (source === 'sso') return [targetUser, text(' joined at their first SSO sign-in')]
      return [
        actor,
        text(' added '),
        targetUser,
        ...(details.is_platform_admin === true ? [text(' as a platform admin')] : []),
      ]
    }
    case 'user.update': {
      const clauses: AuditPart[][] = []
      if (details.is_active === false) {
        const ended = num(details, 'sessions_ended') ?? 0
        clauses.push([
          text('deactivated '),
          targetUser,
          ...(ended > 0 ? [text(` (${plural(ended, 'session')} ended)`)] : []),
        ])
      }
      if (details.is_active === true) clauses.push([text('reactivated '), targetUser])
      if (details.is_platform_admin === true)
        clauses.push([text('made '), targetUser, text(' a platform admin')])
      if (details.is_platform_admin === false)
        clauses.push([text('removed platform admin rights from '), targetUser])
      const other = list(details, 'fields').filter(
        (field) => field !== 'is_active' && field !== 'is_platform_admin',
      )
      if (other.length > 0) {
        const words = fieldWords(other, { display_name: 'name', email: 'email' })
        clauses.push([text(`changed the ${words} of `), targetUser])
      }
      if (clauses.length === 0) clauses.push([text('updated '), targetUser])
      return [
        actor,
        text(' '),
        ...clauses.flatMap((clause, i) => (i ? [text(' and '), ...clause] : clause)),
      ]
    }
    case 'user.external_ids_replace': {
      const kinds = list(details, 'kinds')
      if (kinds.length === 0) return [actor, text(' removed the external IDs of '), targetUser]
      return [actor, text(' set the external IDs of '), targetUser, text(` (${kinds.join(', ')})`)]
    }
    case 'user.identity_link': {
      const how = MATCHED_BY[str(details, 'matched_by') ?? '']
      return [text('The SSO account of '), targetUser, text(` was linked${how ? ` ${how}` : ''}`)]
    }
    case 'user.identity_unlink': {
      const ended = num(details, 'sessions_ended') ?? 0
      return [
        actor,
        text(' unlinked the SSO account of '),
        targetUser,
        ...(ended > 0 ? [text(` (${plural(ended, 'session')} ended)`)] : []),
      ]
    }
    case 'user.sessions_end': {
      const count = num(details, 'count')
      const suffix = count !== undefined ? ` (${plural(count, 'session')})` : ''
      if (entry.target_id && entry.target_id === entry.actor_id) {
        return [actor, text(` signed out everywhere${suffix}`)]
      }
      return [actor, text(' signed '), targetUser, text(` out everywhere${suffix}`)]
    }
    case 'user.groups_sync': {
      const added = list(details, 'added_group_ids').map((id): AuditPart => ({ type: 'group', id }))
      const removed = list(details, 'removed_group_ids').map((id): AuditPart => ({
        type: 'group',
        id,
      }))
      const changes: AuditPart[] = []
      // "Synced member", as the member lists badge it: an added group may already have
      // had this user as a manual member (only the synced flag changed), and a removed
      // one keeps them if they are also a manual member.
      if (added.length) changes.push(text('now a synced member of '), ...joinParts(added))
      if (removed.length) {
        changes.push(
          text(added.length ? '; no longer a synced member of ' : 'no longer a synced member of '),
          ...joinParts(removed),
        )
      }
      return [
        text('Sign-in sync for '),
        targetUser,
        text(changes.length ? ': ' : ': no changes'),
        ...changes,
        ...(details.claim_found === false ? [text(' (the token had no groups claim)')] : []),
      ]
    }

    /* Groups ------------------------------------------------------- */
    case 'group.create': {
      const values = list(details, 'idp_values')
      return [
        actor,
        text(' created '),
        ...theGroup,
        ...(values.length ? [text(`, mapped to ${values.join(', ')}`)] : []),
      ]
    }
    case 'group.update': {
      const fields = list(details, 'fields')
      if (fields.includes('name')) {
        return [
          actor,
          text(fields.includes('description') ? ' renamed and described ' : ' renamed '),
          ...theGroup,
        ]
      }
      return [actor, text(' changed the description of '), ...theGroup]
    }
    case 'group.delete': {
      const members = num(details, 'member_count')
      return [
        actor,
        text(' deleted '),
        ...(entry.target_label ? theGroup : [text('a group')]),
        ...(members !== undefined ? [text(` (${plural(members, 'member')})`)] : []),
      ]
    }
    case 'group.mapping_replace': {
      const from = str(details, 'from_sync_mode')
      const to = str(details, 'sync_mode')
      const before = list(details, 'from_idp_values')
      const after = list(details, 'idp_values')
      const changes: string[] = []
      if (to && from !== to) changes.push(`now ${to}`)
      if (before.join('\n') !== after.join('\n')) {
        changes.push(after.length ? `mapped to ${after.join(', ')}` : 'no longer mapped')
      }
      return [
        actor,
        text(' changed the mapping of '),
        ...theGroup,
        ...(changes.length ? [text(`: ${changes.join(', ')}`)] : []),
      ]
    }
    case 'group.member_add':
      return [actor, text(' added '), detailUser('user_id'), text(' to '), ...theGroup]
    case 'group.member_remove':
      return [actor, text(' removed '), detailUser('user_id'), text(' from '), ...theGroup]

    /* Projects ----------------------------------------------------- */
    case 'project.create':
      return [actor, text(' created project '), entry.target_label ? target('') : project]
    case 'project.update': {
      const fields = list(details, 'fields')
      if (fields.length === 1 && fields[0] === 'archived') {
        return [actor, text(' archived or restored '), project]
      }
      return [
        actor,
        text(` changed the ${fields.length ? fieldWords(fields, PROJECT_FIELDS) : 'settings'} of `),
        project,
      ]
    }
    case 'project.member_add':
      return [
        actor,
        text(' added '),
        detailUser('user_id'),
        text(' to '),
        project,
        text(` as ${role(details.role)}`),
      ]
    case 'project.member_update':
      return [
        actor,
        text(' changed the role of '),
        detailUser('user_id'),
        text(' in '),
        project,
        text(` from ${role(details.from_role)} to ${role(details.role)}`),
      ]
    case 'project.member_remove':
      return [actor, text(' removed '), detailUser('user_id'), text(' from '), project]
    case 'project.group_grant_add':
      return [
        actor,
        text(' gave '),
        ...theGroup,
        text(` the ${role(details.role)} role in `),
        project,
      ]
    case 'project.group_grant_update':
      return [
        actor,
        text(' changed the role of '),
        ...theGroup,
        text(' in '),
        project,
        text(` from ${role(details.from_role)} to ${role(details.role)}`),
      ]
    case 'project.group_grant_remove':
      return [
        actor,
        text(' removed '),
        ...theGroup,
        text(' from '),
        project,
        ...(details.from_role ? [text(` (was ${role(details.from_role)})`)] : []),
      ]
    case 'project.rubric_replace':
      return [actor, text(' changed the rubric of '), project]

    /* Ideas, assignments, evaluations ------------------------------ */
    case 'idea.delete':
      return [actor, text(' deleted '), idea()]
    case 'idea.owner_change': {
      const to = str(details, 'to_owner_id')
      if (!to) return [actor, text(' removed the owner of '), idea()]
      if (sameAsActor(to)) return [actor, text(' took on '), idea(), text(' as owner')]
      return [actor, text(' made '), { type: 'user', id: to }, text(' the owner of '), idea()]
    }
    case 'idea.status_change':
      return [
        actor,
        text(' moved '),
        idea(),
        text(
          ` from ${statusLabel(details.from_status, details.from_resolution)} to ${statusLabel(details.to_status, details.to_resolution)}`,
        ),
      ]
    case 'evaluator.add':
      return [actor, text(' asked '), evaluator(), text(' to evaluate '), idea()]
    case 'evaluator.remove':
      // Phase 6 (contract-phase6 §3.3): no actor when an AI run ended without its evaluation.
      if (!entry.actor_id && str(details, 'reason') === 'ai_run_ended') {
        return [
          evaluator(),
          text(' was taken off the evaluators of '),
          idea(),
          text(': its AI run ended without an evaluation'),
        ]
      }
      return [actor, text(' removed '), evaluator(), text(' as an evaluator of '), idea()]
    case 'evaluation.submit':
      return [actor, text(' submitted an evaluation of '), idea()]
    case 'evaluation.close':
      return [actor, text(' closed evaluation of '), idea()]
    case 'evaluation.reopen':
      return [actor, text(' reopened evaluation of '), idea()]

    /* Email (contract-phase3 §3.10): never an address -------------- */
    case 'email.test_send':
      return [
        actor,
        text(
          details.to_self === false
            ? ' sent a test email to another address'
            : ' sent a test email to themselves',
        ),
      ]
    case 'email.retry': {
      const count = num(details, 'count')
      if (count !== undefined) {
        return [actor, text(` retried ${plural(count, 'failed email')} (Retry all failed)`)]
      }
      return [actor, text(' retried a failed email')]
    }

    /* Public submissions and branding (contract-phase4 §3.14): never personal data */
    case 'submission.approve':
      return [actor, text(' approved '), idea(), text(' from the public form')]
    case 'submission.reject':
      return [actor, text(' rejected and deleted '), idea(), text(' from the public form')]
    case 'submission.erase': {
      if (entry.actor) return [actor, text(' erased the submitter’s details of '), idea()]
      if (str(details, 'reason') === 'retention') {
        return [
          text('The submitter’s details of '),
          idea(),
          text(' were erased automatically (closed for 180 days)'),
        ]
      }
      return [text('The submitter of '), idea(), text(' erased their details')]
    }
    case 'branding.update': {
      const fields = list(details, 'fields')
      return [
        actor,
        text(
          fields.length
            ? ` changed the ${fieldWords(fields, BRANDING_FIELDS)} of the branding`
            : ' changed the branding',
        ),
      ]
    }

    /* API keys and MCP (contract-phase5 §3.6): never a key, only its prefix */
    case 'api_key.create': {
      const forSomeoneElse =
        entry.target_type === 'user' && entry.target_id && entry.target_id !== entry.actor_id
      return [
        actor,
        text(' created API key '),
        keyPrefix(details),
        ...(forSomeoneElse ? [text(' for '), targetUser] : []),
        text(`: ${keyTerms(details)}`),
      ]
    }
    case 'api_key.revoke': {
      const ownKey = !entry.target_id || entry.target_id === entry.actor_id
      if (str(details, 'reason') === 'deactivated') {
        return [
          actor,
          text(' deactivated '),
          targetUser,
          text(', which revoked API key '),
          keyPrefix(details),
        ]
      }
      return [
        actor,
        text(' revoked API key '),
        keyPrefix(details),
        ...(ownKey ? [] : [text(' of '), targetUser]),
      ]
    }
    /* AI agents and runs (contract-phase6 §3.10): never prompts, agent text or keys */
    case 'ai_agent.register': {
      const namespace = str(details, 'namespace')
      const agentName = str(details, 'name')
      const purposes = purposeWords(list(details, 'purposes'))
      return [
        actor,
        text(' registered AI agent '),
        targetUser,
        ...(namespace && agentName
          ? [text(' ('), mono(`${namespace}/${agentName}`), text(')')]
          : []),
        ...(purposes ? [text(` for ${purposes}`)] : []),
      ]
    }
    case 'ai_agent.update': {
      const changed = list(details, 'changed')
      if (changed.includes('enabled') && details.enabled === false) {
        return [
          actor,
          text(' disabled AI agent '),
          targetUser,
          text(', which stopped its runs and revoked its key'),
        ]
      }
      if (changed.includes('enabled') && details.enabled === true) {
        return [actor, text(' enabled AI agent '), targetUser]
      }
      return [
        actor,
        text(
          changed.length
            ? ` changed the ${fieldWords(changed, AGENT_FIELDS)} of AI agent `
            : ' changed AI agent ',
        ),
        targetUser,
      ]
    }
    case 'ai_run.request': {
      const kind = str(details, 'kind')
      const section = str(details, 'section_key')
      const what =
        kind === 'evaluate'
          ? 'to evaluate '
          : kind === 'research'
            ? 'to research '
            : kind === 'draft_section'
              ? `to draft ${section && section in SECTION_TITLES ? SECTION_TITLES[section as keyof typeof SECTION_TITLES] : 'a section'} of `
              : 'to work on '
      const agentId = str(details, 'agent_id')
      return agentId
        ? [actor, text(' asked '), { type: 'agent', id: agentId }, text(` ${what}`), idea()]
        : [actor, text(` asked an AI agent ${what}`), idea()]
    }
    case 'ai_run.cancel':
      if (str(details, 'rule') === 'platform.manage_agents') {
        return [
          actor,
          text(' stopped an AI run on '),
          idea(),
          text(' by changing or disabling its agent'),
        ]
      }
      return [actor, text(' cancelled an AI run on '), idea()]
    case 'evaluation.include_ai':
      return details.include === false
        ? [
            actor,
            text(' left '),
            detailUser('evaluator_id'),
            text('’s evaluation of '),
            idea(),
            text(' out of the score'),
          ]
        : [
            actor,
            text(' counted '),
            detailUser('evaluator_id'),
            text('’s evaluation of '),
            idea(),
            text(' in the score'),
          ]
    case 'ai_note.delete': {
      // The note's text never reaches the audit log: name the agent when it still exists.
      const agentId = str(details, 'agent_id')
      return agentId
        ? [
            actor,
            text(' deleted a research note by '),
            { type: 'agent', id: agentId },
            text(' on '),
            idea(),
          ]
        : [actor, text(' deleted an AI research note on '), idea()]
    }

    case 'mcp.call': {
      const tool = str(details, 'tool')
      const code = str(details, 'code')
      const denied = str(details, 'decision') === 'deny'
      const outcome = code
        ? `: ${denied ? 'denied' : 'failed'} (${code.replaceAll('_', ' ')})`
        : denied
          ? ': denied'
          : ''
      const owner: AuditPart[] = entry.actor
        ? [name(`${entry.actor.display_name}’s`), text(' key')]
        : [text(entry.actor_id ? 'A deleted user’s key' : 'A key')]
      if (!tool) {
        // c15: refused at the door (the key has no `mcp` scope).
        return [
          ...owner,
          text(
            !code || code === 'insufficient_scope'
              ? ' was refused by the MCP server: it doesn’t allow AI assistants (MCP)'
              : ` was refused by the MCP server${outcome}`,
          ),
        ]
      }
      const on: AuditPart[] =
        entry.target_type === 'idea'
          ? [text(' on '), idea()]
          : entry.target_type === 'project'
            ? [text(' in '), project]
            : []
      return [
        ...owner,
        text(tool === 'unknown' ? ' called an unknown tool' : ' called '),
        ...(tool === 'unknown' ? [] : [mono(tool)]),
        ...on,
        text(outcome),
      ]
    }
  }
  // An action this screen doesn't know yet: say what is certain.
  return [
    actor,
    text(`: ${entry.action}`),
    ...(entry.target_label ? [text(' · '), name(entry.target_label)] : []),
  ]
}

export interface NameResolver {
  user: (id: string) => string | null | undefined
  group: (id: string) => string | null | undefined
  idea?: (id: string) => string | null | undefined
  agent?: (id: string) => string | null | undefined
}

const UNRESOLVED: NameResolver = { user: () => undefined, group: () => undefined }

/** The sentence as text: unresolved ids read "a user" / "a group" ("a deleted …" when gone). */
export function auditText(parts: AuditPart[], names: NameResolver = UNRESOLVED): string {
  return parts
    .map((part) => {
      if (part.type === 'text' || part.type === 'name' || part.type === 'code') return part.text
      if (part.type === 'idea') return names.idea?.(part.id) ?? part.fallback
      if (part.type === 'agent') {
        const agent = names.agent?.(part.id)
        return agent ? `AI agent ${agent}` : 'an AI agent'
      }
      const resolved = names[part.type](part.id)
      if (resolved) return resolved
      return resolved === null ? `a deleted ${part.type}` : `a ${part.type}`
    })
    .join('')
}

/** The action was taken in a break-glass session (contract-phase2 §3.8: every use audited). */
export function isBreakGlassEntry(entry: AuditEntry): boolean {
  return entry.details.auth_method === 'break_glass' || entry.details.method === 'break_glass'
}

/** The entry's raw fields for the detail view, in a stable order (details keys sorted). */
export function auditFields(entry: AuditEntry): { label: string; value: string }[] {
  const rows: { label: string; value: string }[] = [
    { label: 'action', value: entry.action },
    { label: 'created_at', value: entry.created_at },
    { label: 'actor_id', value: entry.actor_id ?? '—' },
  ]
  if (entry.target_type) {
    rows.push({ label: 'target', value: `${entry.target_type} ${entry.target_id ?? ''}`.trim() })
  }
  if (entry.project) rows.push({ label: 'project_id', value: entry.project.id })
  for (const key of Object.keys(entry.details).sort()) {
    const value = entry.details[key]
    rows.push({
      label: key,
      value:
        value === null || value === undefined
          ? '—'
          : typeof value === 'string'
            ? value
            : JSON.stringify(value),
    })
  }
  return rows
}
