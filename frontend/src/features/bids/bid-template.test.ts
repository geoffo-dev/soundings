import { describe, expect, it } from 'vitest'

import type { BidTemplate } from '@/api/types'

import {
  emptyQuestion,
  emptySection,
  hasErrors,
  isDirty,
  priceQuestionCount,
  serverErrors,
  toDraft,
  toTemplateIn,
  validateTemplate,
  weightTotal,
} from './bid-template'

const TEMPLATE: BidTemplate = {
  scale: ['None', 'Poor', 'Weak', 'Adequate', 'Good', 'Excellent'],
  sections: [
    {
      title: 'Technical',
      guidance: 'How well it works.',
      weight: 60,
      questions: [
        { text: 'Does it meet the requirements?', guidance: '', type: 'score', weight: 2 },
        { text: 'Any risks?', guidance: '', type: 'comment', weight: 0 },
      ],
    },
    {
      title: 'Commercial',
      guidance: '',
      weight: 40,
      questions: [
        { text: 'Price', guidance: '', type: 'price', weight: 1 },
        { text: 'Are the terms acceptable?', guidance: '', type: 'score', weight: 1 },
      ],
    },
  ],
  must_haves: [
    { text: 'Insurance certificate', kind: 'document', pricing: false },
    { text: 'Pricing schedule', kind: 'document', pricing: true },
  ],
  updated_at: null,
  updated_by: null,
  can_edit: true,
}

describe('the bid template form', () => {
  it('round-trips the project template unchanged', () => {
    const draft = toDraft(TEMPLATE)
    expect(hasErrors(validateTemplate(draft))).toBe(false)
    expect(weightTotal(draft)).toBe(100)
    expect(priceQuestionCount(draft)).toBe(1)
    expect(toTemplateIn(draft)).toEqual({
      scale: TEMPLATE.scale,
      sections: TEMPLATE.sections,
      must_haves: TEMPLATE.must_haves,
    })
    expect(isDirty(draft, toDraft(TEMPLATE))).toBe(false)
  })

  it('says the weights must make 100, in the form’s own message', () => {
    const draft = toDraft(TEMPLATE)
    const [first] = draft.sections
    if (!first) throw new Error('no section')
    first.weight = '50'
    const errors = validateTemplate(draft)
    expect(errors.form).toBe('The section weights add up to 90%: they need to make 100%.')
    expect(isDirty(draft, toDraft(TEMPLATE))).toBe(true)
  })

  it('needs a scored question per section, one price question at most, distinct titles', () => {
    const draft = toDraft(TEMPLATE)
    const section = { ...emptySection(), title: 'technical', weight: '0' }
    section.questions = [{ ...emptyQuestion('comment'), text: 'Notes' }]
    draft.sections.push(section)
    const second = draft.sections[1]
    second?.questions.push({ ...emptyQuestion('price'), text: 'Another price', weight: '1' })
    const errors = validateTemplate(draft)
    expect(errors.fields[`${section.id}:questions`]).toBe(
      'Every section needs at least one question assessors score.',
    )
    expect(errors.fields[`${section.id}:title`]).toBe('Another section has this title.')
    expect(errors.fields[`${section.id}:weight`]).toBe('A whole number from 1 to 100.')
    expect(errors.form).toBe('A template has at most one price question.')
  })

  it('puts a server 422 next to its field', () => {
    const draft = toDraft(TEMPLATE)
    const question = draft.sections[0]?.questions[0]
    const errors = serverErrors(draft, [
      { loc: ['body', 'sections', 0, 'questions', 0, 'text'], msg: 'Too long' },
      { loc: ['body', 'must_haves', 1, 'pricing'], msg: 'Only document must-haves' },
      { loc: ['body'], msg: 'Something else' },
    ])
    expect(errors.fields[`${question?.id}:text`]).toBe('Too long')
    expect(errors.fields[`${draft.mustHaves[1]?.id}:pricing`]).toBe('Only document must-haves')
    expect(errors.form).toBe('Something else')
  })
})
