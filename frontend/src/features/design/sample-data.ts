import type { ClosedResolution, IdeaStatus } from '@/lib/status'

/** Illustrative data for the /design page only. */

export interface SamplePerson {
  id: string
  name: string
  src?: string | null
  isAgent?: boolean
  email?: string
}

// A soft gradient "photo" as an inline SVG — nothing is fetched from the network.
const photo = (a: string, b: string) =>
  `data:image/svg+xml,${encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="${a}"/><stop offset="1" stop-color="${b}"/></linearGradient></defs><rect width="64" height="64" fill="url(#g)"/><circle cx="32" cy="26" r="11" fill="#fff" fill-opacity=".85"/><path d="M12 60c3-12 11-18 20-18s17 6 20 18" fill="#fff" fill-opacity=".85"/></svg>`,
  )}`

export const PEOPLE: SamplePerson[] = [
  {
    id: 'u1',
    name: 'Priya Natarajan',
    email: 'priya@example.com',
    src: photo('#7aa6d8', '#1d5fa8'),
  },
  { id: 'u2', name: 'Tom Okafor', email: 'tom@example.com' },
  { id: 'u3', name: 'Lena Fischer', email: 'lena@example.com' },
  { id: 'u4', name: 'Marcus Webb', email: 'marcus@example.com' },
  { id: 'u5', name: 'Aiko Tanaka', email: 'aiko@example.com', src: photo('#d9b38c', '#8a5a3c') },
  { id: 'u6', name: 'Sam Rivera', email: 'sam@example.com' },
  { id: 'ai', name: 'Research agent', isAgent: true },
]

export const person = (id: string): SamplePerson => {
  const found = PEOPLE.find((p) => p.id === id)
  if (!found) throw new Error(`Unknown sample person ${id}`)
  return found
}

export interface SampleIdea {
  id: string
  key: string
  title: string
  summary: string
  status: IdeaStatus
  resolution?: ClosedResolution
  ownerId: string | null
  evaluatorIds: string[]
  submitted: number
  score: number | null
  hidden?: boolean
  disagreement?: boolean
  tags: string[]
  /** ISO timestamp — shown with <RelativeTime> (lib/dates.ts). */
  updatedAt: string
}

const HOUR = 3_600_000
/** A timestamp `hours` before the page loaded, so relative times read naturally. */
const ago = (hours: number) => new Date(Date.now() - hours * HOUR).toISOString()
/** A due date `days` from now. */
export const inDays = (days: number) => new Date(Date.now() + days * 24 * HOUR).toISOString()

export const IDEAS: SampleIdea[] = [
  {
    id: 'i1',
    key: 'CI-42',
    title: 'Self-serve returns portal for business customers',
    summary: 'Let account admins start and track returns without calling support.',
    status: 'evaluating',
    ownerId: 'u1',
    evaluatorIds: ['u2', 'u3', 'u4', 'ai'],
    submitted: 3,
    score: 3.8,
    disagreement: true,
    tags: ['Support', 'B2B'],
    updatedAt: ago(2),
  },
  {
    id: 'i2',
    key: 'CI-38',
    title: 'Carbon footprint estimate on every order',
    summary: 'Show an estimate at checkout and in the monthly account summary.',
    status: 'shortlisted',
    ownerId: 'u5',
    evaluatorIds: ['u1', 'u2', 'u6'],
    submitted: 3,
    score: 4.4,
    tags: ['Sustainability'],
    updatedAt: ago(26),
  },
  {
    id: 'i3',
    key: 'CI-51',
    title: 'Offline mode for field engineers',
    summary: 'Cache job sheets so engineers can work in basements and rural sites.',
    status: 'new',
    ownerId: null,
    evaluatorIds: [],
    submitted: 0,
    score: null,
    tags: ['Mobile'],
    updatedAt: ago(72),
  },
  {
    id: 'i4',
    key: 'CI-29',
    title: 'Partner API for inventory sync',
    summary: 'A documented API so resellers stop scraping our stock pages.',
    status: 'proposal',
    ownerId: 'u4',
    evaluatorIds: ['u1', 'u3', 'u5', 'u6'],
    submitted: 4,
    score: 4.1,
    tags: ['Platform', 'Partners'],
    updatedAt: ago(170),
  },
  {
    id: 'i5',
    key: 'CI-17',
    title: 'Gamified onboarding checklist',
    summary: 'Badges and streaks for completing account setup steps.',
    status: 'closed',
    resolution: 'parked',
    ownerId: 'u2',
    evaluatorIds: ['u1', 'u4'],
    submitted: 2,
    score: 2.3,
    tags: ['Onboarding'],
    updatedAt: ago(4800),
  },
]

export interface Criterion {
  id: string
  name: string
  description: string
  weight: number
  guidance: Record<1 | 2 | 3 | 4 | 5, string>
}

/** The default rubric from SPEC §2 (Effort and Risk are inverted: 5 = low effort / low risk). */
export const RUBRIC: Criterion[] = [
  {
    id: 'value',
    name: 'Value',
    description: 'How much does this matter to customers or the business?',
    weight: 3,
    guidance: {
      1: 'Nice to have; few people would notice',
      2: 'Helps a small group a little',
      3: 'Clear benefit for a meaningful group',
      4: 'Strong benefit, customers are asking for it',
      5: 'Transformative for customers or revenue',
    },
  },
  {
    id: 'feasibility',
    name: 'Feasibility',
    description: 'Can we realistically build and run it?',
    weight: 2,
    guidance: {
      1: 'Unclear if it is possible at all',
      2: 'Major unknowns or dependencies',
      3: 'Doable with some open questions',
      4: 'We know how; few unknowns',
      5: 'Straightforward with what we have',
    },
  },
  {
    id: 'effort',
    name: 'Effort',
    description: 'How much work is it? Higher score means less effort.',
    weight: 2,
    guidance: {
      1: 'Many teams for many months',
      2: 'A team for a quarter or more',
      3: 'A team for a few weeks',
      4: 'A small team for a week or two',
      5: 'Days of work',
    },
  },
  {
    id: 'fit',
    name: 'Strategic fit',
    description: 'Does it move this year’s priorities forward?',
    weight: 2,
    guidance: {
      1: 'Unrelated to our priorities',
      2: 'Loosely related',
      3: 'Supports a priority indirectly',
      4: 'Directly supports a priority',
      5: 'Core to our strategy',
    },
  },
  {
    id: 'risk',
    name: 'Risk',
    description: 'What could go wrong? Higher score means lower risk.',
    weight: 1,
    guidance: {
      1: 'Serious legal, security or brand risk',
      2: 'Significant risk that needs mitigation',
      3: 'Manageable, known risks',
      4: 'Minor risks',
      5: 'Negligible risk',
    },
  },
]

export const CRITERION_RESULTS: Record<string, { value: number; min: number; max: number }> = {
  value: { value: 4.3, min: 4, max: 5 },
  feasibility: { value: 3.7, min: 3, max: 4 },
  effort: { value: 2.7, min: 1, max: 4 },
  fit: { value: 4.0, min: 4, max: 4 },
  risk: { value: 3.3, min: 3, max: 4 },
}

export const SAMPLE_MARKDOWN = `Business customers currently **phone support** to start a return, which takes ~9 minutes per call and peaks after quarter-end.

### Proposal
1. A returns page in the account area
2. Label printing and courier booking
3. Status updates by email

- [x] Talk to three enterprise customers
- [ ] Size the courier integration

> “We'd use this every week.” — Ops lead at a pilot customer

See the [support dashboard](https://example.com/dashboard) and the \`returns_v2\` flag.

| Metric | Today | Target |
| --- | --- | --- |
| Calls per month | 1,240 | 400 |
| Avg handling time | 9 min | 2 min |
`
