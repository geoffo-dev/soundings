import { describe, expect, it } from 'vitest'

import {
  activeMentionQuery,
  activeShownQuery,
  applyShownEdit,
  exactMention,
  insertMention,
  MAX_MENTIONS,
  mentionAt,
  mentionedUserIds,
  mentionLabel,
  mentionsToText,
  mentionToken,
  parseMentions,
  removeMention,
  toShown,
  toStored,
  type MentionDraft,
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

describe('exactly one token', () => {
  it('accepts only the server’s spelling', () => {
    expect(exactMention(`@[Ada](user:${ADA.toUpperCase()})`)).toEqual({ label: 'Ada', userId: ADA })
    for (const text of [
      `@[Ada](user:${ADA} "title")`,
      `@[Ada](<user:${ADA}>)`,
      `@[A [B] C](user:${ADA})`,
      `x@[Ada](user:${ADA})`,
      `@[Ada](user:${ADA}) `,
    ]) {
      expect(exactMention(text)).toBeNull()
    }
  })
})

describe('the comment box shows "@Name" and stores tokens', () => {
  const stored = `Hi @[Ada Lovelace](user:${ADA}), and @[Bob](user:${BOB}) too`
  const shown = toShown(stored)

  it('shows each token as @Name and remembers where it is', () => {
    expect(shown.text).toBe('Hi @Ada Lovelace, and @Bob too')
    expect(shown.mentions).toEqual([
      { start: 3, end: 16, label: 'Ada Lovelace', userId: ADA },
      { start: 22, end: 26, label: 'Bob', userId: BOB },
    ])
    expect(toStored(shown)).toBe(stored)
    expect(toShown('plain')).toEqual({ text: 'plain', mentions: [] })
  })

  const edit = (draft: MentionDraft, next: string, caret: number) =>
    toStored(applyShownEdit(draft, next, caret))

  it('keeps mentions the edit doesn’t touch, shifted', () => {
    // Typing at the start, between and right after a mention.
    expect(edit(shown, `Oh ${shown.text}`, 3)).toBe(`Oh ${stored}`)
    expect(edit(shown, 'Hi @Ada Lovelace: and @Bob too', 17)).toBe(
      `Hi @[Ada Lovelace](user:${ADA}): and @[Bob](user:${BOB}) too`,
    )
    expect(edit(shown, 'Hi @Ada Lovelace, and @Bobb too', 27)).toBe(
      `Hi @[Ada Lovelace](user:${ADA}), and @[Bob](user:${BOB})b too`,
    )
    // Deleting the space right after a mention.
    expect(edit(shown, 'Hi @Ada Lovelace, and @Bobtoo', 26)).toBe(
      `Hi @[Ada Lovelace](user:${ADA}), and @[Bob](user:${BOB})too`,
    )
  })

  it('turns a mention the edit changes into plain text', () => {
    expect(edit(shown, 'Hi @Ada Lovelxace, and @Bob too', 14)).toBe(
      `Hi @Ada Lovelxace, and @[Bob](user:${BOB}) too`,
    )
    // A selection across both, replaced.
    expect(edit(shown, 'Hi @Ax too', 6)).toBe('Hi @Ax too')
  })

  it('removes a whole mention (Backspace after it)', () => {
    const mention = mentionAt(shown, 16, 'end')
    if (!mention) throw new Error('no mention ends there')
    expect(mention.label).toBe('Ada Lovelace')
    const result = removeMention(shown, mention)
    expect(result.caret).toBe(3)
    expect(toStored(result.draft)).toBe(`Hi , and @[Bob](user:${BOB}) too`)
    expect(mentionAt(shown, 22, 'start')?.label).toBe('Bob')
    expect(mentionAt(shown, 5, 'end')).toBeUndefined()
  })

  it('never opens the picker on a mention that is already there', () => {
    expect(activeShownQuery(shown, 16)).toBeNull() // right after "@Ada Lovelace"
    const typing = applyShownEdit(shown, `${shown.text} @ca`, shown.text.length + 4)
    expect(activeShownQuery(typing, typing.text.length)).toEqual({
      start: shown.text.length + 1,
      query: 'ca',
    })
  })

  it('keeps a typed token as a mention', () => {
    // Pasting a token: it is one (the server reads the stored text).
    const pasted = toShown(edit(toShown(''), `@[Ada](user:${ADA})`, 49))
    expect(pasted).toEqual({
      text: '@Ada',
      mentions: [{ start: 0, end: 4, label: 'Ada', userId: ADA }],
    })
  })
})

describe('inserting a mention', () => {
  const person = { id: ADA, display_name: 'Ada Lovelace' }

  it('replaces "@query" with "@Name" and a space, and puts the caret after it', () => {
    const result = insertMention(toShown('Thanks @ad'), { start: 7, caret: 10 }, person)
    expect(result.draft.text).toBe('Thanks @Ada Lovelace ')
    expect(toStored(result.draft)).toBe(`Thanks @[Ada Lovelace](user:${ADA}) `)
    expect(result.caret).toBe(result.draft.text.length)
  })

  it('keeps the text after the caret and its mentions, and doesn’t double the space', () => {
    const before = toShown(`@ad for @[Bob](user:${BOB})`)
    const result = insertMention(before, { start: 0, caret: 3 }, person)
    expect(result.draft.text).toBe('@Ada Lovelace for @Bob')
    expect(result.draft.text.slice(result.caret)).toBe(' for @Bob')
    expect(toStored(result.draft)).toBe(`@[Ada Lovelace](user:${ADA}) for @[Bob](user:${BOB})`)
  })
})
