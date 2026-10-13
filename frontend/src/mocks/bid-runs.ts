/**
 * Phase 10: the AI assessor's runs in the mock (contract-phase10 §9). A run per bid,
 * asked for by a call manager ("Ask AI to assess", "Assess all with AI") or started
 * automatically by the call's AI assessor once a bid's documents are read. The
 * pretend worker (`ai.ts`) walks it through the real steps; what the fake agent
 * writes through MCP (`submit_bid_assessment`) is written here: a score with a
 * rationale and a quote for every score question, and a finding for every must-have
 * that isn't a pricing one. It never reads pricing documents or the price.
 *
 * Agent names ending in `-invents` quote a sentence that isn't in the document (the
 * server marks it "Not found in the document").
 */
import {
  addRunEvent,
  agentName,
  isActive,
  outcomeSetting,
  scheduleRun,
  type MockAiAgent,
  type MockAiRun,
} from './ai'
import {
  callOf,
  documentsOf,
  mustHavesOf,
  questionsOf,
  sectionsOf,
  type MockBid,
  type MockBidAiAssessment,
  type MockBidCall,
  type MockEvidence,
} from './bids'
import { ID_KIND, newId, type MockDb, type MockIdea, type MockUser } from './db'

const SCORES = [4, 3, 4, 3, 5, 2, 4]

/** A queued assess run for one bid (the caller checked the rules and the hourly limit). */
export function createAssessRun(
  db: MockDb,
  idea: MockIdea,
  call: MockBidCall,
  bid: MockBid,
  agent: MockAiAgent,
  requestedBy: MockUser | null,
): MockAiRun {
  const now = Date.now()
  const run: MockAiRun = {
    id: newId(db, ID_KIND.phase5),
    idea_id: idea.id,
    agent_id: agent.id,
    kind: 'assess_bid',
    section_key: null,
    bid_id: bid.id,
    bid_call_id: call.id,
    automatic: requestedBy === null,
    bid_ai_assessment_id: null,
    status: 'queued',
    requested_by_id: requestedBy?.id ?? null,
    created_at: new Date(now).toISOString(),
    started_at: null,
    finished_at: null,
    timeout_seconds: db.aiSettings.run_timeout_seconds,
    cancel_requested_at: null,
    cancel_requested_by_id: null,
    error_code: null,
    error_message: null,
    evaluation_id: null,
    suggestion_id: null,
    activity_event_id: null,
    assigned_evaluator: false,
    outcome: outcomeSetting(),
    step: 0,
  }
  db.aiRuns.push(run)
  addRunEvent(db, run, 'queued', requestedBy ? undefined : 'Started automatically')
  scheduleRun(db, run)
  return run
}

/** The active run of this agent for this bid, if any (`uq_ai_runs_active`). */
export function activeAssessRun(db: MockDb, bid: MockBid, agentId: string): MockAiRun | undefined {
  return db.aiRuns.find(
    (run) =>
      run.kind === 'assess_bid' &&
      run.bid_id === bid.id &&
      run.agent_id === agentId &&
      isActive(run.status),
  )
}

/** Cancels the active assess runs of these bids (rejection, template change, award…). */
export function cancelAssessRuns(db: MockDb, bidIds: readonly string[]): void {
  for (const run of db.aiRuns) {
    if (run.kind !== 'assess_bid' || !run.bid_id || !bidIds.includes(run.bid_id)) continue
    if (!isActive(run.status) || run.cancel_requested_at) continue
    run.cancel_requested_at = new Date().toISOString()
    addRunEvent(db, run, 'cancel_requested')
  }
}

/** A passage of at least 20 characters from the document's text (whitespace kept). */
function passage(text: string, from: number): string | null {
  const sentences = text
    .split(/(?<=[.!?])\s+/)
    .map((s) => s.trim())
    .filter((s) => s.replace(/\s+/g, ' ').length >= 24)
  if (!sentences.length) return null
  return (sentences[from % sentences.length] ?? '').slice(0, 300)
}

/** What the fake agent submits through MCP; an MCP error code when it can't. */
export function writeBidAssessment(
  db: MockDb,
  run: MockAiRun,
  idea: MockIdea,
  agent: MockAiAgent,
): string | null {
  const call = callOf(db, idea)
  const bid = db.bid.bids.find((b) => b.id === run.bid_id && b.call_id === call?.id)
  if (!call || !bid) return 'not_found'
  if (bid.rejected) return 'bid_rejected'
  if (call.status === 'awarded' || call.status === 'cancelled') return 'bid_call_finished'
  if (call.status !== 'open' && call.status !== 'assessing') return 'bid_call_not_assessable'
  // Never a pricing document (contract-phase10 §6.4), and only text that was read.
  const documents = documentsOf(db, bid).filter(
    (d) => !d.pricing && d.extraction.state === 'done' && d.extraction.text.length > 0,
  )
  const invents = agent.name.endsWith('-invents') || agentName(db, agent).endsWith('-invents')
  const quote = (index: number): MockEvidence[] => {
    const doc = documents[index % Math.max(1, documents.length)]
    if (!doc) return []
    const text =
      invents && index === 0
        ? 'We guarantee a dedicated account team available around the clock.'
        : passage(doc.extraction.text, index)
    return text ? [{ document_id: doc.id, quote: text }] : []
  }
  let index = 0
  const scores: MockBidAiAssessment['scores'] = []
  for (const section of sectionsOf(db, call)) {
    for (const question of questionsOf(db, section)) {
      if (question.type !== 'score') continue
      const evidence = quote(index)
      const score = evidence.length ? (SCORES[index % SCORES.length] ?? 3) : 0
      scores.push({
        question_id: question.id,
        score,
        rationale: evidence.length
          ? `The bid addresses “${question.text}” directly; see the quoted passage.`
          : 'The documents I could read don’t answer this question.',
        evidence,
      })
      index += 1
    }
  }
  const findings: MockBidAiAssessment['findings'] = []
  for (const mustHave of mustHavesOf(db, call)) {
    if (mustHave.pricing) continue
    if (mustHave.kind === 'document') {
      const linked = documentsOf(db, bid).find((d) => d.must_have_id === mustHave.id && !d.pricing)
      findings.push(
        linked
          ? {
              must_have_id: mustHave.id,
              finding: 'met',
              rationale: `A file is attached for “${mustHave.text}”.`,
              evidence: quote(index++),
            }
          : {
              must_have_id: mustHave.id,
              finding: 'not_met',
              rationale: `I found no ${mustHave.text.toLowerCase()} among the documents.`,
              evidence: [],
            },
      )
    } else {
      const text = documents.map((d) => d.extraction.text).join('\n')
      const accepts = /accept(s|ed)? (your|the) (standard )?terms/i.exec(text)
      findings.push(
        accepts
          ? {
              must_have_id: mustHave.id,
              finding: 'met',
              rationale: 'The bid says it accepts the terms.',
              evidence: quote(index++),
            }
          : {
              must_have_id: mustHave.id,
              finding: 'unclear',
              rationale: 'I couldn’t find a clear statement about this.',
              evidence: [],
            },
      )
    }
  }
  const at = new Date().toISOString()
  const earlier = db.bid.aiAssessments.find((a) => a.bid_id === bid.id && a.agent_id === agent.id)
  if (earlier) {
    const changed =
      JSON.stringify(earlier.scores.map((s) => [s.question_id, s.score])) !==
      JSON.stringify(scores.map((s) => [s.question_id, s.score]))
    earlier.scores = scores
    earlier.findings = findings
    earlier.submitted_at = at
    if (changed) earlier.included = false
    run.bid_ai_assessment_id = earlier.id
  } else {
    const assessment: MockBidAiAssessment = {
      id: newId(db, ID_KIND.phase5),
      bid_id: bid.id,
      agent_id: agent.id,
      submitted_at: at,
      included: false,
      scores,
      findings,
    }
    db.bid.aiAssessments.push(assessment)
    run.bid_ai_assessment_id = assessment.id
  }
  return null
}
