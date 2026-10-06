import type {
  AiAgentProtocol,
  AiBlockedReason,
  AiRun,
  AiRunKind,
  AiRunStatus,
  ProposalSectionKey,
} from '@/api/types'

/*
 * Words for AI assistance (contract-phase6 §3.15), shared by the idea page, the
 * proposal editor, the admin page and the audit log. Everything an agent says
 * itself is data and never comes from here: these are Soundings' own words.
 */

/** What each kind of run does, as a menu item and as the run card's title. */
export const KIND_COPY: Record<
  AiRunKind,
  { action: string; doing: string; noun: string; purpose: string }
> = {
  evaluate: {
    action: 'Ask AI to evaluate',
    doing: 'Evaluating',
    noun: 'Evaluation',
    purpose: 'Evaluate ideas',
  },
  research: {
    action: 'Research this',
    doing: 'Researching',
    noun: 'Research',
    purpose: 'Research ideas',
  },
  draft_section: {
    action: 'Draft with AI',
    doing: 'Drafting',
    noun: 'Draft',
    purpose: 'Draft proposal sections',
  },
}

/** The run's state in a word, for its badge. */
export const STATUS_COPY: Record<
  AiRunStatus,
  { label: string; tone: 'neutral' | 'info' | 'success' | 'warning' | 'danger' }
> = {
  queued: { label: 'Waiting', tone: 'neutral' },
  running: { label: 'Working', tone: 'info' },
  succeeded: { label: 'Done', tone: 'success' },
  failed: { label: 'Failed', tone: 'danger' },
  cancelled: { label: 'Cancelled', tone: 'neutral' },
  timed_out: { label: 'Timed out', tone: 'warning' },
}

export function runStatusLabel(run: Pick<AiRun, 'status' | 'cancel_requested'>): string {
  if (run.cancel_requested && (run.status === 'queued' || run.status === 'running')) {
    return 'Cancelling'
  }
  return STATUS_COPY[run.status].label
}

export const isActiveRun = (run: Pick<AiRun, 'status'>) =>
  run.status === 'queued' || run.status === 'running'

/** Why an AI action is disabled, in plain words (`AiBlockedReason`). */
export const BLOCKED_COPY: Record<AiBlockedReason, string> = {
  not_allowed: 'Only the idea’s owner and admins can ask an AI agent',
  ai_off: 'AI assistance is off',
  project_archived: 'This project is archived',
  awaiting_moderation: 'Waiting for moderation',
  idea_closed: 'The idea is closed',
  evaluation_closed: 'Evaluation is closed',
  proposal_not_available:
    'The proposal can be drafted while the idea is Shortlisted or in Proposal',
  no_proposal: 'Start the proposal first',
  no_agent: 'No AI agent serves this project',
}

/** Template section titles (`PROPOSAL_TEMPLATE`), for text outside the editor. */
export const SECTION_TITLES: Record<ProposalSectionKey, string> = {
  summary: 'Summary',
  problem: 'Problem',
  solution: 'Solution',
  market: 'Market & users',
  cost: 'Cost & effort',
  benefits: 'Benefits / revenue',
  risks: 'Risks',
  next_steps: 'Next steps / the ask',
}

/** "Evaluating", "Drafting Risks" while active; "Evaluation", "Draft of Risks" once over. */
export function runTitle(run: Pick<AiRun, 'kind' | 'section_key' | 'status'>): string {
  const copy = KIND_COPY[run.kind]
  const active = run.status === 'queued' || run.status === 'running'
  const word = active ? copy.doing : copy.noun
  if (run.kind !== 'draft_section' || !run.section_key) return word
  return `${word}${active ? '' : ' of'} ${SECTION_TITLES[run.section_key]}`
}

export const PURPOSE_ORDER: readonly AiRunKind[] = ['evaluate', 'research', 'draft_section']

/** "evaluation and research" (an agent's purposes, in a sentence). */
export function purposeWords(purposes: readonly string[]): string {
  const words = PURPOSE_ORDER.filter((kind) => purposes.includes(kind)).map((kind) =>
    kind === 'evaluate' ? 'evaluation' : kind === 'research' ? 'research' : 'proposal drafts',
  )
  if (words.length <= 1) return words.join('')
  return `${words.slice(0, -1).join(', ')} and ${words.at(-1) ?? ''}`
}

export const PROTOCOL_COPY: Record<AiAgentProtocol, { label: string; detail: string }> = {
  kagent_v0_10: { label: 'kagent 0.10 (A2A 0.3)', detail: '/api/a2a/{namespace}/{name}/' },
  kagent_v1_0: { label: 'kagent 1.0 (A2A 1.0)', detail: '/agents/{namespace}/{name}' },
}

/** "4 min left", "under a minute left", or null once it passed. */
export function timeLeft(deadline: string | null, now: number): string | null {
  if (!deadline) return null
  const ms = Date.parse(deadline) - now
  if (Number.isNaN(ms) || ms <= 0) return null
  const minutes = Math.ceil(ms / 60_000)
  return ms < 60_000 ? 'under a minute left' : `${minutes} min left`
}

/** "0:42", "12:05", "1:02:09" since `from` (tabular, for the run card). */
export function elapsed(from: string | null, until: number): string {
  if (!from) return '0:00'
  const total = Math.max(0, Math.floor((until - Date.parse(from)) / 1000))
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const seconds = String(total % 60).padStart(2, '0')
  return hours > 0
    ? `${hours}:${String(minutes).padStart(2, '0')}:${seconds}`
    : `${minutes}:${seconds}`
}

/** "2 minutes 5 seconds" for screen readers. */
export function elapsedWords(from: string | null, until: number): string {
  if (!from) return 'just started'
  const total = Math.max(0, Math.floor((until - Date.parse(from)) / 1000))
  const minutes = Math.floor(total / 60)
  const seconds = total % 60
  const parts = []
  if (minutes > 0) parts.push(`${minutes} ${minutes === 1 ? 'minute' : 'minutes'}`)
  if (seconds > 0 || minutes === 0) parts.push(`${seconds} ${seconds === 1 ? 'second' : 'seconds'}`)
  return parts.join(' ')
}
