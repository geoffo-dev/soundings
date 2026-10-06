import { describe, expect, it } from 'vitest'

import type { AiAgentRef } from '@/api/types'

import { evaluateActionLabel, submittedEvaluatorIds } from './idea-ai'

const agent = (id: string): AiAgentRef => ({
  id: `agent-${id}`,
  user_id: id,
  display_name: `Agent ${id}`,
  purposes: ['evaluate'],
})

describe('evaluateActionLabel', () => {
  it('says “again” only once every agent offered has submitted (menu, list and ⌘K alike)', () => {
    expect(evaluateActionLabel([agent('a')], [])).toBe('Ask AI to evaluate')
    expect(evaluateActionLabel([agent('a')], ['a'])).toBe('Ask AI to evaluate again')
    expect(evaluateActionLabel([agent('a'), agent('b')], ['a'])).toBe('Ask AI to evaluate')
    expect(evaluateActionLabel([], ['a'])).toBe('Ask AI to evaluate')
  })

  it('takes the submitted evaluators from the idea', () => {
    expect(
      submittedEvaluatorIds([
        { state: 'submitted', user: { id: 'a' } },
        { state: 'pending', user: { id: 'b' } },
      ]),
    ).toEqual(['a'])
  })
})
