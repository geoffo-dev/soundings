/** DOM ids the AI pieces focus across tabs (toasts, run cards, the evaluator row). */

/** A run's card on the Overview tab. */
export const runDomId = (runId: string) => `ai-run-${runId}`

/** A research note in the activity feed. */
export const researchNoteDomId = (noteId: string) => `research-note-${noteId}`

/** An evaluation's card on the Evaluations tab. */
export const evaluationCardDomId = (evaluationId: string) => `evaluation-card-${evaluationId}`
