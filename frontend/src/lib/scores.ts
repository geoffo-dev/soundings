/** Scores are 1–5. Bands map an aggregate (e.g. 3.8) to a colour step. */
export type ScoreBand = 1 | 2 | 3 | 4 | 5

export const SCORE_MIN = 1
export const SCORE_MAX = 5

export function scoreBand(score: number): ScoreBand {
  const rounded = Math.round(Math.min(SCORE_MAX, Math.max(SCORE_MIN, score)))
  return rounded as ScoreBand
}

export function formatScore(score: number | null | undefined): string {
  if (score === null || score === undefined || Number.isNaN(score)) return '–'
  return score.toFixed(1)
}

/** Tailwind classes per band — keep literal so Tailwind can see them. */
export const SCORE_FILL: Record<ScoreBand, string> = {
  1: 'bg-score-1',
  2: 'bg-score-2',
  3: 'bg-score-3',
  4: 'bg-score-4',
  5: 'bg-score-5',
}

export const SCORE_TINT: Record<ScoreBand, string> = {
  1: 'bg-score-1/15',
  2: 'bg-score-2/15',
  3: 'bg-score-3/18',
  4: 'bg-score-4/18',
  5: 'bg-score-5/15',
}
