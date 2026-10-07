import type { Page } from '@playwright/test'

import { createTeamProject, defaultRubricScores, type Person } from './support/api'
import {
  details,
  expect,
  heading,
  openIdea,
  primaryAction,
  SCORE_TEXT,
  signIn,
  test,
} from './support/fixtures'

/**
 * Blind evaluation (role matrix §3, contract §3.7): a pending evaluator sees no score
 * data for that idea anywhere — list, board, idea page, evaluations, My work, search —
 * and no API response the SPA receives carries it either. Test plan: BL-*.
 *
 * Seeded story: CUST-11 "WhatsApp order updates" (owner Bob) has two submitted
 * evaluations (Kenji, Zanele: aggregate 3.4 with high disagreement) and two pending
 * evaluators: Alice (platform admin and project admin, so no role lifts the blind) and
 * Amara (a plain member). Alice also has a draft on TOOLS-9.
 */

const BLIND_KEY = 'CUST-11'
const BLIND_TITLE = 'WhatsApp order updates'
// The submitted evaluators' private comments on CUST-11 (seed content).
const PRIVATE_COMMENTS = [
  'Customers in Spain and Brazil would love this.',
  'Big privacy review and a new vendor',
]

interface Captured {
  url: string
  body: unknown
}

/**
 * Records every JSON response from the API while the page is used. The SPA may hide
 * data it received; these checks make sure it never receives it.
 */
function captureApi(page: Page) {
  const pending: Promise<Captured | null>[] = []
  page.on('response', (response) => {
    const url = response.url()
    if (!url.includes('/api/v1/')) return
    if (!(response.headers()['content-type'] ?? '').includes('json')) return
    pending.push(
      response
        .json()
        .then((body: unknown) => ({ url, body }))
        .catch(() => null),
    )
  })
  return async () => (await Promise.all(pending)).filter((c): c is Captured => c !== null)
}

/** Every object in `value` (depth first). */
function* objects(value: unknown): Generator<Record<string, unknown>> {
  if (Array.isArray(value)) {
    for (const item of value) yield* objects(item)
  } else if (value && typeof value === 'object') {
    const record = value as Record<string, unknown>
    yield record
    for (const item of Object.values(record)) yield* objects(item)
  }
}

/** Asserts that no captured response reveals score data about `key`. */
function expectNoScoreData(captured: Captured[], key: string, ideaId: string) {
  expect(captured.length).toBeGreaterThan(0)
  let seen = 0
  for (const { url, body } of captured) {
    const text = JSON.stringify(body)
    for (const comment of PRIVATE_COMMENTS) expect(text, url).not.toContain(comment)
    if (
      /\/ideas\/[^/?]+\/evaluations(\?|$)/.test(url) &&
      (url.includes(key) || url.includes(ideaId))
    ) {
      expect(body, url).toEqual({ items: [], score_hidden: true })
    }
    for (const object of objects(body)) {
      if (object.key !== key && object.id !== ideaId) continue
      seen += 1
      if ('score' in object) expect(object.score, `${url} score`).toBeNull()
      if ('score_hidden' in object) expect(object.score_hidden, `${url} score_hidden`).toBe(true)
      if ('high_disagreement' in object) {
        expect(object.high_disagreement, `${url} high_disagreement`).toBe(false)
      }
      if ('aggregate' in object) expect(object.aggregate, `${url} aggregate`).toBeNull()
      if ('aggregate_score' in object) expect(object.aggregate_score, url).toBeNull()
    }
  }
  expect(seen, `the pages loaded ${key} at least once`).toBeGreaterThan(0)
}

const lock = 'Scores hidden until you submit your evaluation'
const listRows = (page: Page) =>
  page
    .getByRole('table', { name: 'Ideas' })
    .getByRole('row')
    .filter({ has: page.getByRole('link') })

for (const person of ['alice', 'amara'] as const satisfies readonly Person[]) {
  test.describe(`${person}, a pending evaluator of ${BLIND_KEY}`, () => {
    test.beforeEach(async ({ page }) => {
      await signIn(page, person)
    })

    test('BL-01…06: sees no score on any surface, and the API sends none', async ({
      page,
      api,
    }) => {
      const ideaId = (await (await api('bob')).idea(BLIND_KEY)).id
      const responses = captureApi(page)

      // BL-04 My work: the evaluation is due; nothing about its score.
      await page.goto('/')
      const due = page.locator('#evaluations').getByRole('listitem').filter({ hasText: BLIND_KEY })
      await expect(due).toContainText(BLIND_TITLE)
      await expect(
        due.getByRole('link', { name: new RegExp(`^Evaluate ${BLIND_KEY}`) }),
      ).toBeVisible()
      for (const row of await page.getByRole('listitem').filter({ hasText: BLIND_KEY }).all()) {
        await expect(row).not.toContainText(SCORE_TEXT)
      }

      // BL-01 List (default order, then by score).
      await page.goto('/p/customer-innovation?view=list')
      const row = listRows(page).filter({ hasText: BLIND_KEY })
      await expect(row.getByRole('img', { name: lock })).toBeVisible()
      await expect(row).not.toContainText(SCORE_TEXT)
      await expect(row.getByRole('img', { name: 'High disagreement' })).toHaveCount(0)

      // BL-02 Board.
      await page.goto('/p/customer-innovation?view=board')
      const card = page.getByRole('link', { name: new RegExp(`\\(${BLIND_KEY}\\)$`) })
      await expect(card.getByRole('img', { name: lock })).toBeVisible()
      await expect(card).not.toContainText(SCORE_TEXT)
      await expect(card.getByRole('img', { name: 'High disagreement' })).toHaveCount(0)

      // BL-03 Idea page: overview, sidebar and the Evaluations tab.
      await openIdea(page, BLIND_KEY)
      await expect(heading(page, BLIND_TITLE)).toBeVisible()
      const sidebar = details(page)
      await expect(sidebar.getByText('Hidden until you submit')).toBeVisible()
      await expect(sidebar.getByRole('meter')).toHaveCount(0)
      await expect(sidebar).not.toContainText('High disagreement')
      await expect(page.locator('main')).not.toContainText(SCORE_TEXT)
      // Submission progress is not score data: it stays visible.
      await expect(sidebar.getByRole('img', { name: '2 of 4 evaluations submitted' })).toBeVisible()
      await page.getByRole('tab', { name: /Evaluations/ }).click()
      const panel = page.getByRole('tabpanel')
      await expect(panel).toContainText('Hidden until you submit')
      await expect(panel.getByRole('article')).toHaveCount(0)
      await expect(page.locator('main')).not.toContainText(SCORE_TEXT)

      // BL-05 Command palette search.
      await page.keyboard.press('ControlOrMeta+k')
      const palette = page.getByRole('dialog', { name: 'Command palette' })
      await expect(palette.getByRole('combobox')).toBeFocused()
      await page.keyboard.type('whatsapp')
      const option = palette.getByRole('option', { name: new RegExp(BLIND_TITLE) })
      await expect(option).toBeVisible()
      await expect(option).not.toContainText(SCORE_TEXT)
      await page.keyboard.press('Escape')

      // BL-06 Nothing the SPA received for CUST-11 carries score data.
      expectNoScoreData(await responses(), BLIND_KEY, ideaId)
    })

    test('BL-08/09: sorting by score and the disagreement filter treat it as unscored', async ({
      page,
    }) => {
      await page.goto('/p/customer-innovation?view=list&sort=-score')
      await expect(listRows(page).first()).toBeVisible()
      const labels = await listRows(page).evaluateAll((rows) =>
        rows.map((row) => ({
          key: /[A-Z]+-\d+/.exec(row.textContent ?? '')?.[0] ?? '',
          scored: Boolean(row.querySelector('[aria-label^="Score "]')),
        })),
      )
      const position = labels.findIndex((row) => row.key === BLIND_KEY)
      expect(position).toBeGreaterThan(-1)
      // Every idea with a visible score sorts before it.
      expect(labels.slice(position).every((row) => !row.scored)).toBe(true)
      expect(labels.slice(0, position).some((row) => row.scored)).toBe(true)

      await page.goto('/p/customer-innovation?view=list&high_disagreement=1')
      await expect(listRows(page).filter({ hasText: 'CUST-8' })).toHaveCount(1)
      await expect(listRows(page).filter({ hasText: BLIND_KEY })).toHaveCount(0)
      await page.goto('/p/customer-innovation?view=board&high_disagreement=1')
      await expect(page.getByRole('link', { name: /\(CUST-8\)$/ })).toBeVisible()
      await expect(page.getByRole('link', { name: new RegExp(`\\(${BLIND_KEY}\\)$`) })).toHaveCount(
        0,
      )
    })
  })
}

test('BL-07: a saved draft does not lift the blind', async ({ page, api }) => {
  // Alice has a draft on TOOLS-9; Dave and Sven have submitted.
  await signIn(page, 'alice')
  const ideaId = (await (await api('carol')).idea('TOOLS-9')).id
  const responses = captureApi(page)
  await openIdea(page, 'TOOLS-9')
  await expect(primaryAction(page)).toHaveAccessibleName('Continue evaluation')
  await expect(details(page).getByText('Hidden until you submit')).toBeVisible()
  await expect(page.locator('main')).not.toContainText(SCORE_TEXT)
  await page.getByRole('tab', { name: /Evaluations/ }).click()
  await expect(page.getByRole('tabpanel').getByRole('article')).toHaveCount(0)
  expectNoScoreData(await responses(), 'TOOLS-9', ideaId)
})

test('BL-10: control — the owner sees the same idea’s score and flag', async ({ page }) => {
  // Proves the checks above would notice a score: Bob owns CUST-11 and evaluates nothing.
  await signIn(page, 'bob')
  await openIdea(page, BLIND_KEY)
  await expect(details(page).getByText('3.4', { exact: true }).first()).toBeVisible()
  await expect(details(page).getByText('High disagreement')).toBeVisible()
  await page.goto('/p/customer-innovation?view=list&high_disagreement=1')
  await expect(listRows(page).filter({ hasText: BLIND_KEY })).toHaveCount(1)
  await expect(
    listRows(page)
      .filter({ hasText: BLIND_KEY })
      .getByRole('img', { name: /^Score 3\.4/ }),
  ).toBeVisible()
})

test('BL-11: closing evaluation keeps a pending evaluator blind', async ({ page, api }) => {
  const alice = await api('alice')
  const project = await createTeamProject(alice, 'Blind close', {
    bob: 'member',
    carol: 'member',
    dave: 'member',
    erin: 'member',
  })
  const idea = await alice.createIdea(project.slug, {
    title: 'Evening delivery slots',
    summary: 'Deliver between 6 and 10 pm in big cities.',
  })
  await alice.setOwner(idea.key, 'bob')
  const bob = await api('bob')
  await bob.invite(idea.key, ['carol', 'dave', 'erin'])
  await (
    await api('carol')
  ).evaluate(idea.key, defaultRubricScores(5, 4, 2, 5, 1), {
    recommendation: 'go',
  })
  await (
    await api('dave')
  ).evaluate(idea.key, defaultRubricScores(2, 3, 4, 3, 3), {
    recommendation: 'no',
  })
  await bob.send('POST', `/ideas/${idea.key}/evaluation/close`)

  await signIn(page, 'erin')
  const responses = captureApi(page)
  await openIdea(page, idea.key)
  await expect(details(page).getByText('Hidden until you submit')).toBeVisible()
  await expect(details(page)).toContainText('Evaluation closed before you submitted')
  await expect(page.locator('main')).not.toContainText(SCORE_TEXT)
  await page.goto(`/p/${project.slug}?view=list`)
  await expect(
    listRows(page).filter({ hasText: idea.key }).getByRole('img', { name: lock }),
  ).toBeVisible()
  expectNoScoreData(await responses(), idea.key, idea.id)
})
