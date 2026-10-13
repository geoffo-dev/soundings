import type {
  BidCallTemplate,
  BidCallTemplateIn,
  BidQuestionType,
  BidTemplate,
  BidTemplateIn,
  FieldError,
  MustHaveKind,
} from '@/api/types'
import { moveItem } from '@/features/project/settings/rubric'

/**
 * The bid evaluation template's form model (contract-phase10 §4), shared by Project
 * settings → Bids (the project's default) and a call's own copy (which keeps ids, so
 * assessments, results and assessors stay with their questions). The limits follow the
 * schema: 1-8 sections whose weights add up to 100, 1-15 questions each with at least
 * one score question, at most one price question in the template, 0-20 must-haves, six
 * scale anchors. Saving replaces the whole template.
 */
export const TEMPLATE_LIMITS = {
  sections: 8,
  questions: 15,
  mustHaves: 20,
  scale: 6,
  sectionTitle: 60,
  sectionGuidance: 500,
  questionText: 300,
  questionGuidance: 1000,
  mustHaveText: 200,
  scaleLabel: 80,
} as const

export interface QuestionDraft {
  /** Stable React key. */
  id: string
  /** The question's id in a call's copy; null for a new one (and always in a project). */
  serverId: string | null
  text: string
  guidance: string
  type: BidQuestionType
  /** As typed (a number input); comment questions keep 0. */
  weight: string
}

export interface SectionDraft {
  id: string
  serverId: string | null
  title: string
  guidance: string
  weight: string
  questions: QuestionDraft[]
}

export interface MustHaveDraft {
  id: string
  serverId: string | null
  text: string
  kind: MustHaveKind
  pricing: boolean
}

export interface TemplateDraft {
  scale: string[]
  sections: SectionDraft[]
  mustHaves: MustHaveDraft[]
}

export const QUESTION_TYPE_LABELS: Record<BidQuestionType, string> = {
  score: 'Score 0-5',
  price: 'Price',
  comment: 'Comment',
}

export const QUESTION_TYPE_HELP: Record<BidQuestionType, string> = {
  score: 'Each assessor of the section scores it from 0 to 5.',
  price: 'Scored automatically from each bid’s price: lowest price ÷ this price × 5.',
  comment: 'Assessors write an answer; it isn’t scored.',
}

export const MUST_HAVE_KIND_LABELS: Record<MustHaveKind, string> = {
  document: 'Required document',
  confirmation: 'Confirmation',
}

let counter = 0
const key = (prefix: string) => {
  counter += 1
  return `${prefix}-new-${counter}`
}

type AnyTemplate = BidTemplate | BidCallTemplate

function hasIds(template: AnyTemplate): template is BidCallTemplate {
  return 'price_question_id' in template
}

export function toDraft(template: AnyTemplate): TemplateDraft {
  if (hasIds(template)) {
    return {
      scale: [...template.scale],
      sections: template.sections.map((section) => ({
        id: section.id,
        serverId: section.id,
        title: section.title,
        guidance: section.guidance,
        weight: String(section.weight),
        questions: section.questions.map((q) => ({
          id: q.id,
          serverId: q.id,
          text: q.text,
          guidance: q.guidance,
          type: q.type,
          weight: String(q.weight),
        })),
      })),
      mustHaves: template.must_haves.map((m) => ({
        id: m.id,
        serverId: m.id,
        text: m.text,
        kind: m.kind,
        pricing: m.pricing,
      })),
    }
  }
  return {
    scale: [...template.scale],
    sections: template.sections.map((section, i) => ({
      id: `section-${i}`,
      serverId: null,
      title: section.title,
      guidance: section.guidance,
      weight: String(section.weight),
      questions: section.questions.map((q, j) => ({
        id: `section-${i}-q-${j}`,
        serverId: null,
        text: q.text,
        guidance: q.guidance,
        type: q.type,
        weight: String(q.weight),
      })),
    })),
    mustHaves: template.must_haves.map((m, i) => ({
      id: `must-have-${i}`,
      serverId: null,
      text: m.text,
      kind: m.kind,
      pricing: m.pricing,
    })),
  }
}

export function emptyQuestion(type: BidQuestionType = 'score'): QuestionDraft {
  return {
    id: key('q'),
    serverId: null,
    text: '',
    guidance: '',
    type,
    weight: type === 'comment' ? '0' : '1',
  }
}

export function emptySection(): SectionDraft {
  return {
    id: key('section'),
    serverId: null,
    title: '',
    guidance: '',
    weight: '',
    questions: [emptyQuestion()],
  }
}

export function emptyMustHave(): MustHaveDraft {
  return { id: key('must-have'), serverId: null, text: '', kind: 'document', pricing: false }
}

export const moveRow = moveItem

/** The weights as numbers (NaN for what isn't a whole number). */
function weightOf(value: string): number {
  return /^\d+$/.test(value.trim()) ? Number(value.trim()) : Number.NaN
}

/** Σ section weights (what can be added up), for "Weights add up to 90%". */
export function weightTotal(draft: TemplateDraft): number {
  return draft.sections.reduce((sum, s) => {
    const w = weightOf(s.weight)
    return Number.isNaN(w) ? sum : sum + w
  }, 0)
}

export function priceQuestionCount(draft: TemplateDraft): number {
  return draft.sections.flatMap((s) => s.questions).filter((q) => q.type === 'price').length
}

/** Field errors keyed `<row id>:<field>`; `form` for what belongs to the whole template. */
export interface TemplateErrors {
  fields: Record<string, string>
  form?: string
}

const LINE_BREAK = /[\r\n]/

function checkText(
  errors: TemplateErrors,
  id: string,
  value: string,
  { min, max, label, line = true }: { min: number; max: number; label: string; line?: boolean },
) {
  const text = value.trim()
  if (text.length < min) errors.fields[id] = `Enter ${label}.`
  else if (text.length > max) errors.fields[id] = `At most ${max} characters.`
  else if (line && LINE_BREAK.test(text)) errors.fields[id] = 'One line, please.'
}

export function validateTemplate(draft: TemplateDraft): TemplateErrors {
  const errors: TemplateErrors = { fields: {} }
  draft.scale.forEach((label, score) =>
    checkText(errors, `scale-${score}:label`, label, {
      min: 1,
      max: TEMPLATE_LIMITS.scaleLabel,
      label: `what a ${score} means`,
    }),
  )
  const titles = new Map<string, number>()
  for (const section of draft.sections) {
    const title = section.title.trim().toLowerCase()
    if (title) titles.set(title, (titles.get(title) ?? 0) + 1)
  }
  for (const section of draft.sections) {
    checkText(errors, `${section.id}:title`, section.title, {
      min: 1,
      max: TEMPLATE_LIMITS.sectionTitle,
      label: 'a title',
    })
    if (
      !errors.fields[`${section.id}:title`] &&
      (titles.get(section.title.trim().toLowerCase()) ?? 0) > 1
    ) {
      errors.fields[`${section.id}:title`] = 'Another section has this title.'
    }
    if (section.guidance.trim().length > TEMPLATE_LIMITS.sectionGuidance) {
      errors.fields[`${section.id}:guidance`] =
        `At most ${TEMPLATE_LIMITS.sectionGuidance} characters.`
    }
    const weight = weightOf(section.weight)
    if (Number.isNaN(weight) || weight < 1 || weight > 100) {
      errors.fields[`${section.id}:weight`] = 'A whole number from 1 to 100.'
    }
    if (section.questions.length === 0) errors.fields[`${section.id}:questions`] = 'Add a question.'
    else if (!section.questions.some((q) => q.type === 'score')) {
      errors.fields[`${section.id}:questions`] =
        'Every section needs at least one question assessors score.'
    }
    for (const q of section.questions) {
      checkText(errors, `${q.id}:text`, q.text, {
        min: 1,
        max: TEMPLATE_LIMITS.questionText,
        label: 'the question',
      })
      if (q.guidance.trim().length > TEMPLATE_LIMITS.questionGuidance) {
        errors.fields[`${q.id}:guidance`] =
          `At most ${TEMPLATE_LIMITS.questionGuidance} characters.`
      }
      if (q.type !== 'comment') {
        const w = weightOf(q.weight)
        if (Number.isNaN(w) || w < 1 || w > 100) {
          errors.fields[`${q.id}:weight`] = 'A whole number from 1 to 100.'
        }
      }
    }
  }
  if (draft.sections.length === 0) errors.form = 'Add a section.'
  else if (
    weightTotal(draft) !== 100 &&
    draft.sections.every((s) => !errors.fields[`${s.id}:weight`])
  ) {
    errors.form = `The section weights add up to ${weightTotal(draft)}%: they need to make 100%.`
  }
  if (priceQuestionCount(draft) > 1) {
    errors.form ??= 'A template has at most one price question.'
  }
  const texts = new Map<string, number>()
  for (const m of draft.mustHaves) {
    const text = m.text.trim().toLowerCase()
    if (text) texts.set(text, (texts.get(text) ?? 0) + 1)
  }
  for (const m of draft.mustHaves) {
    checkText(errors, `${m.id}:text`, m.text, {
      min: 1,
      max: TEMPLATE_LIMITS.mustHaveText,
      label: 'the must-have',
    })
    if (!errors.fields[`${m.id}:text`] && (texts.get(m.text.trim().toLowerCase()) ?? 0) > 1) {
      errors.fields[`${m.id}:text`] = 'Another must-have says this.'
    }
  }
  return errors
}

export function hasErrors(errors: TemplateErrors): boolean {
  return Boolean(errors.form) || Object.keys(errors.fields).length > 0
}

const weightIn = (q: QuestionDraft) => (q.type === 'comment' ? 0 : weightOf(q.weight))

export function toTemplateIn(draft: TemplateDraft): BidTemplateIn {
  return {
    scale: draft.scale.map((label) => label.trim()),
    sections: draft.sections.map((s) => ({
      title: s.title.trim(),
      guidance: s.guidance.trim(),
      weight: weightOf(s.weight),
      questions: s.questions.map((q) => ({
        text: q.text.trim(),
        guidance: q.guidance.trim(),
        type: q.type,
        weight: weightIn(q),
      })),
    })),
    must_haves: draft.mustHaves.map((m) => ({
      text: m.text.trim(),
      kind: m.kind,
      pricing: m.kind === 'document' && m.pricing,
    })),
  }
}

export function toCallTemplateIn(draft: TemplateDraft): BidCallTemplateIn {
  const base = toTemplateIn(draft)
  return {
    scale: base.scale,
    sections: base.sections.map((s, i) => ({
      ...s,
      id: draft.sections[i]?.serverId ?? null,
      questions: s.questions.map((q, j) => ({
        ...q,
        id: draft.sections[i]?.questions[j]?.serverId ?? null,
      })),
    })),
    must_haves: (base.must_haves ?? []).map((m, i) => ({
      ...m,
      id: draft.mustHaves[i]?.serverId ?? null,
    })),
  }
}

/** Compare by what is saved (trimmed text, numbers), never by React keys. */
export function isDirty(draft: TemplateDraft, baseline: TemplateDraft): boolean {
  const shape = (d: TemplateDraft) =>
    JSON.stringify({
      scale: d.scale.map((s) => s.trim()),
      sections: d.sections.map((s) => [
        s.serverId,
        s.title.trim(),
        s.guidance.trim(),
        s.weight.trim(),
        s.questions.map((q) => [
          q.serverId,
          q.text.trim(),
          q.guidance.trim(),
          q.type,
          q.type === 'comment' ? '0' : q.weight.trim(),
        ]),
      ]),
      mustHaves: d.mustHaves.map((m) => [
        m.serverId,
        m.text.trim(),
        m.kind,
        m.kind === 'document' && m.pricing,
      ]),
    })
  return shape(draft) !== shape(baseline)
}

/**
 * A 422 from the server (`loc: ["body", "sections", 1, "questions", 0, "text"]`) put next
 * to its field; anything else becomes the form's message.
 */
export function serverErrors(
  draft: TemplateDraft,
  details: Pick<FieldError, 'loc' | 'msg'>[],
): TemplateErrors {
  const errors: TemplateErrors = { fields: {} }
  for (const { loc, msg } of details) {
    const [, area, i, field, j, subField] = loc
    const message = msg || 'Check this value.'
    if (area === 'scale' && typeof i === 'number') errors.fields[`scale-${i}:label`] = message
    else if (area === 'sections' && typeof i === 'number') {
      const section = draft.sections[i]
      if (
        section &&
        field === 'questions' &&
        typeof j === 'number' &&
        typeof subField === 'string'
      ) {
        const q = section.questions[j]
        if (q) errors.fields[`${q.id}:${subField}`] = message
        else errors.form ??= message
      } else if (section && typeof field === 'string')
        errors.fields[`${section.id}:${field}`] = message
      else errors.form ??= message
    } else if (area === 'must_haves' && typeof i === 'number' && typeof field === 'string') {
      const m = draft.mustHaves[i]
      if (m) errors.fields[`${m.id}:${field}`] = message
      else errors.form ??= message
    } else errors.form ??= message
  }
  return errors
}
