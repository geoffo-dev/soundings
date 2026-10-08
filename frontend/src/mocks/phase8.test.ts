import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from 'vitest'

import { api } from '@/api/client'
import { ApiError } from '@/api/errors'
import { getDb, resetDb, USERS } from '@/mocks/db'
import { RESEARCH_ITEMS } from '@/mocks/phase8-fixtures'
import { similarity } from '@/mocks/research'
import { server } from '@/mocks/server'
import { endSession } from '@/mocks/session'

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
beforeEach(() => {
  resetDb()
  localStorage.setItem('soundings-mock-latency', 'none')
})
afterEach(() => {
  server.resetHandlers()
  endSession()
})
afterAll(() => server.close())

async function signIn(userId: string) {
  await api.POST('/api/v1/auth/dev/login', { body: { user_id: userId } })
}

async function rejection(promise: Promise<unknown>): Promise<ApiError> {
  try {
    await promise
  } catch (error) {
    if (error instanceof ApiError) return error
    throw error
  }
  throw new Error('expected the request to fail')
}

const idea = (key: string) => ({ params: { path: { idea: key } } })
const move = (key: string, status: 'research' | 'evaluating' | 'new' | 'proposal', extra = {}) =>
  api.POST('/api/v1/ideas/{idea}/status', { ...idea(key), body: { status, ...extra } })

describe('the lifecycle per project', () => {
  it('gives each project its lifecycle and board columns', async () => {
    await signIn(USERS.alice)
    const tools = await api.GET('/api/v1/projects/{slug}', {
      params: { path: { slug: 'internal-tools' } },
    })
    expect(tools.data?.research_step).toBe('before_evaluation')
    expect(tools.data?.lifecycle).toEqual([
      'new',
      'research',
      'evaluating',
      'shortlisted',
      'proposal',
      'closed',
    ])
    const board = await api.GET('/api/v1/projects/{slug}/board', {
      params: { path: { slug: 'sustainability' } },
    })
    expect(board.data?.columns.map((c) => c.status)).toEqual([
      'new',
      'evaluating',
      'shortlisted',
      'research',
      'proposal',
      'closed',
    ])
    const cust = await api.GET('/api/v1/projects/{slug}/board', {
      params: { path: { slug: 'customer-innovation' } },
    })
    expect(cust.data?.columns.map((c) => c.status)).not.toContain('research')
  })

  it('refuses Research while the step is off', async () => {
    await signIn(USERS.priya)
    const error = await rejection(move('CUST-2', 'research'))
    expect(error).toMatchObject({ status: 409, code: 'research_step_off' })
  })

  it('shows research progress only in Research or the status before it', async () => {
    await signIn(USERS.alice)
    const tool7 = await api.GET('/api/v1/ideas/{idea}', idea('TOOL-7'))
    expect(tool7.data?.research).toEqual({ answered: 1, total: 3, required_open: 1 })
    const tool5 = await api.GET('/api/v1/ideas/{idea}', idea('TOOL-5'))
    expect(tool5.data?.research).toMatchObject({ answered: 0, total: 3, required_open: 2 })
    const tool1 = await api.GET('/api/v1/ideas/{idea}', idea('TOOL-1'))
    expect(tool1.data?.research).toBeNull()
  })
})

describe('the research gate', () => {
  it('refuses a move past Research with the open required items', async () => {
    await signIn(USERS.bob) // TOOL-7's owner, a member
    const error = await rejection(move('TOOL-7', 'evaluating'))
    expect(error).toMatchObject({ status: 409, code: 'research_incomplete' })
    expect(error.problem).toMatchObject({
      open_items: [
        { item_id: RESEARCH_ITEMS.toolConsulted, title: 'Departments or teams consulted' },
      ],
      can_override: false,
    })
  })

  it('lets owners move back and close, never guarded', async () => {
    await signIn(USERS.bob)
    expect((await move('TOOL-7', 'new')).data?.status).toBe('new')
    const closed = await api.POST('/api/v1/ideas/{idea}/status', {
      ...idea('TOOL-7'),
      body: { status: 'closed', resolution: 'parked' },
    })
    expect(closed.data?.status).toBe('closed')
    // Reopening into Evaluating counts from where it was closed (New): guarded.
    expect((await rejection(move('TOOL-7', 'evaluating'))).code).toBe('research_incomplete')
  })

  it('refuses the override to owners (403) and audits an admin’s', async () => {
    await signIn(USERS.bob)
    expect(
      await rejection(move('TOOL-7', 'evaluating', { override_research: true })),
    ).toMatchObject({ status: 403 })
    endSession()
    await signIn(USERS.alice) // TOOL admin
    const refused = await rejection(move('TOOL-7', 'evaluating'))
    expect(refused.problem).toMatchObject({ can_override: true })
    const moved = await move('TOOL-7', 'evaluating', {
      override_research: true,
      override_reason: 'Legal agreed on a call',
    })
    expect(moved.data?.status).toBe('evaluating')
    const entry = getDb().audit.at(-1)
    expect(entry).toMatchObject({
      action: 'idea.research_override',
      details: expect.objectContaining({ to_status: 'evaluating', open_items: 1 }) as unknown,
    })
    const activity = await api.GET('/api/v1/ideas/{idea}/activity', idea('TOOL-7'))
    const overridden = activity.data?.items.filter(
      (item) => item.type === 'status_changed' && item.research_overridden,
    )
    expect(overridden).toHaveLength(1)
  })

  it('a complete checklist lets every path through; clearing an answer re-arms it', async () => {
    await signIn(USERS.alice)
    expect((await move('TOOL-10', 'evaluating')).data?.status).toBe('evaluating')
    await move('TOOL-10', 'research')
    await api.DELETE('/api/v1/ideas/{idea}/research/items/{item_id}', {
      params: { path: { idea: 'TOOL-10', item_id: RESEARCH_ITEMS.toolElsewhere } },
    })
    expect((await rejection(move('TOOL-10', 'evaluating'))).code).toBe('research_incomplete')
  })

  it('guards the first invite before evaluation, and starting a proposal before the proposal', async () => {
    await signIn(USERS.bob)
    const detail = await api.GET('/api/v1/ideas/{idea}', idea('TOOL-7'))
    expect(detail.data?.permissions.invite_blocked_by_research).toBe(true)
    const invite = await rejection(
      api.POST('/api/v1/ideas/{idea}/evaluators', {
        ...idea('TOOL-7'),
        body: { user_ids: [USERS.alice] },
      }),
    )
    expect(invite.code).toBe('research_incomplete')
    endSession()
    await signIn(USERS.carol) // GREEN admin; GREEN-3 is Shortlisted with one item answered
    const view = await api.GET('/api/v1/ideas/{idea}/proposal', idea('GREEN-3'))
    expect(view.data?.permissions.start_blocked_by_research).toBe(true)
    const start = await rejection(
      api.POST('/api/v1/ideas/{idea}/proposal', { ...idea('GREEN-3'), body: {} }),
    )
    expect(start.problem).toMatchObject({ code: 'research_incomplete', can_override: true })
    const started = await api.POST('/api/v1/ideas/{idea}/proposal', {
      ...idea('GREEN-3'),
      body: { override_research: true },
    })
    // The project's template, Carbon impact included; the idea moved to Proposal.
    expect(started.data?.proposal?.sections.map((s) => s.key)).toContain('carbon_impact')
    expect(started.data?.proposal?.idea.status).toBe('proposal')
    expect(getDb().audit.filter((e) => e.action === 'idea.research_override')).toHaveLength(1)
  })
})

describe('answers', () => {
  it('records who answered and when; owners and admins only; invisible text refused', async () => {
    await signIn(USERS.bob)
    const answered = await api.PUT('/api/v1/ideas/{idea}/research/items/{item_id}', {
      params: { path: { idea: 'TOOL-7', item_id: RESEARCH_ITEMS.toolConsulted } },
      body: { answer: 'Legal (contracts team), 3 Oct: fine if we keep the standard terms' },
    })
    const item = answered.data?.items.find((i) => i.item_id === RESEARCH_ITEMS.toolConsulted)
    expect(item?.answer).toMatchObject({ answered_by: { display_name: 'Bob Chen' } })
    expect(answered.data).toMatchObject({ blocking: false, progress: { required_open: 0 } })
    const invisible = await rejection(
      api.PUT('/api/v1/ideas/{idea}/research/items/{item_id}', {
        params: { path: { idea: 'TOOL-7', item_id: RESEARCH_ITEMS.toolDataProtection } },
        body: { answer: '​' },
      }),
    )
    expect(invisible.status).toBe(422)
    endSession()
    await signIn(USERS.dave) // a TOOL member who doesn't own TOOL-7
    const read = await api.GET('/api/v1/ideas/{idea}/research', idea('TOOL-7'))
    expect(read.data?.permissions).toEqual({ can_answer: false, can_override: false })
    const refused = await rejection(
      api.DELETE('/api/v1/ideas/{idea}/research/items/{item_id}', {
        params: { path: { idea: 'TOOL-7', item_id: RESEARCH_ITEMS.toolElsewhere } },
      }),
    )
    expect(refused.status).toBe(403)
  })

  it('keeps a required answer once the idea is past Research (code review M1)', async () => {
    await signIn(USERS.alice) // a TOOL admin; TOOL-4 is in Proposal, its checklist answered
    const item = (id: string) => ({ params: { path: { idea: 'TOOL-4', item_id: id } } })
    const kept = await rejection(
      api.DELETE(
        '/api/v1/ideas/{idea}/research/items/{item_id}',
        item(RESEARCH_ITEMS.toolConsulted),
      ),
    )
    expect(kept).toMatchObject({ status: 409, code: 'research_answer_required' })
    // Editing it stays allowed; an idea in Research still clears (it re-arms the gate).
    const edited = await api.PUT('/api/v1/ideas/{idea}/research/items/{item_id}', {
      ...item(RESEARCH_ITEMS.toolConsulted),
      body: { answer: 'Security (Raj), 21 Jul: fine with SSO only' },
    })
    expect(edited.error).toBeUndefined()
    const cleared = await api.DELETE('/api/v1/ideas/{idea}/research/items/{item_id}', {
      params: { path: { idea: 'TOOL-7', item_id: RESEARCH_ITEMS.toolElsewhere } },
    })
    expect(cleared.data?.progress.answered).toBe(0)
  })
})

describe('research settings', () => {
  it('refuses moving the step while ideas are in Research, with the count', async () => {
    await signIn(USERS.alice)
    const error = await rejection(
      api.PUT('/api/v1/projects/{slug}/research', {
        params: { path: { slug: 'internal-tools' } },
        body: { step: 'off', items: [] },
      }),
    )
    expect(error).toMatchObject({ status: 409, code: 'ideas_in_research' })
    expect(error.problem).toMatchObject({ idea_count: 2 })
  })

  it('turning the step off keeps the checklist, and on again brings it back', async () => {
    await signIn(USERS.carol)
    const off = await api.PUT('/api/v1/projects/{slug}/research', {
      params: { path: { slug: 'sustainability' } },
      body: { step: 'off', items: [] },
    })
    expect(off.data?.step).toBe('off')
    expect(off.data?.items).toHaveLength(3)
    const project = await api.GET('/api/v1/projects/{slug}', {
      params: { path: { slug: 'sustainability' } },
    })
    expect(project.data?.lifecycle).not.toContain('research')
    const research = await api.GET('/api/v1/ideas/{idea}/research', idea('GREEN-4'))
    expect(research.data).toMatchObject({ step: 'off', items: [], blocking: false })
    // On again with the same ids (the SPA sends the kept checklist back).
    const on = await api.PUT('/api/v1/projects/{slug}/research', {
      params: { path: { slug: 'sustainability' } },
      body: {
        step: 'before_evaluation',
        items: (off.data?.items ?? []).map(({ id, title, hint, required }) => ({
          id,
          title,
          hint,
          required,
        })),
      },
    })
    expect(on.data?.items.map((i) => i.title)).toEqual([
      'Not already being done elsewhere',
      'Departments or teams consulted',
      'Data protection considered',
    ])
  })
})

describe('the proposal template', () => {
  it('keeps keys through renames and reorders, archives sections with text, restores them', async () => {
    await signIn(USERS.alice)
    const path = { params: { path: { slug: 'internal-tools' } } }
    const before = await api.GET('/api/v1/projects/{slug}/proposal-template', path)
    expect(before.data?.sections.map((s) => s.key)).toEqual([
      'summary',
      'problem',
      'solution',
      'effort_rollout',
      'risks',
      'the_ask',
    ])
    const saved = await api.PUT('/api/v1/projects/{slug}/proposal-template', {
      ...path,
      body: {
        sections: [
          { key: 'problem', title: 'The problem', hint: '' },
          { key: 'summary', title: 'Summary', hint: '' },
          { title: 'Effort & rollout plan', hint: 'Who and when' },
        ],
      },
    })
    expect(saved.data?.sections.map((s) => [s.key, s.title])).toEqual([
      ['problem', 'The problem'],
      ['summary', 'Summary'],
      ['effort_rollout_plan', 'Effort & rollout plan'],
    ])
    // Solution, Effort & rollout and Risks have text in TOOL-4's proposal: archived.
    expect(saved.data?.removed_sections.map((s) => s.key).sort()).toEqual([
      'effort_rollout',
      'risks',
      'solution',
    ])
    const proposal = await api.GET('/api/v1/ideas/{idea}/proposal', idea('TOOL-4'))
    expect(proposal.data?.proposal?.sections.map((s) => s.key)).toEqual([
      'problem',
      'summary',
      'effort_rollout_plan',
    ])
    const removedSave = await rejection(
      api.PUT('/api/v1/ideas/{idea}/proposal/sections/{section_key}', {
        params: { path: { idea: 'TOOL-4', section_key: 'risks' } },
        body: { body_md: 'x', base_version: 2 },
      }),
    )
    expect(removedSave.status).toBe(404)
    const thread = await rejection(
      api.POST('/api/v1/ideas/{idea}/proposal/threads', {
        ...idea('TOOL-4'),
        body: { section_key: 'risks', body_md: 'Hello' },
      }),
    )
    expect(thread).toMatchObject({ status: 422, code: 'unknown_section' })
    const restored = await api.PUT('/api/v1/projects/{slug}/proposal-template', {
      ...path,
      body: {
        sections: [
          { key: 'problem', title: 'The problem', hint: '' },
          { key: 'risks', title: 'Risks', hint: '' },
        ],
      },
    })
    expect(restored.data?.sections.map((s) => s.key)).toEqual(['problem', 'risks'])
    const back = await api.GET('/api/v1/ideas/{idea}/proposal', idea('TOOL-4'))
    expect(back.data?.proposal?.sections.find((s) => s.key === 'risks')?.body_md).toMatch(
      /Flags left behind/,
    )
  })

  it('ends the Markdown export with the research appendix while the step is on', async () => {
    await signIn(USERS.alice)
    const response = await fetch('/api/v1/ideas/TOOL-4/proposal/markdown')
    const text = await response.text()
    expect(text).toMatch(/## Effort & rollout/)
    expect(text).not.toMatch(/## Market & users/)
    expect(text).toMatch(/## Research and consultation\n\n### Not already being done elsewhere/)
  })
})

describe('similar ideas', () => {
  it('finds ideas with similar titles or summaries the viewer can see, never held ones', async () => {
    expect(similarity('Service health dashboard', 'Office energy dashboard')).toBeGreaterThan(0.3)
    await signIn(USERS.alice)
    const { data } = await api.GET('/api/v1/ideas/{idea}/similar-ideas', idea('TOOL-7'))
    expect(data?.items.map((i) => i.key)).toEqual(['TOOL-8', 'GREEN-5'])
    const held = getDb().ideas.find((i) => i.held_for)
    expect(data?.items.some((i) => i.id === held?.id)).toBe(false)
    expect(JSON.stringify(data)).not.toMatch(/score/)
  })
})
