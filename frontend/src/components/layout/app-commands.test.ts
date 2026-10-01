import { describe, expect, it } from 'vitest'

import { rankGroups } from '@/components/layout/app-commands'
import type { CommandGroupData } from '@/components/ui/command-palette'

const action = (label: string, keywords?: string[], hint?: string) => ({
  id: label,
  label,
  keywords,
  hint,
  onSelect: () => undefined,
})

const groups: CommandGroupData[] = [
  { heading: 'Actions', actions: [action('New idea', ['create', 'submit', 'add'])] },
  {
    heading: 'Go to',
    actions: [
      action('My work', ['home', 'inbox', 'evaluations']),
      action('Internal Tools', ['project', 'internal-tools', 'TOOL'], 'Project'),
      action('Design system', [], 'Dev only'),
    ],
  },
  { heading: 'Preferences', actions: [action('Sign out', ['log out', 'logout'])] },
]

const labels = (query: string) =>
  rankGroups(groups, query).flatMap((group) => group.actions.map((a) => a.label))

describe('rankGroups (⌘K local results)', () => {
  it('lists everything, in order, without a query', () => {
    expect(labels('')).toEqual([
      'New idea',
      'My work',
      'Internal Tools',
      'Design system',
      'Sign out',
    ])
  })

  it('drops letters scattered across a command', () => {
    // "whats" matched My work (w… h… a… t… s) and sat above the WhatsApp idea.
    expect(labels('whats')).toEqual([])
  })

  it('puts the group with the best match first', () => {
    expect(labels('sign')[0]).toBe('Sign out')
    expect(labels('new')[0]).toBe('New idea')
    expect(labels('tools')).toEqual(['Internal Tools'])
  })
})
