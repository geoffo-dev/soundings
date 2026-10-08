import type { Locator, Page } from '@playwright/test'

import { Api, uniqueSuffix, userOf, type IdeaDetail, type Project } from './support/api'
import {
  aiTeam,
  registerAgent,
  requestRun,
  retireAgents,
  signInAs,
  skipWithoutAi,
} from './support/ai'
import { expect, heading, openIdea, settled, signIn, test, toast } from './support/fixtures'
import { projectWithPublicForm, Visitor } from './support/public'
import {
  answerItem,
  answerRequired,
  CHECKLIST,
  ideaResearch,
  REQUIRED_ITEMS,
  researchSettings,
  researchTeam,
  setResearchStep,
  similarIdeas,
} from './support/research'

/**
 * Phase 8, the research step (contract-phase8 §3), against the real API and the demo
 * data: turning the step on in project settings (the default checklist), the board's
 * Research column and the cards' checklist progress, the gate dialog when a move is
 * refused (Open research for the owner, "Move anyway" with a reason for an admin,
 * audited), the idea page's Research panel (answers, progress, the primary action),
 * Similar ideas (never a held idea), the settings' lock while ideas are in Research,
 * "Start proposal" and "Invite evaluators" before the gate, and the seeded Internal
 * Tools story. Test plan: RS-*.
 */

const column = (page: Page, label: string) =>
  page.getByRole('region', { name: new RegExp(`^${label}\\b`) })
const card = (scope: Page | Locator, key: string) =>
  scope.getByRole('link', { name: new RegExp(`\\(${key}\\)$`) })
const gate = (page: Page) => page.getByRole('dialog', { name: 'Finish the research first' })
const panel = (page: Page) => page.getByRole('region', { name: 'Research' })
const badge = (scope: Locator, name: string | RegExp) => scope.getByRole('img', { name })

async function openBoard(page: Page, project: Project) {
  await page.goto(`/p/${project.slug}?view=board`)
  await expect(heading(page, project.name)).toBeVisible()
  await settled(page)
}

/**
 * Picks the card up with the keyboard and drops it `steps` columns to the right, waiting
 * for the drag library's announcements between keys (as board.spec.ts does).
 */
async function moveRight(page: Page, key: string, steps: number) {
  const announcer = page.locator('[id^="DndLiveRegion"]')
  await card(page, key).focus()
  await page.keyboard.press('Space')
  await expect(announcer).toContainText(`Picked up ${key}`)
  for (let i = 0; i < steps; i += 1) await page.keyboard.press('ArrowRight')
  await expect(announcer).toContainText(`${key} is over`)
  await page.keyboard.press('Space')
}

/** A project with the step before evaluation, and an idea Bob owns, in Research. */
async function inResearch(alice: Api, name: string) {
  const project = await researchTeam(alice, name, 'before_evaluation', {
    bob: 'member',
    carol: 'member',
    erin: 'viewer',
  })
  const idea = await alice.createIdea(project.slug, {
    title: `Gift wrapping at the till ${uniqueSuffix()}`,
    summary: 'Wrap presents at the till in December, for a small charge.',
  })
  await alice.setOwner(idea.key, 'bob')
  await alice.changeStatus(idea.key, 'research')
  return { project, idea }
}

test.describe('RS-01: project settings', () => {
  test('an admin turns the step on with the default checklist; the board gains the column', async ({
    page,
    api,
  }) => {
    const alice = await api('alice')
    const project = await researchTeam(alice, 'Research settings', 'off', { bob: 'member' })
    await signIn(page, 'alice')
    await page.goto(`/p/${project.slug}/settings?tab=research`)
    await expect(page.getByRole('heading', { name: 'Research step' })).toBeVisible()
    await expect(page.getByRole('radio', { name: 'Off' })).toBeChecked()
    await expect(page.getByRole('list', { name: 'Checklist items' })).toHaveCount(0)

    await page.getByRole('radio', { name: 'Before evaluation' }).check()
    await expect(page.getByText('We filled in the default checklist')).toBeVisible()
    const items = page.getByRole('list', { name: 'Checklist items' }).getByRole('listitem')
    await expect(items).toHaveCount(3)
    await page.getByRole('button', { name: 'Save research step' }).click()
    await expect(toast(page, 'Research step saved')).toBeVisible()

    const saved = await researchSettings(alice, project.slug)
    expect(saved.step).toBe('before_evaluation')
    expect(saved.items.map((item) => [item.title, item.required])).toEqual([
      [CHECKLIST.elsewhere, true],
      [CHECKLIST.consulted, true],
      [CHECKLIST.privacy, false],
    ])
    expect((await alice.project(project.slug)).lifecycle).toEqual([
      'new',
      'research',
      'evaluating',
      'shortlisted',
      'proposal',
      'closed',
    ])
    const [entry] = await alice.audit({
      action: 'project.research_step_change',
      project_id: project.id,
    })
    expect(entry?.details).toMatchObject({ from: 'off', to: 'before_evaluation' })

    // The board: Research between New and Evaluating.
    await alice.createIdea(project.slug, { title: 'A first idea', summary: 'To fill the board.' })
    await openBoard(page, project)
    const x = async (label: string) => (await column(page, label).boundingBox())?.x ?? 0
    expect(await x('New')).toBeLessThan(await x('Research'))
    expect(await x('Research')).toBeLessThan(await x('Evaluating'))
  })

  test('a member reads the step and checklist without changing them', async ({ page, api }) => {
    const alice = await api('alice')
    const project = await researchTeam(alice, 'Research read', 'before_proposal', {
      bob: 'member',
    })
    await signIn(page, 'bob')
    await page.goto(`/p/${project.slug}/settings?tab=research`)
    await expect(page.getByText('Only project admins can change these settings.')).toBeVisible()
    await expect(page.getByText(CHECKLIST.consulted)).toBeVisible()
    await expect(page.getByRole('radio')).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Save research step' })).toHaveCount(0)
  })

  test('RS-07: the step is locked while ideas are in Research', async ({ page, api }) => {
    const alice = await api('alice')
    const { project } = await inResearch(alice, 'Research lock')
    await signIn(page, 'alice')
    await page.goto(`/p/${project.slug}/settings?tab=research`)
    // One quiet line under the choice, not a warning above the checklist (UX review M3).
    await expect(page.getByText('Can’t change while 1 idea is in Research')).toBeVisible()
    await expect(page.getByRole('alert')).toHaveCount(0)
    await expect(page.getByRole('radio', { name: 'Off' })).toBeDisabled()
    await expect(page.getByRole('radio', { name: 'Before proposal' })).toBeDisabled()
    // The API refuses it too, with the count.
    const response = await alice.raw('PUT', `/projects/${project.slug}/research`, {
      step: 'off',
      items: [],
    })
    expect(response.status()).toBe(409)
    expect(await response.json()).toMatchObject({ code: 'ideas_in_research', idea_count: 1 })
    // "Show them": the board filtered on Research.
    await page.getByRole('link', { name: /Show them/ }).click()
    await expect(page).toHaveURL(/status=research/)
  })
})

test.describe('RS-02: the board', () => {
  test('cards show checklist progress; a refused move snaps back and explains', async ({
    page,
    api,
  }) => {
    const alice = await api('alice')
    const { project, idea } = await inResearch(alice, 'Research board')
    const fresh = await alice.createIdea(project.slug, {
      title: 'Self-checkout for flowers',
      summary: 'A flower stand customers pay at themselves.',
    })
    await alice.setOwner(fresh.key, 'bob')
    await signIn(page, 'bob')
    await openBoard(page, project)
    const research = column(page, 'Research')
    await expect(card(research, idea.key)).toBeVisible()
    await expect(
      badge(card(research, idea.key), 'Research 0 of 3 answered, 2 required items open'),
    ).toBeVisible()
    await expect(card(research, idea.key).getByText('2 open')).toBeVisible()
    // New is the status before Research: no badge there until something is answered
    // (UX review m1).
    await expect(card(column(page, 'New'), fresh.key)).toBeVisible()
    await expect(badge(card(column(page, 'New'), fresh.key), /^Research/)).toHaveCount(0)

    // The owner drags it to Evaluating: refused, the dialog names the open items.
    await moveRight(page, idea.key, 1)
    await expect(gate(page)).toBeVisible()
    await expect(gate(page)).toContainText(`${idea.key} can’t move to Evaluating`)
    const open = gate(page).getByRole('list', { name: 'Open research items' })
    await expect(open.getByRole('listitem')).toHaveText(REQUIRED_ITEMS)
    await expect(gate(page).getByRole('button', { name: /anyway/ })).toHaveCount(0)
    await page.keyboard.press('Escape')
    await expect(gate(page)).toHaveCount(0)
    await expect(card(column(page, 'Research'), idea.key)).toBeFocused()
    expect((await alice.idea(idea.key)).status).toBe('research')

    // Open research: the idea page, focused on the first open item.
    await moveRight(page, idea.key, 1)
    await gate(page).getByRole('button', { name: 'Open research' }).click()
    await expect(page).toHaveURL(new RegExp(`/ideas/${idea.key}#research$`))
    await expect(page.getByRole('textbox', { name: CHECKLIST.elsewhere })).toBeFocused()
  })

  test('RS-04: an admin moves it anyway, with a reason in the audit log', async ({ page, api }) => {
    const alice = await api('alice')
    const { project, idea } = await inResearch(alice, 'Research override')
    await signIn(page, 'alice')
    await openBoard(page, project)
    await moveRight(page, idea.key, 1)
    await expect(gate(page)).toBeVisible()
    await expect(gate(page)).toContainText('As an admin you can go ahead anyway')
    await gate(page).getByRole('button', { name: 'Move anyway…' }).click()
    const reason = gate(page).getByRole('textbox', { name: 'Reason (optional)' })
    await expect(reason).toBeFocused()
    await reason.fill('Legal agreed on a call; notes to follow')
    await gate(page).getByRole('button', { name: 'Move anyway', exact: true }).click()
    await expect(gate(page)).toHaveCount(0)
    await expect(card(column(page, 'Evaluating'), idea.key)).toBeVisible()
    await expect(toast(page, `${idea.key} moved to Evaluating`)).toBeVisible()

    const current = await alice.idea(idea.key)
    expect(current.status).toBe('evaluating')
    const [entry] = await alice.audit({ action: 'idea.research_override', target_id: current.id })
    expect(entry?.details).toMatchObject({
      operation: 'change_idea_status',
      from_status: 'research',
      to_status: 'evaluating',
      open_items: 2,
      reason: 'Legal agreed on a call; notes to follow',
    })
    // The feed says so.
    await page.goto(`/ideas/${idea.key}`)
    await expect(page.getByText(/to Evaluating without finishing research/)).toBeVisible()
  })

  test('the list filters on Research', async ({ page, api }) => {
    const alice = await api('alice')
    const { project, idea } = await inResearch(alice, 'Research list')
    await alice.createIdea(project.slug, { title: 'Still new', summary: 'Not in Research.' })
    await signIn(page, 'alice')
    await page.goto(`/p/${project.slug}?view=list&status=research`)
    const rows = page
      .getByRole('table', { name: 'Ideas' })
      .getByRole('row')
      .filter({ has: page.getByRole('link') })
    await expect(rows).toHaveCount(1)
    await expect(rows.first()).toContainText(idea.key)
  })
})

test.describe('RS-03: the idea page', () => {
  test('the owner answers the checklist, then starts evaluation', async ({ page, api }) => {
    const alice = await api('alice')
    const { idea } = await inResearch(alice, 'Research answers')
    await signIn(page, 'bob')
    await page.goto(`/ideas/${idea.key}`)
    const research = panel(page)
    await expect(research).toContainText('0 of 3 answered')
    await expect(research).toContainText('2 required items left before Evaluating')
    await expect(page.getByRole('button', { name: 'Finish research' }).first()).toBeVisible()

    await page.getByRole('button', { name: 'Finish research' }).first().click()
    const first = page.getByRole('textbox', { name: CHECKLIST.elsewhere })
    await expect(first).toBeFocused()
    // The hint is a line under the title, read with the field (UX review m3).
    await expect(first).toHaveAccessibleDescription(/Search Soundings and ask around/)
    await first.fill('Searched Soundings and asked store ops: nobody wraps gifts at the till.')
    await research.getByRole('button', { name: 'Save answer' }).click()
    await expect(first).toBeFocused()
    await expect(research).toContainText('1 of 3 answered')

    const second = page.getByRole('textbox', { name: CHECKLIST.consulted })
    await second.fill('Legal (contracts team), 3 Oct: fine if we keep the standard terms')
    await research.getByRole('button', { name: 'Save answer' }).click()
    await expect(research).toContainText('Research complete')
    await expect(research).toContainText('Answered by Bob Brown')

    // The API agrees, and nothing blocks now.
    const saved = await ideaResearch(alice, idea.key)
    expect(saved.progress).toEqual({ answered: 2, total: 3, required_open: 0 })
    expect(saved.blocking).toBe(false)
    expect(saved.items[1]?.answer?.answer).toBe(
      'Legal (contracts team), 3 Oct: fine if we keep the standard terms',
    )

    // Evaluation needs evaluators: Start evaluation invites them, and the invite moves
    // the idea on (UX review p7).
    await page.getByRole('button', { name: 'Start evaluation' }).first().click()
    const invite = page.getByRole('dialog', { name: 'Invite evaluators' })
    await expect(invite).toContainText(`moves ${idea.key} to Evaluating`)
    await invite.getByRole('option', { name: /Carol/ }).click()
    await invite.getByRole('button', { name: 'Invite', exact: true }).click()
    await expect(toast(page, 'Invited')).toContainText(`${idea.key} moves to Evaluating`)
    await expect.poll(async () => (await alice.idea(idea.key)).status).toBe('evaluating')
    expect((await alice.idea(idea.key)).evaluators.map((row) => row.user.display_name)).toEqual([
      expect.stringMatching(/^Carol/),
    ])
    expect(await alice.audit({ action: 'idea.research_override', target_id: idea.id })).toEqual([])
  })

  test('members and viewers read the answers; only the owner and admins write', async ({
    page,
    api,
  }) => {
    const alice = await api('alice')
    const { idea } = await inResearch(alice, 'Research readers')
    const bob = await api('bob')
    await answerItem(bob, idea.key, CHECKLIST.elsewhere, 'Nothing like it on Soundings.')
    for (const person of ['carol', 'erin'] as const) {
      await signIn(page, person)
      await page.goto(`/ideas/${idea.key}`)
      await expect(panel(page)).toContainText('Nothing like it on Soundings.')
      await expect(panel(page)).toContainText('Not answered yet')
      await expect(panel(page).getByRole('textbox')).toHaveCount(0)
      await expect(panel(page).getByRole('button', { name: /^Clear/ })).toHaveCount(0)
    }
    const carol = await api('carol')
    const response = await carol.raw(
      'PUT',
      `/ideas/${idea.key}/research/items/${(await ideaResearch(bob, idea.key)).items[1]?.item_id}`,
      { answer: 'Me too' },
    )
    expect(response.status()).toBe(403)
  })

  test('clearing an answer can be undone', async ({ page, api }) => {
    const alice = await api('alice')
    const { idea } = await inResearch(alice, 'Research clear')
    const bob = await api('bob')
    await answerItem(bob, idea.key, CHECKLIST.elsewhere, 'Nothing like it on Soundings.')
    await signIn(page, 'bob')
    await page.goto(`/ideas/${idea.key}`)
    await expect(panel(page)).toContainText('1 of 3 answered')
    await panel(page)
      .getByRole('button', { name: `Clear the answer to ${CHECKLIST.elsewhere}` })
      .click()
    await expect(panel(page)).toContainText('0 of 3 answered')
    await toast(page, 'cleared').getByRole('button', { name: 'Undo' }).click()
    await expect(panel(page)).toContainText('1 of 3 answered')
    await expect
      .poll(async () => (await ideaResearch(bob, idea.key)).items[0]?.answer?.answer)
      .toBe('Nothing like it on Soundings.')
  })
})

test.describe('RS-05: Similar ideas', () => {
  test('finds a similar idea in another project, never a held one', async ({ page, api }) => {
    const alice = await api('alice')
    const { project } = await inResearch(alice, 'Research similar')
    // The demo's public form holds "Repair café in the flagship store" for moderation.
    const held = (await alice.moderationQueue('customer-innovation')).items.find(
      (item) => item.title === 'Repair café in the flagship store',
    )
    expect(held, 'the seeded idea held for moderation').toBeTruthy()
    const mine = await alice.createIdea(project.slug, {
      title: 'Repair café in the flagship store on Saturdays',
      summary: 'Once a month, volunteers help customers fix small appliances and clothes.',
    })
    // An idea everyone can see, in Customer Innovation (internal).
    const visible = await alice.createIdea('customer-innovation', {
      title: `Repair café for customers ${uniqueSuffix()}`,
      summary: 'Once a month, volunteers help customers fix small appliances and clothes.',
    })
    const found = await similarIdeas(alice, mine.key)
    expect(found.items.map((item) => item.key)).toContain(visible.key)
    expect(found.items.map((item) => item.key)).not.toContain(held?.key)

    await signIn(page, 'alice')
    await page.goto(`/ideas/${mine.key}`)
    const research = panel(page)
    await expect(research.getByRole('heading', { name: 'Similar ideas' })).toBeVisible()
    await expect(research.getByRole('link', { name: new RegExp(visible.key) })).toBeVisible()
    await expect(
      research.getByText('Repair café in the flagship store', { exact: true }),
    ).toHaveCount(0)
    await expect(research.getByRole('link', { name: new RegExp(`${held?.key}\\b`) })).toHaveCount(0)
  })

  test('says so when nothing is similar', async ({ page, api }) => {
    const alice = await api('alice')
    const project = await researchTeam(alice, 'Research empty', 'before_evaluation', {})
    const word = uniqueSuffix()
    const idea = await alice.createIdea(project.slug, {
      title: `Qx${word} zebra tuning`,
      summary: `Vv${word} yodel kiosk.`,
    })
    await signIn(page, 'alice')
    await page.goto(`/ideas/${idea.key}`)
    await expect(panel(page)).toContainText('No similar ideas found in the projects you can see')
  })

  test('the seeded TOOLS-11 finds CUST-14', async ({ page }) => {
    await signIn(page, 'carol')
    await page.goto('/ideas/TOOLS-11')
    const research = panel(page)
    await expect(research).toContainText('Research complete')
    await expect(research.getByRole('link', { name: /CUST-14/ })).toBeVisible()
  })
})

test.describe('RS-06: before the gate, elsewhere', () => {
  test('Start proposal waits for the research before the proposal; an admin starts it anyway', async ({
    page,
    api,
  }) => {
    const alice = await api('alice')
    const project = await researchTeam(alice, 'Research proposal', 'before_proposal', {
      bob: 'member',
    })
    const idea = await alice.createIdea(project.slug, {
      title: 'Refill station for cleaning products',
      summary: 'Customers bring bottles back and refill them in store.',
    })
    await alice.setOwner(idea.key, 'bob')
    await alice.changeStatus(idea.key, 'shortlisted')
    expect((await alice.proposal(idea.key)).permissions.start_blocked_by_research).toBe(true)

    // The owner (a member) is sent to the research instead.
    await signIn(page, 'bob')
    await page.goto(`/ideas/${idea.key}?tab=proposal`)
    await expect(page.getByText('Finish the research checklist first')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Start proposal' })).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Open research' }).first()).toBeVisible()

    // An admin starts it anyway after confirming.
    await signIn(page, 'alice')
    await page.goto(`/ideas/${idea.key}?tab=proposal`)
    await page.getByRole('button', { name: 'Start proposal' }).click()
    await expect(gate(page)).toBeVisible()
    await expect(gate(page)).toContainText('Starting the proposal moves')
    await gate(page).getByRole('button', { name: 'Start anyway…' }).click()
    await gate(page).getByRole('button', { name: 'Start anyway', exact: true }).click()
    await expect(page.getByRole('heading', { level: 2, name: /Problem$/ })).toBeVisible()
    await expect.poll(async () => (await alice.idea(idea.key)).status).toBe('proposal')
    const [entry] = await alice.audit({ action: 'idea.research_override', target_id: idea.id })
    expect(entry?.details).toMatchObject({
      operation: 'create_proposal',
      from_status: 'shortlisted',
      to_status: 'proposal',
    })
  })

  test('Invite evaluators explains the wait; an admin invites anyway', async ({ page, api }) => {
    const alice = await api('alice')
    const project = await researchTeam(alice, 'Research invite', 'before_evaluation', {
      bob: 'member',
      carol: 'member',
    })
    const idea: IdeaDetail = await alice.createIdea(project.slug, {
      title: 'Price checker app for staff',
      summary: 'Scan a shelf label to see the till price.',
    })
    await alice.setOwner(idea.key, 'bob')
    expect((await alice.idea(idea.key)).permissions.invite_blocked_by_research).toBe(true)

    // The owner (a member) is pointed at the research instead of the invite.
    await signIn(page, 'bob')
    await page.goto(`/ideas/${idea.key}`)
    await expect(
      page.getByText(/Finish the research checklist before inviting evaluators/),
    ).toBeVisible()
    await expect(page.getByRole('button', { name: 'Invite evaluators' })).toHaveCount(0)
    // The API refuses the owner's first invite the same way.
    const bob = await api('bob')
    const carol = await userOf(alice.baseURL, 'carol')
    const refused = await bob.raw('POST', `/ideas/${idea.key}/evaluators`, {
      user_ids: [carol.id],
    })
    expect(refused.status()).toBe(409)
    expect(await refused.json()).toMatchObject({ code: 'research_incomplete', can_override: false })

    // An admin keeps the button, is warned in the dialog, and invites anyway.
    await signIn(page, 'alice')
    await page.goto(`/ideas/${idea.key}`)
    await expect(
      page.getByText('Finish the research checklist first (admins can invite anyway).'),
    ).toBeVisible()
    await page.getByRole('button', { name: 'Invite evaluators' }).click()
    const invite = page.getByRole('dialog', { name: 'Invite evaluators' })
    await expect(invite).toContainText('As an admin you can invite anyway')
    await invite.getByRole('combobox', { name: 'Evaluators' }).fill('Carol')
    await invite.getByRole('option', { name: /Carol Chen/ }).click()
    await invite.getByRole('button', { name: 'Invite', exact: true }).click()
    await expect(gate(page)).toBeVisible()
    await expect(gate(page)).toContainText('Inviting the first evaluator starts evaluation')
    await gate(page).getByRole('button', { name: 'Invite anyway…' }).click()
    await gate(page).getByRole('button', { name: 'Invite anyway', exact: true }).click()
    await expect(gate(page)).toHaveCount(0)
    await expect.poll(async () => (await alice.idea(idea.key)).evaluator_progress.total).toBe(1)
    const [entry] = await alice.audit({ action: 'idea.research_override', target_id: idea.id })
    expect(entry?.details).toMatchObject({ operation: 'add_evaluators', open_items: 2 })
  })

  test('turning the step off hides Research everywhere and keeps the answers', async ({
    page,
    api,
  }) => {
    const alice = await api('alice')
    const { project, idea } = await inResearch(alice, 'Research off')
    const bob = await api('bob')
    await answerRequired(bob, idea.key)
    await bob.changeStatus(idea.key, 'evaluating')
    await setResearchStep(alice, project.slug, 'off')
    await signIn(page, 'bob')
    await openBoard(page, project)
    await expect(column(page, 'Research')).toHaveCount(0)
    await page.goto(`/ideas/${idea.key}`)
    await expect(heading(page, idea.title)).toBeVisible()
    await expect(panel(page)).toHaveCount(0)
    // On again: the answers are still there.
    await setResearchStep(alice, project.slug, 'before_evaluation')
    expect((await ideaResearch(bob, idea.key)).progress.answered).toBe(2)
  })
})

test.describe('RS-10: public tracking', () => {
  test('a submitter never sees Research: it reads as the status before it', async ({
    page,
    api,
    baseURL,
  }) => {
    const alice = await api('alice')
    const project = await projectWithPublicForm(alice, 'Gate tracking', { bob: 'member' })
    await setResearchStep(alice, project.slug, 'before_proposal')
    const visitor = await Visitor.open(baseURL ?? '')
    const receipt = await visitor.submitted(project.slug, {
      title: 'Refill station for cleaning products',
      summary: 'Bring your bottles back and refill them in store.',
    })
    const [queued] = (await alice.moderationQueue(project.slug)).items
    const key = queued?.key ?? ''
    await alice.approve(key)
    await alice.setOwner(key, 'bob')
    await alice.changeStatus(key, 'evaluating')
    await alice.changeStatus(key, 'shortlisted')
    await alice.changeStatus(key, 'research')
    expect((await alice.idea(key)).status).toBe('research')

    // Research comes after Shortlisted here: the submitter still reads Shortlisted, and
    // the move into Research adds nothing to their history.
    const tracked = await visitor.tracked(receipt.tracking_token)
    await visitor.dispose()
    expect(tracked.status).toBe('shortlisted')
    expect(tracked.history.map((entry) => entry.status)).not.toContain('research')
    expect(tracked.history.at(-1)?.status).toBe('shortlisted')
    await page.goto(`/track#${receipt.tracking_token}`)
    await expect(page.getByText('Refill station for cleaning products')).toBeVisible()
    await expect(page.getByText(/Shortlisted/).first()).toBeVisible()
    await expect(page.getByText(/Research/)).toHaveCount(0)
  })

  test('before evaluation, an idea in Research reads as with the team (New)', async ({
    api,
    baseURL,
  }) => {
    const alice = await api('alice')
    const project = await projectWithPublicForm(alice, 'Gate tracking new', { bob: 'member' })
    await setResearchStep(alice, project.slug, 'before_evaluation')
    const visitor = await Visitor.open(baseURL ?? '')
    const receipt = await visitor.submitted(project.slug, {
      title: 'Water fountains by the tills',
      summary: 'Free drinking water for customers.',
    })
    const [queued] = (await alice.moderationQueue(project.slug)).items
    const key = queued?.key ?? ''
    await alice.approve(key)
    await alice.changeStatus(key, 'research')
    const before = await visitor.tracked(receipt.tracking_token)
    expect(before.status).toBe('new')
    expect(before.reached_team_at).not.toBeNull()
    expect(before.history.map((entry) => entry.status)).not.toContain('research')
    // On to Evaluating (answered), then back to Research: the submitter reads New again.
    await answerRequired(alice, key)
    await alice.changeStatus(key, 'evaluating')
    await alice.changeStatus(key, 'research')
    const after = await visitor.tracked(receipt.tracking_token)
    await visitor.dispose()
    expect(after.status).toBe('new')
    expect(after.history.map((entry) => entry.status)).toEqual(
      expect.not.arrayContaining(['research']),
    )
    expect(after.history.at(-1)?.status).toBe('new')
  })
})

test.describe('RS-08: the demo story', () => {
  test('Internal Tools: TOOLS-11 complete, TOOLS-12 refused for its owner', async ({
    page,
    api,
  }) => {
    await signIn(page, 'sven')
    await page.goto('/p/internal-tools?view=board')
    await expect(heading(page, 'Internal Tools')).toBeVisible()
    const research = column(page, 'Research')
    await expect(
      badge(card(research, 'TOOLS-11'), 'Research 3 of 3 answered, complete'),
    ).toBeVisible()
    await expect(
      badge(card(research, 'TOOLS-12'), 'Research 1 of 3 answered, 1 required item open'),
    ).toBeVisible()
    // Past Research: no badge.
    await expect(
      column(page, 'Evaluating').getByRole('img', { name: /^Research \d of/ }),
    ).toHaveCount(0)
    await moveRight(page, 'TOOLS-12', 1)
    await expect(gate(page)).toBeVisible()
    await expect(gate(page).getByRole('list', { name: 'Open research items' })).toHaveText(
      CHECKLIST.consulted,
    )
    await page.keyboard.press('Escape')
    const sven = await api('sven')
    expect((await sven.idea('TOOLS-12')).status).toBe('research')
  })
})

test.describe('@ai RS-09: Ask AI to evaluate waits for the research', () => {
  test.beforeEach(skipWithoutAi)

  test('the owner is told why; an admin asks anyway, audited', async ({ page, api }) => {
    const alice = await api('alice')
    const team = await aiTeam(alice, 'AI research gate')
    await setResearchStep(alice, team.project.slug, 'before_evaluation')
    const idea = await alice.createIdea(team.project.slug, {
      title: `Locker pickup for staff ${uniqueSuffix()}`,
      summary: 'Staff collect their own online orders from a locker in the break room.',
    })
    await alice.setOwnerUser(idea.key, team.owner.me)
    const agent = await registerAgent(alice, {
      projectIds: [team.project.id],
      purposes: ['evaluate'],
    })
    try {
      // The owner's request is refused (it would be the first evaluator).
      const refused = await requestRun(team.owner, idea.key, 'evaluate', agent.agent.id)
      expect(refused.status()).toBe(409)
      expect(await refused.json()).toMatchObject({
        code: 'research_incomplete',
        can_override: false,
      })
      await signInAs(page, team.owner.me)
      await openIdea(page, idea.key)
      await page.getByRole('button', { name: 'AI actions' }).first().click()
      await expect(page.getByRole('menu')).toContainText('Finish the research checklist first')
      await page.keyboard.press('Escape')

      // An admin asks anyway after confirming; the run starts.
      await signIn(page, 'alice')
      await openIdea(page, idea.key)
      await page.getByRole('button', { name: 'AI actions' }).first().click()
      await page.getByRole('menuitem', { name: /Ask AI to evaluate/ }).click()
      await expect(gate(page)).toBeVisible()
      await expect(gate(page)).toContainText('Asking AI to evaluate starts evaluation')
      await gate(page).getByRole('button', { name: 'Ask anyway…' }).click()
      await gate(page).getByRole('button', { name: 'Ask anyway', exact: true }).click()
      await expect(gate(page)).toHaveCount(0)
      await expect(
        page
          .getByRole('button', { name: /AI run (in progress|waiting to start)\. View progress/ })
          .first(),
      ).toBeVisible()
      const [entry] = await alice.audit({ action: 'idea.research_override', target_id: idea.id })
      expect(entry?.details).toMatchObject({
        operation: 'request_ai_evaluation',
        from_status: 'new',
        to_status: 'new',
        open_items: 2,
      })
    } finally {
      await retireAgents(alice, [agent])
      await team.dispose()
    }
  })
})
