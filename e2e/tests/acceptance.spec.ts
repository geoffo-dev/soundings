import type { Page } from '@playwright/test'

import { PEOPLE, uniqueKey, type Person } from './support/api'
import {
  details,
  evaluateSheet,
  expect,
  heading,
  openIdea,
  pickRecommendation,
  pickScore,
  primaryAction,
  SCORE_TEXT,
  switchUserInUi,
  test,
  toast,
} from './support/fixtures'

/**
 * Phase 1 acceptance (SPEC section 13), entirely through the UI against the real
 * stack, switching people with the dev login page:
 *
 * create a project → submit an idea → assign an owner → three evaluators score it
 * blind → the aggregate and the ranking. Test plan: docs/test-plans/phase-1.md (AC-*).
 */

const EVALUATORS = ['carol', 'dave', 'kenji'] as const satisfies readonly Person[]
// Default rubric: Value, Feasibility, Effort (inverted), Strategic fit, Risk (inverted).
const SCORES: Record<(typeof EVALUATORS)[number], Record<string, number>> = {
  carol: { Value: 5, Feasibility: 4, Effort: 2, 'Strategic fit': 5, Risk: 1 },
  dave: { Value: 4, Feasibility: 4, Effort: 3, 'Strategic fit': 4, Risk: 2 },
  kenji: { Value: 2, Feasibility: 3, Effort: 4, 'Strategic fit': 3, Risk: 3 },
}
const RECOMMENDATION = { carol: 'Go', dave: 'Go', kenji: 'Maybe' } as const
// Adjusted means (inverted: 6 − s): Value 11/3, Feasibility 11/3, Effort 3,
// Strategic fit 4, Risk 4 → overall 11/3 = 3.67 → 3.7; Value spreads 2–5 → disagreement.
const OVERALL = '3.7'

/** `YYYY-MM-DD` for today + `days` in the browser's time zone (the date input's format). */
function dateInDays(page: Page, days: number): Promise<string> {
  return page.evaluate((n) => {
    const d = new Date()
    d.setDate(d.getDate() + n)
    const pad = (v: number) => String(v).padStart(2, '0')
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
  }, days)
}

async function addMember(page: Page, person: Person) {
  await page.getByRole('combobox', { name: 'Add a person' }).click()
  await page.getByPlaceholder('Search by name or email…').last().fill(person)
  await page.getByRole('option', { name: new RegExp(PEOPLE[person]) }).click()
  await page.getByRole('button', { name: 'Add', exact: true }).click()
  await expect(toast(page, `${PEOPLE[person]} added as member`)).toBeVisible()
}

test('AC-01…07: project → idea → owner → three blind evaluations → aggregate and ranking', async ({
  page,
  api,
}) => {
  test.slow() // a dozen sign-ins through the login page
  const key = uniqueKey('A')
  const slug = `acceptance-${key.toLowerCase()}`
  const name = `Acceptance ${key}`

  // AC-01: Alice (platform admin) signs in and creates the project from the sidebar.
  await page.goto('/')
  await expect(page).toHaveURL(/\/login\?next=/)
  await switchUserInUi(page, 'alice')
  await page
    .getByRole('navigation', { name: 'Main' })
    .getByRole('button', { name: 'New project' })
    .click()
  const create = page.getByRole('dialog', { name: 'New project' })
  await create.getByRole('textbox', { name: 'Name' }).fill(name)
  await create.getByRole('textbox', { name: 'URL' }).fill(slug)
  await create.getByRole('textbox', { name: 'Idea key' }).fill(key)
  await create.getByRole('button', { name: /Create project/ }).click()
  await expect(page).toHaveURL(new RegExp(`/p/${slug}$`))
  await expect(heading(page, name)).toBeVisible()

  // …and adds the team in the project settings.
  await page.goto(`/p/${slug}/settings?tab=members`)
  for (const person of ['mateo', 'bob', ...EVALUATORS] as const) await addMember(page, person)

  // AC-02: Mateo, a member, submits an idea with "n" from the project page.
  await switchUserInUi(page, 'mateo')
  await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name }).click()
  await expect(heading(page, name)).toBeVisible()
  await page.keyboard.press('n')
  const newIdea = page.getByRole('dialog', { name: 'New idea' })
  await expect(newIdea.getByRole('textbox', { name: 'Title' })).toBeFocused()
  // Mateo can submit to several projects: the picker starts on the one in view.
  await expect(newIdea.getByRole('combobox', { name: 'Project' })).toHaveText(new RegExp(name))
  await page.keyboard.type('Refunds without a phone call')
  await newIdea
    .getByRole('textbox', { name: 'Summary' })
    .fill('Customers start a refund in their account and track it to the bank.')
  await page.keyboard.press('ControlOrMeta+Enter')
  await expect(page).toHaveURL(new RegExp(`/ideas/${key}-1$`))
  await expect(heading(page, 'Refunds without a phone call')).toBeVisible()
  const ideaKey = `${key}-1`

  // Two more ideas give the ranking something to rank (arranged through the API):
  // the runner-up gets one middling evaluation, the third none.
  const mateo = await api('mateo')
  const runnerUp = await mateo.createIdea(slug, {
    title: 'Refund status by SMS',
    summary: 'Text customers when the refund is paid.',
  })
  const unscored = await mateo.createIdea(slug, {
    title: 'Refund kiosk in stores',
    summary: 'A self-service kiosk for in-store refunds.',
  })
  const alice = await api('alice')
  alice.created.push(slug) // archived after the test, like the projects the API creates
  await alice.invite(runnerUp.key, ['carol'])
  await (
    await api('carol')
  ).evaluate(
    runnerUp.key,
    { Value: 3, Feasibility: 3, Effort: 3, 'Strategic fit': 3, Risk: 3 },
    { recommendation: 'maybe' },
  )

  // AC-03: Alice assigns Bob as the owner ("a" on the idea page).
  await switchUserInUi(page, 'alice')
  await openIdea(page, ideaKey)
  await expect(primaryAction(page)).toHaveAccessibleName('Assign owner')
  await page.keyboard.press('a')
  const ownerDialog = page.getByRole('dialog', { name: 'Assign owner' })
  await ownerDialog.getByRole('combobox', { name: 'Owner' }).fill('bob')
  await ownerDialog.getByRole('option', { name: /Bob Brown/ }).click()
  await expect(details(page).getByRole('button', { name: /^Owner: Bob Brown/ })).toBeVisible()

  // AC-04: Bob, the owner, moves it to Evaluating and invites three evaluators with a
  // due date ten days out.
  await switchUserInUi(page, 'bob')
  await openIdea(page, ideaKey)
  await page.keyboard.press('s')
  await page
    .getByRole('dialog', { name: 'Change status' })
    .getByRole('option', { name: 'Evaluating' })
    .click()
  await expect(details(page).getByRole('button', { name: /^Status:/ })).toHaveAccessibleName(
    'Status: Evaluating. Change status',
  )
  await expect(primaryAction(page)).toHaveAccessibleName('Invite evaluators')
  await primaryAction(page).click()
  const invite = page.getByRole('dialog', { name: 'Invite evaluators' })
  for (const person of EVALUATORS) {
    await invite.getByRole('combobox', { name: 'Evaluators' }).fill(person)
    await invite.getByRole('option', { name: new RegExp(PEOPLE[person]) }).click()
  }
  await invite.getByLabel('Due date').fill(await dateInDays(page, 10))
  // The list below updates optimistically: the API is read once the invite is saved.
  const invited = page.waitForResponse(
    (response) =>
      response.url().endsWith(`/api/v1/ideas/${ideaKey}/evaluators`) &&
      response.request().method() === 'POST',
  )
  await invite.getByRole('button', { name: /Invite 3 people/ }).click()
  expect((await invited).status()).toBe(200)
  await expect(invite).toBeHidden()
  const evaluatorList = details(page).getByRole('list', { name: 'Evaluators' })
  await expect(evaluatorList.getByRole('listitem')).toHaveCount(3)
  await expect(evaluatorList.getByRole('img', { name: 'Not submitted yet' })).toHaveCount(3)
  const detail = await (await api('bob')).idea(ideaKey)
  expect(detail.status).toBe('evaluating')
  expect(detail.owner?.display_name).toBe(PEOPLE.bob)
  expect(detail.evaluation_due_at).not.toBeNull()
  const dueInDays = (Date.parse(detail.evaluation_due_at ?? '') - Date.now()) / 86_400_000
  expect(dueInDays).toBeGreaterThan(9)
  expect(dueInDays).toBeLessThan(11)

  // AC-05: each evaluator is blind until they submit, scores in the evaluate sheet,
  // submits, and sees everyone's scores at once.
  const submitted: string[] = []
  for (const person of EVALUATORS) {
    await switchUserInUi(page, person)

    // My work lists the evaluation; its button opens the sheet on the idea.
    const due = page.locator('#evaluations').getByRole('listitem').filter({ hasText: ideaKey })
    await expect(due).toContainText('Refunds without a phone call')
    await expect(due).not.toContainText(SCORE_TEXT)

    await openIdea(page, ideaKey)
    const sidebar = details(page)
    await expect(sidebar.getByText('Hidden until you submit')).toBeVisible()
    await expect(sidebar.getByRole('meter')).toHaveCount(0)
    await expect(sidebar).not.toContainText(SCORE_TEXT)
    await expect(sidebar).not.toContainText('High disagreement')
    // Who has submitted is visible; what they scored is not.
    await expect(
      sidebar.getByRole('img', { name: `${submitted.length} of 3 evaluations submitted` }),
    ).toBeVisible()
    await page.getByRole('tab', { name: /Evaluations/ }).click()
    await expect(page.getByRole('tabpanel')).toContainText('Hidden until you submit')
    await expect(page.getByRole('tabpanel').getByRole('article')).toHaveCount(0)
    // The list agrees: a lock instead of the score.
    await page.goto(`/p/${slug}?view=list`)
    const row = page.getByRole('row').filter({ hasText: ideaKey })
    await expect(
      row.getByRole('img', { name: 'Scores hidden until you submit your evaluation' }),
    ).toBeVisible()
    await expect(row).not.toContainText(SCORE_TEXT)

    await openIdea(page, ideaKey)
    await expect(primaryAction(page)).toHaveAccessibleName('Evaluate')
    await page.keyboard.press('e')
    const sheet = evaluateSheet(page)
    await expect(sheet).toBeVisible()
    for (const [criterion, score] of Object.entries(SCORES[person])) {
      await pickScore(sheet, criterion, score)
    }
    await pickRecommendation(sheet, RECOMMENDATION[person])
    await expect(sheet.getByText('5 of 5 scored')).toBeVisible()
    await sheet.getByRole('button', { name: /^Submit/ }).click()

    const reveal = page.getByRole('dialog', { name: 'Your evaluation' })
    await expect(reveal).toBeVisible()
    await expect(reveal.getByRole('img', { name: /^Your score: \d out of 5$/ })).toHaveCount(5)
    for (const other of submitted) {
      await expect(
        reveal.getByRole('img', { name: new RegExp(`^${other}: \\d out of 5$`) }),
      ).toHaveCount(5)
    }
    const count = submitted.length + 1
    await expect(
      reveal.getByText(`${count} ${count === 1 ? 'evaluation' : 'evaluations'}`),
    ).toBeVisible()
    if (submitted.length === 0) {
      await expect(reveal.getByText('You’re the first to submit.', { exact: false })).toBeVisible()
    }
    await reveal.getByRole('button', { name: 'Done' }).click()
    await expect(reveal).toBeHidden()
    // The blind lifts on the page too, and the evaluation leaves My work.
    await expect(details(page).getByText('Hidden until you submit')).toBeHidden()
    await expect(details(page).getByRole('meter')).toHaveCount(5)
    await expect(primaryAction(page)).toHaveCount(0)
    submitted.push(PEOPLE[person])
  }
  await page.goto('/')
  await expect(page.locator('#evaluations').getByText(ideaKey)).toHaveCount(0)

  // AC-06: Bob, the owner, sees the aggregate, the disagreement and every evaluation.
  await switchUserInUi(page, 'bob')
  await openIdea(page, ideaKey)
  const sidebar = details(page)
  // The overall comes first; Value and Feasibility means are 3.7 too.
  await expect(sidebar.getByText(OVERALL, { exact: true }).first()).toBeVisible()
  await expect(sidebar.getByText('/ 5 · 3 evaluations')).toBeVisible()
  await expect(sidebar.getByText('High disagreement')).toBeVisible()
  await expect(sidebar.getByRole('meter')).toHaveCount(5)
  await expect(sidebar.getByRole('img', { name: '3 of 3 evaluations submitted' })).toBeVisible()
  // Every evaluation is in, so closing evaluation is the owner's next step.
  await expect(primaryAction(page)).toHaveAccessibleName('Close evaluation')
  await page.getByRole('tab', { name: /Evaluations/ }).click()
  await expect(page.getByRole('tabpanel').getByRole('article')).toHaveCount(3)
  for (const person of EVALUATORS) {
    await expect(
      page.getByRole('tabpanel').getByRole('article', { name: PEOPLE[person] }),
    ).toBeVisible()
  }
  const aggregate = (await (await api('bob')).idea(ideaKey)).aggregate
  expect(aggregate).toMatchObject({ overall: 3.7, count: 3, high_disagreement: true })
  expect(aggregate?.recommendations).toEqual({ go: 2, maybe: 1, no: 0 })

  // AC-07: the list sorted by score ranks the ideas; unscored ones come last.
  await page.goto(`/p/${slug}?view=list`)
  await page.getByRole('button', { name: 'Score', exact: true }).click()
  await expect(page).toHaveURL(/sort=-score/)
  const rows = page
    .getByRole('table', { name: 'Ideas' })
    .getByRole('row')
    .filter({ has: page.getByRole('link') })
  await expect(rows).toHaveCount(3)
  await expect(rows.nth(0)).toContainText(ideaKey)
  await expect(
    rows.nth(0).getByRole('img', { name: new RegExp(`^Score ${OVERALL}`) }),
  ).toBeVisible()
  await expect(rows.nth(1)).toContainText(runnerUp.key)
  await expect(rows.nth(1).getByRole('img', { name: /^Score 3\.0/ })).toBeVisible()
  await expect(rows.nth(2)).toContainText(unscored.key)
})

test('AC-08: a member volunteers to own an unowned idea when the project allows it', async ({
  page,
  api,
}) => {
  const alice = await api('alice')
  const key = uniqueKey('V')
  const project = await alice.createProject({
    name: `Volunteers ${key}`,
    slug: `vol-${key.toLowerCase()}`,
    key,
  })
  await alice.addMember(project.slug, 'farah')
  const idea = await alice.createIdea(project.slug, {
    title: 'Quarterly customer panel',
    summary: 'Invite ten customers every quarter to try what we are building.',
  })

  await switchUserInUi(page, 'farah')
  await page.goto(`/ideas/${idea.key}`)
  await expect(primaryAction(page)).toHaveAccessibleName('I’ll own this')
  await primaryAction(page).click()
  await expect(details(page).getByRole('button', { name: /^Owner: Farah Haddad/ })).toBeVisible()
  expect((await alice.idea(idea.key)).owner?.display_name).toBe(PEOPLE.farah)

  // With volunteering switched off, the offer disappears.
  await alice.send('PATCH', `/projects/${project.slug}`, { allow_volunteer_owners: false })
  const second = await alice.createIdea(project.slug, {
    title: 'Customer panel newsletter',
    summary: 'A short monthly note to the panel.',
  })
  await page.goto(`/ideas/${second.key}`)
  await expect(heading(page, 'Customer panel newsletter')).toBeVisible()
  await expect(primaryAction(page)).toHaveCount(0)
  await expect(page.getByRole('button', { name: /I’ll own this/ })).toHaveCount(0)
})
