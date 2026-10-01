import { describe, expect, it } from 'vitest'

import {
  activeMentionQuery,
  insertMention,
  MAX_MENTIONS,
  mentionedUserIds,
  mentionLabel,
  mentionsToText,
  mentionToken,
  parseMentions,
} from './mentions'

const ADA = '10000000-0000-4000-8000-000000000002'
const BOB = '10000000-0000-4000-8000-000000000003'

describe('mention tokens (contract-phase3 §3.8)', () => {
  it('builds the token the server expects, with a safe label', () => {
    expect(mentionToken(ADA, 'Ada Lovelace')).toBe(`@[Ada Lovelace](user:${ADA})`)
    // Brackets and line breaks would end the label early: removed, spaces collapsed.
    expect(mentionLabel('Ada [admin]\nLovelace  ')).toBe('Ada admin Lovelace')
    expect(mentionLabel('[]')).toBe('user')
    expect(mentionLabel('x'.repeat(150))).toHaveLength(100)
  })

  it('parses tokens anywhere and lists each person once, in order', () => {
    const text = `Hi @[Bob](user:${BOB}) and @[Ada](user:${ADA.toUpperCase()}), cc @[Bob B](user:${BOB})`
    expect(parseMentions(text).map((m) => m.label)).toEqual(['Bob', 'Ada', 'Bob B'])
    expect(mentionedUserIds(text)).toEqual([BOB, ADA])
    expect(parseMentions(text)[0]).toMatchObject({ start: 3, userId: BOB })
    expect(MAX_MENTIONS).toBe(20)
  })

  it('treats anything else as plain text', () => {
    expect(mentionedUserIds('@ada and @[Ada](user:not-a-uuid) and [Ada](user:x)')).toEqual([])
    expect(mentionedUserIds(`[Ada](user:${ADA})`)).toEqual([]) // no "@"
  })

  it('shows tokens as @Name in plain text', () => {
    expect(mentionsToText(`Thanks @[Ada Lovelace](user:${ADA})!`)).toBe('Thanks @Ada Lovelace!')
  })
})

describe('the mention being typed', () => {
  it('opens after "@" at the start or after a space or bracket', () => {
    expect(activeMentionQuery('@', 1)).toEqual({ start: 0, query: '' })
    expect(activeMentionQuery('Thanks @ad', 10)).toEqual({ start: 7, query: 'ad' })
    expect(activeMentionQuery('(@bo', 4)).toEqual({ start: 1, query: 'bo' })
    // Names have spaces.
    expect(activeMentionQuery('cc @Ada Lov', 11)).toEqual({ start: 3, query: 'Ada Lov' })
  })

  it('stays closed for email addresses, finished tokens, new lines and long text', () => {
    expect(activeMentionQuery('mail bob@example.com', 20)).toBeNull()
    const token = `@[Ada](user:${ADA}) `
    expect(activeMentionQuery(token, token.length)).toBeNull()
    expect(activeMentionQuery('@ada\nnext', 9)).toBeNull()
    expect(activeMentionQuery('@ ', 2)).toBeNull()
    expect(activeMentionQuery('@ada  x', 7)).toBeNull()
    expect(activeMentionQuery(`@${'a'.repeat(41)}`, 42)).toBeNull()
    expect(activeMentionQuery('no at sign', 5)).toBeNull()
  })

  it('only looks before the caret', () => {
    expect(activeMentionQuery('@ada later text', 4)).toEqual({ start: 0, query: 'ada' })
  })
})

describe('inserting a mention', () => {
  const person = { id: ADA, display_name: 'Ada Lovelace' }

  it('replaces "@query" with the token and a space, and puts the caret after it', () => {
    const result = insertMention('Thanks @ad', { start: 7, caret: 10 }, person)
    expect(result.text).toBe(`Thanks @[Ada Lovelace](user:${ADA}) `)
    expect(result.caret).toBe(result.text.length)
  })

  it('keeps the text after the caret and doesn’t double the space', () => {
    const result = insertMention('@ad for review', { start: 0, caret: 3 }, person)
    expect(result.text).toBe(`@[Ada Lovelace](user:${ADA}) for review`)
    expect(result.text.slice(result.caret)).toBe(' for review')
  })
})
