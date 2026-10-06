import type {
  AiAgentProtocol,
  AiBlockedReason,
  AiRun,
  AiRunError,
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

/**
 * "4 min left", "under a minute left", or null once it passed. Rounded, never up:
 * a one-minute limit never reads "2 min left".
 */
export function timeLeft(deadline: string | null, now: number): string | null {
  if (!deadline) return null
  const ms = Date.parse(deadline) - now
  if (Number.isNaN(ms) || ms <= 0) return null
  return ms < 60_000 ? 'under a minute left' : `${Math.round(ms / 60_000)} min left`
}

/**
 * A timed-out run's limit in words ("5 minutes", "45 seconds"): from its start to its
 * deadline while that is known, else to when it ended (the deadline plus the few
 * seconds cancelling took: whole minutes, rounded down).
 */
export function runLimitWords(
  run: Pick<AiRun, 'started_at' | 'deadline_at' | 'finished_at'>,
): string | null {
  const end = run.deadline_at ?? run.finished_at
  if (!run.started_at || !end) return null
  const seconds = (Date.parse(end) - Date.parse(run.started_at)) / 1000
  if (!Number.isFinite(seconds) || seconds <= 0) return null
  if (seconds < 60) return `${Math.round(seconds)} seconds`
  const minutes = run.deadline_at ? Math.round(seconds / 60) : Math.floor(seconds / 60)
  return minutes === 1 ? '1 minute' : `${minutes} minutes`
}

/**
 * Why a run stopped, and what to do about it, by its error code (contract-phase6
 * §3.4): Soundings' own words, never the agent's. The server's sentence for the
 * code stays in the run's steps; this is what the run's line says.
 */
const RUN_ERROR_COPY: Record<AiRunError, { what: string; next: string }> = {
  ai_disabled: {
    what: 'AI assistance was turned off before it started.',
    next: 'Ask a platform admin if you need it back.',
  },
  agent_unavailable: {
    what: 'This agent no longer works on this project.',
    next: 'Choose another agent, or ask a platform admin to check its projects.',
  },
  agent_unreachable: {
    what: 'Soundings couldn’t reach the agent.',
    next: 'Try again in a few minutes. If it keeps happening, ask a platform admin to test its connection.',
  },
  agent_protocol_error: {
    what: 'Soundings couldn’t understand the agent’s answer.',
    next: 'Ask a platform admin to check the agent’s protocol setting.',
  },
  agent_rejected: {
    what: 'The agent turned the request down.',
    next: 'Try again later. If it keeps refusing, ask a platform admin to check the agent.',
  },
  agent_failed: {
    what: 'The agent ran into an error and stopped.',
    next: 'Try again. If it keeps failing, ask a platform admin to check the agent.',
  },
  agent_needs_input: {
    what: 'The agent asked a question, and a run can’t answer one.',
    next: 'Try again. If it keeps asking, its instructions may need a change.',
  },
  no_result: {
    what: 'The agent finished without saving anything.',
    next: 'Try again.',
  },
  timed_out: {
    what: 'The agent didn’t finish in time.',
    next: 'Try again: it may have been busy.',
  },
  queue_timeout: {
    what: 'It waited too long for a free worker.',
    next: 'Try again in a few minutes.',
  },
  worker_lost: {
    what: 'The worker running it stopped before it finished.',
    next: 'Try again.',
  },
  internal_error: {
    what: 'Something went wrong on our side.',
    next: 'Try again. If it keeps happening, let an admin know.',
  },
}

/** A stopped run's reason and next step ("The agent didn’t finish within 5 minutes."). */
export function runErrorWords(
  run: Pick<AiRun, 'status' | 'error' | 'started_at' | 'deadline_at' | 'finished_at'>,
): { what: string; next: string } {
  const code = run.error?.code ?? (run.status === 'timed_out' ? 'timed_out' : 'internal_error')
  const copy = RUN_ERROR_COPY[code] as { what: string; next: string } | undefined
  if (!copy) {
    return { what: run.error?.message ?? 'It stopped with an error.', next: 'Try again.' }
  }
  if (code === 'timed_out') {
    const limit = runLimitWords(run)
    if (limit) return { ...copy, what: `The agent didn’t finish within ${limit}.` }
  }
  return copy
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
