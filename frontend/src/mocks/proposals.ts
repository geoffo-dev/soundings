/**
 * Phase 4 proposals in the mock API (contract-phase4 §3.1–3.4): the fixed
 * template, per-section versions for optimistic concurrency, margin threads
 * and the exports. Records mirror the backend tables (`proposals`,
 * `proposal_sections`, `proposal_threads`, `proposal_comments`); the functions
 * here turn them into API shapes for a viewer and hold the permission rules
 * (role matrix section E). The backend is the authority.
 */
import type {
  IdeaStatus,
  ProposalComment,
  ProposalPermissions,
  ProposalSection,
  ProposalSectionKey,
  ProposalThread,
  ProposalView,
} from '@/api/types'

import type { MockDb, MockIdea, MockUser } from './db'
import {
  computeAggregate,
  effectiveRole,
  findUser,
  ideaKey,
  ideaRef,
  isPendingEvaluator,
  projectOf,
  statusLabel,
  userRefById,
} from './domain'

export interface MockProposal {
  id: string
  idea_id: string
  created_at: string
  created_by_id: string | null
  updated_at: string
}

export interface MockProposalSection {
  proposal_id: string
  key: ProposalSectionKey
  body_md: string
  version: number
  updated_at: string
  updated_by_id: string | null
}

export interface MockProposalThread {
  id: string
  proposal_id: string
  section_key: ProposalSectionKey
  created_at: string
  resolved_at: string | null
  resolved_by_id: string | null
}

export interface MockProposalComment {
  id: string
  thread_id: string
  author_id: string | null
  body_md: string
  created_at: string
  deleted_at: string | null
}

/** The fixed template (`app.schemas.proposals.PROPOSAL_TEMPLATE`, SPEC section 2). */
export const PROPOSAL_TEMPLATE: readonly {
  key: ProposalSectionKey
  title: string
  prompt: string
}[] = [
  {
    key: 'summary',
    title: 'Summary',
    prompt: 'The idea in a few sentences: what we would do and why it matters.',
  },
  { key: 'problem', title: 'Problem', prompt: 'Who has this problem, and how do we know?' },
  {
    key: 'solution',
    title: 'Solution',
    prompt: 'Describe what we would build or change, and how it solves the problem.',
  },
  {
    key: 'market',
    title: 'Market & users',
    prompt: 'Who would use or buy this, how many of them are there, and how do we reach them?',
  },
  {
    key: 'cost',
    title: 'Cost & effort',
    prompt: 'What would it take: people, time, money and dependencies?',
  },
  {
    key: 'benefits',
    title: 'Benefits / revenue',
    prompt: 'What do we gain: revenue, savings or other benefits, and how will we measure them?',
  },
  { key: 'risks', title: 'Risks', prompt: 'What could go wrong, and how would we reduce it?' },
  {
    key: 'next_steps',
    title: 'Next steps / the ask',
    prompt: 'What do you need, from whom, and by when?',
  },
]

export const SECTION_KEYS = PROPOSAL_TEMPLATE.map((section) => section.key)
export const SECTION_MAX_LENGTH = 20_000
export const COMMENT_MAX_LENGTH = 5_000
export const MAX_THREADS_PER_PROPOSAL = 500
export const MAX_COMMENTS_PER_THREAD = 200
/** Markdown and PDF together, per user per minute (contract-phase4 §3.4). */
export const EXPORTS_PER_MINUTE = 10

const EDITABLE: IdeaStatus[] = ['shortlisted', 'proposal']

export function proposalOf(db: MockDb, idea: MockIdea): MockProposal | undefined {
  return db.proposals.find((proposal) => proposal.idea_id === idea.id)
}

export function sectionsOf(db: MockDb, proposal: MockProposal): MockProposalSection[] {
  const sections = db.proposalSections.filter((section) => section.proposal_id === proposal.id)
  return SECTION_KEYS.flatMap((key) => sections.find((section) => section.key === key) ?? [])
}

/** Who may do what (role matrix E, contract-phase4 §3.1); held ideas are read-only (§3.6). */
export function proposalRules(db: MockDb, idea: MockIdea, user: MockUser) {
  const project = projectOf(db, idea)
  const role = effectiveRole(db, project.id, user.id)
  const memberish = role === 'member' || role === 'admin'
  const admin = user.is_platform_admin || role === 'admin'
  const owner = idea.owner_id === user.id && memberish
  const open = project.archived_at === null && idea.held_for !== 'moderation'
  return {
    admin,
    memberish,
    /** proposal.write without c7: the owner (while member or admin) and admins. */
    writer: owner || admin,
    /** c7: Shortlisted or Proposal. */
    c7: EDITABLE.includes(idea.status),
    open,
    commenter: admin || memberish,
  }
}

export function proposalPermissions(
  db: MockDb,
  idea: MockIdea,
  user: MockUser,
): ProposalPermissions {
  const rules = proposalRules(db, idea, user)
  const exists = Boolean(proposalOf(db, idea))
  const write = rules.writer && rules.c7 && rules.open
  return {
    can_create: write && !exists,
    can_edit: write && exists,
    can_comment: rules.commenter && rules.open && exists,
    can_export: exists,
  }
}

export function sectionOut(db: MockDb, section: MockProposalSection): ProposalSection {
  const template = PROPOSAL_TEMPLATE.find((t) => t.key === section.key)
  return {
    key: section.key,
    title: template?.title ?? section.key,
    prompt: template?.prompt ?? '',
    body_md: section.body_md,
    version: section.version,
    updated_at: section.updated_at,
    updated_by: userRefById(db, section.updated_by_id),
  }
}

export function proposalView(db: MockDb, idea: MockIdea, user: MockUser): ProposalView {
  const proposal = proposalOf(db, idea)
  return {
    proposal: proposal
      ? {
          id: proposal.id,
          idea: ideaRef(db, idea),
          sections: sectionsOf(db, proposal).map((section) => sectionOut(db, section)),
          created_at: proposal.created_at,
          created_by: userRefById(db, proposal.created_by_id),
          updated_at: proposal.updated_at,
        }
      : null,
    permissions: proposalPermissions(db, idea, user),
  }
}

export function commentsOf(db: MockDb, thread: MockProposalThread): MockProposalComment[] {
  return db.proposalComments
    .filter((comment) => comment.thread_id === thread.id)
    .sort((a, b) => a.created_at.localeCompare(b.created_at) || a.id.localeCompare(b.id))
}

/** Listed: at least one comment that isn't deleted (contract-phase4 §3.3). */
export function isListedThread(db: MockDb, thread: MockProposalThread): boolean {
  return commentsOf(db, thread).some((comment) => comment.deleted_at === null)
}

export function commentOut(
  db: MockDb,
  idea: MockIdea,
  comment: MockProposalComment,
  user: MockUser,
): ProposalComment {
  const rules = proposalRules(db, idea, user)
  const deleted = comment.deleted_at !== null
  const own = comment.author_id === user.id && rules.memberish
  return {
    id: comment.id,
    author: userRefById(db, comment.author_id),
    body_md: deleted ? '' : comment.body_md,
    created_at: comment.created_at,
    deleted,
    can_delete: !deleted && rules.open && (own || rules.admin),
  }
}

export function threadOut(
  db: MockDb,
  idea: MockIdea,
  thread: MockProposalThread,
  user: MockUser,
): ProposalThread {
  return {
    id: thread.id,
    section_key: thread.section_key,
    created_at: thread.created_at,
    resolved_at: thread.resolved_at,
    resolved_by: userRefById(db, thread.resolved_by_id),
    comments: commentsOf(db, thread).map((comment) => commentOut(db, idea, comment, user)),
  }
}

/** Every listed thread in template-section order, then oldest first. */
export function listedThreads(db: MockDb, proposal: MockProposal): MockProposalThread[] {
  return db.proposalThreads
    .filter((thread) => thread.proposal_id === proposal.id && isListedThread(db, thread))
    .sort(
      (a, b) =>
        SECTION_KEYS.indexOf(a.section_key) - SECTION_KEYS.indexOf(b.section_key) ||
        a.created_at.localeCompare(b.created_at) ||
        a.id.localeCompare(b.id),
    )
}

/** Deletes an idea's proposal with its sections, threads and comments (idea deleted). */
export function forgetProposal(db: MockDb, ideaId: string): void {
  const proposal = db.proposals.find((p) => p.idea_id === ideaId)
  if (!proposal) return
  const threads = new Set(
    db.proposalThreads.filter((t) => t.proposal_id === proposal.id).map((t) => t.id),
  )
  db.proposalComments = db.proposalComments.filter((c) => !threads.has(c.thread_id))
  db.proposalSuggestions = db.proposalSuggestions.filter((s) => s.proposal_id !== proposal.id)
  db.proposalThreads = db.proposalThreads.filter((t) => t.proposal_id !== proposal.id)
  db.proposalSections = db.proposalSections.filter((s) => s.proposal_id !== proposal.id)
  db.proposals = db.proposals.filter((p) => p !== proposal)
}

/* ------------------------------------------------------------------ */
/* Exports (contract-phase4 §3.4)                                      */
/* ------------------------------------------------------------------ */

/**
 * Headings inside a section go two levels down (`#` → `###`, never deeper
 * than `######`); fenced code is left alone. Setext headings become ATX ones.
 * (The backend does this with the parser's tokens; this is close enough.)
 */
export function demoteHeadings(markdown: string): string {
  const lines = markdown.split('\n')
  const out: string[] = []
  let fence: string | null = null
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i] ?? ''
    const fenceMatch = /^ {0,3}(`{3,}|~{3,})/.exec(line)
    if (fenceMatch) {
      const marker = fenceMatch[1] ?? ''
      if (fence === null) fence = marker
      else if (marker.startsWith(fence)) fence = null
      out.push(line)
      continue
    }
    if (fence !== null) {
      out.push(line)
      continue
    }
    const atx = /^ {0,3}(#{1,6})(\s.*|$)/.exec(line)
    if (atx) {
      const level = Math.min((atx[1] ?? '#').length + 2, 6)
      out.push(`${'#'.repeat(level)}${atx[2] ?? ''}`)
      continue
    }
    const next = lines[i + 1]
    if (line.trim() && next !== undefined && /^ {0,3}(=+|-+)\s*$/.test(next)) {
      const level = next.trim().startsWith('=') ? 3 : 4
      out.push(`${'#'.repeat(level)} ${line.trim()}`)
      i += 1
      continue
    }
    out.push(line)
  }
  return out.join('\n')
}

/** The export's text (both formats share it): title, metadata, the eight sections. */
export function exportMarkdown(db: MockDb, idea: MockIdea, user: MockUser): string {
  const proposal = proposalOf(db, idea)
  if (!proposal) return ''
  const project = projectOf(db, idea)
  const owner = findUser(db, idea.owner_id)
  const lines = [
    `# ${idea.title}`,
    '',
    `- Project: ${project.name}`,
    `- Idea: ${ideaKey(db, idea)}`,
    `- Status: ${statusLabel(project, idea)}`,
    `- Owner: ${owner?.display_name ?? 'No owner'}`,
    `- Exported ${new Date().toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' })} by ${user.display_name}`,
  ]
  // Only for people who may see scores (never a pending evaluator, role matrix §3).
  const aggregate = isPendingEvaluator(db, idea, user.id) ? null : computeAggregate(db, idea)
  if (aggregate) {
    lines.push(
      `- Aggregate score ${aggregate.overall.toFixed(1)} from ${aggregate.count} evaluation${aggregate.count === 1 ? '' : 's'}`,
    )
  }
  for (const section of sectionsOf(db, proposal)) {
    const title = PROPOSAL_TEMPLATE.find((t) => t.key === section.key)?.title ?? section.key
    lines.push('', `## ${title}`, '')
    lines.push(section.body_md.trim() ? demoteHeadings(section.body_md) : '_Not written yet._')
  }
  return `${lines.join('\n')}\n`
}

/** A tiny, valid one-page PDF that names the idea (the mock has no renderer). */
export function exportPdf(db: MockDb, idea: MockIdea): Uint8Array {
  const text = `${ideaKey(db, idea)} proposal (mock PDF)`.replace(/[()\\]/g, '')
  const content = `BT /F1 18 Tf 72 760 Td (${text}) Tj ET`
  const objects = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>',
    `<< /Length ${content.length} >>\nstream\n${content}\nendstream`,
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
  ]
  let body = '%PDF-1.4\n'
  const offsets: number[] = []
  objects.forEach((object, index) => {
    offsets.push(body.length)
    body += `${index + 1} 0 obj\n${object}\nendobj\n`
  })
  const xref = body.length
  body += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`
  for (const offset of offsets) body += `${String(offset).padStart(10, '0')} 00000 n \n`
  body += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`
  return new TextEncoder().encode(body)
}
