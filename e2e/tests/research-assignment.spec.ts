import type { Locator, Page } from '@playwright/test'

import { daysFromNow } from './support/api'
import {
  disposePeople,
  emailCount,
  emailTo,
  expectNoScoreData,
  links,
  Mailpit,
  newPeople,
  outboxSettled,
  signInAs,
  visibleText,
} from './support/email'
import {
  bestPracticeViolations,
  details,
  expect,
  heading,
  SCORE_TEXT,
  seriousViolations,
  signIn,
  test,
  toast,
} from './support/fixtures'
import {
  answerItem,
  answerRequired,
  assignResearcher,
  CHECKLIST,
  GUEST_EMAIL_LINE,
  ideaResearch,
  PRIVATE_PROJECT_LINE,
  researchTeam,
  researchToDo,
} from './support/research'

/**
 * Phase 8b, assigning the research to a person (contract-phase8b §10, test plan
 * docs/test-plans/phase-8b.md, RA-*), on the real stack. Specs that assign use a private
 * project of their own (`researchTeam`) and new people (`newPeople`: their own inbox and
 * mailbox); RA-03 and RA-06 read the seeded story without changing it: bob researches
 * TOOLS-12 (the private Internal Tools, where he has no role) as its guest, due in three
 * days, asked by dave; alice's GREEN-5 research is overdue.
 */

const researcherLine = (page: Page) => page.getByTestId('researcher-line')
const breadcrumb = (page: Page) => page.getByRole('navigation', { name: 'Breadcrumb' })
const nav = (page: Page) => page.getByRole('navigation', { name: 'Main' })
const card = (scope: Page | Locator, key: string) =>
  scope.getByRole('link', { name: new RegExp(`\\(${key}\\)$`) })

async function openIdea(page: Page, key: string) {
  await page.goto(`/ideas/${key}`)
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
  await expect(researcherLine(page)).toBeVisible()
}

const escaped = (text: string) => text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

async function emailWorks(api: { notificationSummary(): Promise<{ email_available: boolean }> }) {
  return (await api.notificationSummary()).email_available && (await new Mailpit().isUp())
}

test('RA-01 an admin asks someone outside the private project: marked, explained, told, and their guest view', async ({
  page,
  api,
}) => {
  const alice = await api('alice')
  const people = await newPeople(alice, ['nora'])
  const { nora } = people
  try {
    const project = await researchTeam(alice, 'Outside research', 'before_evaluation', {
      carol: 'member',
    })
    const idea = await alice.createIdea(project.slug, {
      title: `Badge reader for the bike shed ${project.key}`,
      summary: 'Open the bike shed with the staff badge instead of a shared key.',
    })
    await alice.setOwner(idea.key, 'carol')
    await alice.changeStatus(idea.key, 'research')

    await signIn(page, 'alice')
    await openIdea(page, idea.key)
    await expect(researcherLine(page)).toContainText('Carol Chen (owner)')
    const change = researcherLine(page).getByRole('button', {
      name: 'Change researcher or due date',
    })
    await change.click()
    const dialog = page.getByRole('dialog', { name: 'Who does the research' })
    const search = dialog.getByRole('combobox', { name: 'Researcher' })
    await expect(search).toHaveAttribute('placeholder', 'Search everyone…')
    await search.fill(nora.email)
    // Her row (the search goes to the server; every run has a Nora Quinn of its own).
    await dialog
      .getByRole('option', {
        name: new RegExp(`Nora Quinn.*Not in this project · ${escaped(nora.email)}`),
      })
      .click()
    await expect(dialog).toContainText('Chosen: Nora Quinn · Not in this project')
    await expect(dialog.getByRole('status')).toHaveText(PRIVATE_PROJECT_LINE)
    await dialog.getByRole('button', { name: 'In a week' }).click()
    const since = new Date()
    await dialog.getByRole('button', { name: /^Save/ }).click()
    await expect(dialog).toHaveCount(0)
    await expect(toast(page, 'Nora Quinn will do the research')).toBeVisible()
    await expect(researcherLine(page)).toContainText('Nora Quinn')
    await expect(researcherLine(page)).toContainText('not in this project')
    await expect(researcherLine(page)).toContainText('due')
    await expect(change).toBeFocused()
    await expect(page.getByText('Alice Anders asked Nora Quinn to research')).toBeVisible()
    const research = await ideaResearch(alice, idea.key)
    expect(research.assignment.researcher?.id).toBe(nora.user.id)
    expect(research.assignment.researcher_in_project).toBe(false)
    expect(research.assignment.due_at).not.toBeNull()

    // "Asked to research" by email, with the guest line and the Research link.
    if (await emailWorks(alice)) {
      const message = await emailTo(nora, `[${idea.key}] Please research`, since)
      expect(message.Text).toContain(GUEST_EMAIL_LINE)
      expect(links(message).some((href) => href.endsWith(`/ideas/${idea.key}?research=1`))).toBe(
        true,
      )
      const visible = visibleText(message.HTML).replaceAll('’', "'")
      expectNoScoreData(
        'asked to research',
        message.Subject,
        message.Text.replace(GUEST_EMAIL_LINE, ''),
        visible.replace(GUEST_EMAIL_LINE, ''),
      )
    }

    // Nora's own browser: the idea as its guest, nothing of the project.
    await signInAs(page, nora)
    await page.goto('/')
    const row = page
      .getByRole('region', { name: /Research to do/ })
      .getByRole('listitem')
      .filter({ hasText: idea.key })
    await expect(row).toContainText(project.name)
    await expect(row.getByRole('link', { name: project.name })).toHaveCount(0)
    await expect(row.getByRole('img', { name: /2 required items open/ })).toHaveText('2 open')
    await expect(nav(page).getByRole('link', { name: project.name })).toHaveCount(0)
    await row
      .getByRole('link', { name: new RegExp(`^Answer the research checklist of ${idea.key}`) })
      .click()
    await expect(heading(page, idea.title)).toBeVisible()
    await expect(
      page.getByText('You can see this idea because you’re researching it.'),
    ).toBeVisible()
    await expect(breadcrumb(page).getByText(project.name)).toBeVisible()
    await expect(breadcrumb(page).getByRole('link', { name: project.name })).toHaveCount(0)
    await expect(page.getByRole('tab')).toHaveCount(0)
    await expect(page.getByRole('textbox', { name: CHECKLIST.elsewhere })).toBeFocused()
    await page.goto(`/p/${project.slug}`)
    await expect(
      page.getByRole('heading', { name: 'This project doesn’t exist or you don’t have access' }),
    ).toBeVisible()
  } finally {
    await disposePeople(people)
  }
})

test('RA-02 an admin removes the researcher by choosing the owner in Change: told who loses the idea', async ({
  page,
  api,
}) => {
  const alice = await api('alice')
  const people = await newPeople(alice, ['nora'])
  const { nora } = people
  try {
    const project = await researchTeam(alice, 'Remove research', 'before_evaluation', {
      carol: 'member',
    })
    const idea = await alice.createIdea(project.slug, {
      title: `Visitor wifi vouchers ${project.key}`,
      summary: 'Print a voucher at reception.',
    })
    await alice.setOwner(idea.key, 'carol')
    await assignResearcher(alice, idea.key, nora.user, daysFromNow(5))

    await signIn(page, 'alice')
    await openIdea(page, idea.key)
    // One path (UX review S2): no separate Remove, nor its Undo.
    await expect(researcherLine(page).getByRole('button', { name: /Remove/ })).toHaveCount(0)
    const change = researcherLine(page).getByRole('button', {
      name: 'Change researcher or due date',
    })
    await change.click()
    const dialog = page.getByRole('dialog', { name: 'Who does the research' })
    await dialog.getByRole('option', { name: /Carol Chen \(owner\)/ }).click()
    await expect(dialog.getByRole('status')).toHaveText(
      `Nora Quinn will no longer see ${idea.key}.`,
    )
    await dialog.getByRole('button', { name: /^Save/ }).click()
    await expect(dialog).toHaveCount(0)
    await expect(toast(page, 'Carol Chen (owner) will do the research')).toBeVisible()
    await expect(researcherLine(page)).toContainText('Carol Chen (owner)')
    await expect(change).toBeFocused()
    await expect
      .poll(async () => (await ideaResearch(alice, idea.key)).assignment.researcher)
      .toBeNull()
    // The due date stays as it was.
    expect((await ideaResearch(alice, idea.key)).assignment.due_at).not.toBeNull()
  } finally {
    await disposePeople(people)
  }
})

test('RA-03 the guest researcher (bob on TOOLS-12) sees that one idea: no scores, no proposal, no project links', async ({
  page,
  api,
}) => {
  await signIn(page, 'bob')
  await page.goto('/ideas/TOOLS-12')
  await expect(heading(page, 'Chat command to request system access')).toBeVisible()
  await expect(page.getByText('You can see this idea because you’re researching it.')).toBeVisible()
  await expect(breadcrumb(page).getByText('Internal Tools')).toBeVisible()
  await expect(breadcrumb(page).getByRole('link', { name: 'Internal Tools' })).toHaveCount(0)
  // No dead tabs, no evaluation area, no score, no AI, no status menu.
  await expect(page.getByRole('tab')).toHaveCount(0)
  const aside = details(page)
  await expect(aside.getByText('Evaluators')).toHaveCount(0)
  await expect(aside.getByText('Score', { exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'AI actions' })).toHaveCount(0)
  await expect(aside.getByRole('button', { name: /^Status/ })).toHaveCount(0)
  await expect(page.locator('main')).not.toContainText(SCORE_TEXT)
  // Who does it: you, with the due date; "Hand back". Never "not in this project" about
  // yourself: the line above says why you see it (UX review p2).
  await expect(researcherLine(page)).toContainText(/Research:.*You/)
  await expect(researcherLine(page)).not.toContainText('not in this project')
  await expect(researcherLine(page)).toContainText('due')
  await expect(researcherLine(page).getByRole('button', { name: 'Hand back' })).toBeVisible()
  await expect(researcherLine(page).getByRole('button', { name: /Change/ })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Answer the checklist' })).toBeVisible()
  await expect(page.getByText('Dave Davies asked Bob Brown to research')).toBeVisible()
  expect(await seriousViolations(page)).toEqual([])
  expect(await bestPracticeViolations(page)).toEqual([])

  // The sidebar has no Internal Tools; ⌘K finds the idea, never the project.
  await expect(nav(page).getByRole('link', { name: 'Internal Tools' })).toHaveCount(0)
  await expect(nav(page).getByRole('link', { name: /^Research, \d+ to do/ })).toBeVisible()
  await page.keyboard.press('ControlOrMeta+k')
  const palette = page.getByRole('dialog', { name: 'Command palette' })
  await expect(palette.getByRole('combobox')).toBeFocused()
  await page.keyboard.type('Chat command')
  await expect(palette.getByRole('option', { name: /TOOLS-12/ })).toBeVisible()
  await expect(palette.getByRole('option', { name: /^Internal Tools/ })).toHaveCount(0)
  await page.keyboard.press('Escape')

  // The project and its other ideas are not found; nothing leaks through the API either.
  await page.goto('/p/internal-tools')
  await expect(
    page.getByRole('heading', { name: 'This project doesn’t exist or you don’t have access' }),
  ).toBeVisible()
  await page.goto('/ideas/TOOLS-11')
  await expect(
    page.getByRole('heading', { name: 'This idea doesn’t exist or you don’t have access' }),
  ).toBeVisible()
  const bob = await api('bob')
  for (const path of [
    '/ideas/TOOLS-12/evaluations',
    '/ideas/TOOLS-12/proposal',
    '/ideas/TOOLS-12/proposal/markdown',
    '/ideas/TOOLS-12/ai-runs',
    '/projects/internal-tools',
    '/projects/internal-tools/board',
  ]) {
    expect((await bob.raw('GET', path)).status(), path).toBe(404)
  }

  // My work: the idea, its project as text.
  await page.goto('/')
  const row = page
    .getByRole('region', { name: /Research to do/ })
    .getByRole('listitem')
    .filter({ hasText: 'TOOLS-12' })
  await expect(row).toContainText('Internal Tools')
  await expect(row.getByRole('link', { name: 'Internal Tools' })).toHaveCount(0)
  await expect(row.getByRole('img', { name: /1 required item open/ })).toHaveText('1 open')
  await expect(row).toContainText(/Due /)
})

test('RA-04 the guest answers the checklist, then hands it back: off to My work, the idea gone', async ({
  page,
  api,
}) => {
  const alice = await api('alice')
  const people = await newPeople(alice, ['nora'])
  const { nora } = people
  try {
    const project = await researchTeam(alice, 'Hand back', 'before_evaluation', {})
    const idea = await alice.createIdea(project.slug, {
      title: `Standing desks on the third floor ${project.key}`,
      summary: 'Six standing desks by the windows.',
    })
    await alice.setOwner(idea.key, 'alice')
    await alice.changeStatus(idea.key, 'research')
    await assignResearcher(alice, idea.key, nora.user, daysFromNow(3))

    await signInAs(page, nora)
    await openIdea(page, idea.key)
    await page.getByRole('button', { name: 'Answer the checklist' }).click()
    const answer = page.getByRole('textbox', { name: CHECKLIST.elsewhere })
    await expect(answer).toBeFocused()
    await answer.fill('Facilities have no plans for the third floor.')
    await page.keyboard.press('ControlOrMeta+Enter')
    await expect(page.getByText('Answered by Nora Quinn')).toBeVisible()
    await expect(answer).toBeFocused()
    expect((await researchToDo(nora.api)).map((item) => item.idea.key)).toContain(idea.key)

    await researcherLine(page).getByRole('button', { name: 'Hand back' }).click()
    const confirm = page.getByRole('alertdialog', {
      name: `Hand back the research of ${idea.key}?`,
    })
    await expect(confirm).toContainText(`You’ll no longer see ${idea.key}`)
    await confirm.getByRole('button', { name: 'Hand back' }).click()
    await expect(page).toHaveURL(/\/$/)
    await expect(toast(page, 'You handed the research back')).toBeVisible()
    await expect(heading(page, 'My work')).toBeVisible()
    await expect(page.locator('main')).not.toContainText(idea.key)
    // The idea's history entry was replaced: Back never lands on it (UX review p6).
    await page.goBack()
    await expect(page).not.toHaveURL(new RegExp(`/ideas/${idea.key}$`))
    await page.goto(`/ideas/${idea.key}`)
    await expect(
      page.getByRole('heading', { name: 'This idea doesn’t exist or you don’t have access' }),
    ).toBeVisible()
    await expect(page.locator('main')).not.toContainText(idea.title)
    // The owner does it again; Nora's answer stays with her name.
    const research = await ideaResearch(alice, idea.key)
    expect(research.assignment.researcher).toBeNull()
    expect(research.items[0]?.answer?.answered_by?.id).toBe(nora.user.id)
  } finally {
    await disposePeople(people)
  }
})

test('RA-05 “Start research”: who does it and by when, then into Research; a plain owner names only members', async ({
  page,
  api,
}) => {
  const alice = await api('alice')
  const project = await researchTeam(alice, 'Start research', 'before_evaluation', {
    carol: 'member',
    kenji: 'member',
  })
  const idea = await alice.createIdea(project.slug, {
    title: `Bike repair stand ${project.key}`,
    summary: 'A repair stand and a pump by the bike shed.',
  })
  await alice.setOwner(idea.key, 'carol')

  await signIn(page, 'carol')
  await openIdea(page, idea.key)
  await page.getByRole('button', { name: 'Start research' }).first().click()
  const dialog = page.getByRole('dialog', { name: 'Start research' })
  await expect(dialog).toContainText(`${idea.key} moves to Research.`)
  await expect(dialog).toContainText('Chosen: You (owner)')
  const search = dialog.getByRole('combobox', { name: 'Researcher' })
  // A plain owner of a private project may name only its people (c25).
  await expect(search).toHaveAttribute('placeholder', 'Search the project’s people…')
  await expect(dialog).toContainText('Only a project admin can ask someone outside this project.')
  await search.fill('erin')
  await expect(dialog).toContainText('No one in this project matches “erin”.')
  await search.fill('kenji')
  await dialog.getByRole('option', { name: /Kenji Watanabe.*Member/ }).click()
  await expect(dialog).toContainText('Chosen: Kenji Watanabe')
  await dialog.getByRole('button', { name: 'In 2 weeks' }).click()
  expect(await seriousViolations(page)).toEqual([])
  await dialog.getByRole('button', { name: /^Start research/ }).click()
  await expect(dialog).toHaveCount(0)
  await expect(toast(page, `${idea.key} moved to Research`)).toHaveCount(1)
  // The toast says who does it and by when (UX review m4).
  await expect(toast(page, `${idea.key} moved to Research`)).toContainText(
    /Kenji Watanabe does the research · due /,
  )
  await expect(details(page).getByText('Research', { exact: true }).first()).toBeVisible()
  await expect(researcherLine(page)).toContainText('Kenji Watanabe')
  const detail = await alice.idea(idea.key)
  expect(detail.status).toBe('research')
  expect(detail.researcher?.display_name).toBe('Kenji Watanabe')
  expect(detail.research_due_at).not.toBeNull()
  // Kenji is told; it is in his My work.
  const kenji = await api('kenji')
  const asked = (await kenji.notifications()).filter(
    (item) => item.type === 'researcher_assigned' && item.idea.key === idea.key,
  )
  expect(asked).toHaveLength(1)
  expect((await researchToDo(kenji)).map((item) => item.idea.key)).toContain(idea.key)
})

test('RA-06 the board: Research cards show who researches them', async ({ page }) => {
  await signIn(page, 'dave')
  await page.goto('/p/internal-tools?view=board')
  const research = page.getByRole('region', { name: /^Research\b/ })
  const tools12 = card(research, 'TOOLS-12')
  await expect(tools12.getByRole('img', { name: 'Researched by Bob Brown' })).toBeVisible()
  // In the card's description: its name stays "Title (KEY)".
  await expect(tools12).toHaveAccessibleDescription(/Researched by Bob Brown/)
  // The owner researching it shows no avatar (TOOLS-11: nobody assigned).
  await expect(card(research, 'TOOLS-11').getByRole('img', { name: /^Researched by/ })).toHaveCount(
    0,
  )
  expect(await seriousViolations(page)).toEqual([])
})

test('RA-07 My work’s “Research to do”: overdue first, the open items, the sidebar badge', async ({
  page,
}) => {
  await signIn(page, 'alice')
  await page.goto('/')
  const section = page.getByRole('region', { name: /Research to do/ })
  await expect(section).toBeVisible()
  const first = section.getByRole('listitem').first()
  await expect(first).toContainText('GREEN-5')
  await expect(first).toContainText(/Overdue \d+ days?/)
  await expect(first.getByRole('img', { name: /2 required items open/ })).toHaveText('2 open')
  await expect(first.getByRole('link', { name: 'Sustainability' })).toBeVisible()
  await expect(
    nav(page).getByRole('link', { name: /^Research, \d+ to do, \d+ overdue$/ }),
  ).toBeVisible()
  expect(await seriousViolations(page)).toEqual([])
  expect(await bestPracticeViolations(page)).toEqual([])
  await first.getByRole('link', { name: /^Answer the research checklist of GREEN-5/ }).click()
  await expect(page).toHaveURL(/\/ideas\/GREEN-5/)
  await expect(page.getByRole('textbox', { name: CHECKLIST.elsewhere })).toBeFocused()
})

test('RA-08 notification preferences: “Asked to research” off sends no email (the inbox still has it); immediate does', async ({
  page,
  api,
}) => {
  const alice = await api('alice')
  const people = await newPeople(alice, ['nora'])
  const { nora } = people
  try {
    const project = await researchTeam(alice, 'Research prefs', 'before_evaluation', {})
    const quiet = await alice.createIdea(project.slug, {
      title: `Quiet room booking ${project.key}`,
      summary: 'Book the quiet room from the calendar.',
    })
    const loud = await alice.createIdea(project.slug, {
      title: `Loud room booking ${project.key}`,
      summary: 'Book the band room from the calendar.',
    })

    await signInAs(page, nora)
    await page.goto('/settings/notifications')
    await expect(page.getByRole('radiogroup')).toHaveCount(9)
    const row = (label: string) => page.getByRole('radiogroup', { name: label, exact: true })
    for (const label of ['Asked to research', 'Research reminders']) {
      await expect(row(label).getByRole('radio', { name: 'Immediate' })).toBeChecked()
    }
    await row('Asked to research').getByRole('radio', { name: 'Off' }).click()
    await expect(page.getByRole('status').filter({ hasText: 'Saved' })).toBeVisible()
    const saved = await nora.api.preferences()
    expect(saved.items.find((item) => item.type === 'researcher_assigned')?.mode).toBe('off')

    const since = new Date()
    await assignResearcher(alice, quiet.key, nora.user, daysFromNow(4))
    const inbox = await nora.api.notifications()
    expect(
      inbox.filter((item) => item.type === 'researcher_assigned' && item.idea.key === quiet.key),
    ).toHaveLength(1)
    if (await emailWorks(alice)) {
      await outboxSettled(alice)
      expect(await emailCount(nora, since, `[${quiet.key}]`)).toBe(0)
    }

    // The inbox page words it.
    await page.goto('/notifications')
    await expect(page.locator('main')).toContainText(/Alice Anders asked you to research/)

    // Immediate again: the next assignment is emailed.
    await page.goto('/settings/notifications')
    await row('Asked to research').getByRole('radio', { name: 'Immediate' }).click()
    await expect(page.getByRole('status').filter({ hasText: 'Saved' })).toBeVisible()
    await assignResearcher(alice, loud.key, nora.user, null)
    if (await emailWorks(alice)) {
      const message = await emailTo(nora, `[${loud.key}] Please research`, since)
      expect(message.Subject).toBe(`[${loud.key}] Please research "${loud.title}"`)
      expect(message.Text).toContain(GUEST_EMAIL_LINE)
    }
  } finally {
    await disposePeople(people)
  }
})

test('RA-09 Restore puts a removed checklist item and template section back where they were', async ({
  page,
  api,
}) => {
  const alice = await api('alice')
  // Removing archives only what something refers to (an answer, a section's text).
  const research = await researchTeam(alice, 'Restore', 'before_evaluation', {})
  const answered = await alice.createIdea(research.slug, {
    title: `Lockers for cyclists ${research.key}`,
    summary: 'Twenty lockers by the showers.',
  })
  await alice.setOwner(answered.key, 'alice')
  await alice.changeStatus(answered.key, 'research')
  await answerItem(alice, answered.key, CHECKLIST.consulted, 'Facilities and the cycling club.')
  const templated = await researchTeam(alice, 'Restore template', 'off', {})
  const drafted = await alice.createIdea(templated.slug, {
    title: `Showers on every floor ${templated.key}`,
    summary: 'Two showers per floor.',
  })
  await alice.setOwner(drafted.key, 'alice')
  await alice.changeStatus(drafted.key, 'shortlisted')
  await alice.startProposal(drafted.key)
  await alice.writeSections(drafted.key, { solution: 'Use the empty store rooms.' })
  await signIn(page, 'alice')

  await page.goto(`/p/${research.slug}/settings?tab=research`)
  const items = page.getByRole('list', { name: 'Checklist items' }).getByRole('listitem')
  await expect(items).toHaveCount(3)
  await page.getByRole('button', { name: `Remove ${CHECKLIST.consulted}` }).click()
  await page.getByRole('button', { name: 'Save research step' }).click()
  await expect(page.getByRole('heading', { name: 'Removed items' })).toBeVisible()
  await expect(items).toHaveCount(2)
  // Another visit: only the server's position knows where it was.
  await page.reload()
  await page.getByRole('button', { name: `Restore ${CHECKLIST.consulted}` }).click()
  await expect(items).toHaveCount(3)
  await expect(items.nth(1).getByRole('textbox', { name: 'Title' })).toHaveValue(
    CHECKLIST.consulted,
  )

  await page.goto(`/p/${templated.slug}/settings?tab=proposal-template`)
  const sections = page.getByRole('list', { name: 'Sections' }).getByRole('listitem')
  await expect(sections).toHaveCount(8)
  await page.getByRole('button', { name: 'Remove Solution' }).click()
  await page.getByRole('button', { name: 'Save template' }).click()
  await expect(toast(page, 'Proposal template saved')).toBeVisible()
  await expect(sections).toHaveCount(7)
  await page.reload()
  await page.getByRole('button', { name: 'Restore Solution' }).click()
  await expect(sections).toHaveCount(8)
  await expect(sections.nth(2).getByRole('textbox', { name: 'Title' })).toHaveValue('Solution')
})

test('RA-10 reassigned while the page is open: the guest’s next action says their research ended, nothing stale', async ({
  page,
  api,
}) => {
  // P8B-QA-F1 (fixed): a write refused with 404 re-checks the idea, and the page drops it
  // (contract-phase8b §4.6, §10). UX review m5/M3: having had the page, the guest is told
  // their research ended (nothing they hadn't seen), and focus goes to that heading.
  const alice = await api('alice')
  const people = await newPeople(alice, ['nora', 'theo'])
  const { nora, theo } = people
  try {
    const project = await researchTeam(alice, 'Reassigned', 'before_evaluation', {})
    const idea = await alice.createIdea(project.slug, {
      title: `Coffee machine on the fourth floor ${project.key}`,
      summary: 'A second coffee machine by the lifts.',
    })
    await alice.setOwner(idea.key, 'alice')
    await alice.changeStatus(idea.key, 'research')
    await assignResearcher(alice, idea.key, nora.user, null)

    await signInAs(page, nora)
    await openIdea(page, idea.key)
    const answer = page.getByRole('textbox', { name: CHECKLIST.elsewhere })
    await expect(answer).toBeVisible()
    // Meanwhile the owner asks someone else.
    await assignResearcher(alice, idea.key, theo.user, null)
    await answer.fill('Nobody else is doing this.')
    await page.keyboard.press('ControlOrMeta+Enter')
    // The server refuses it (404) and the page leaves the idea: nothing of it stays.
    const ended = page.getByRole('heading', {
      level: 1,
      name: `You’re no longer researching ${idea.key}`,
    })
    await expect(ended).toBeVisible()
    await expect(ended).toBeFocused()
    await expect(page.getByText('What you typed is kept on this device.')).toBeVisible()
    await expect(page.locator('main')).not.toContainText(idea.title)
    // Nothing was saved under her name.
    const research = await ideaResearch(alice, idea.key)
    expect(research.items.every((item) => item.answer === null)).toBe(true)
    expect((await nora.api.raw('GET', `/ideas/${idea.key}`)).status()).toBe(404)
  } finally {
    await disposePeople(people)
  }
})

test('RA-11 the team can @mention the outside researcher; the guest’s own picker offers only the people on the idea', async ({
  page,
}) => {
  const composer = page.getByRole('textbox', { name: 'Write a comment' })
  const picker = page.getByRole('listbox', { name: 'People to mention' })
  // Sven (TOOLS-12's owner): the members' picker plus the idea's researcher, labelled so,
  // and a line that the guest reads the comments (guest review L3).
  await signIn(page, 'sven')
  await page.goto('/ideas/TOOLS-12')
  await expect(
    page.getByText('Bob Brown (researching, not in this project) can read comments.'),
  ).toBeVisible()
  await composer.click()
  await page.keyboard.type('@Bo')
  await expect(picker.getByRole('option', { name: /Bob Brown/ })).toContainText('researcher')
  await page.keyboard.press('Escape')
  await composer.fill('')
  // Bob, its guest: the owner and whoever acted in the feed, never the directory (UX
  // review M2: someone who can't see the idea would be notified of nothing). Nothing is
  // posted here.
  await signIn(page, 'bob')
  await page.goto('/ideas/TOOLS-12')
  await composer.click()
  await page.keyboard.type('@Sv')
  await expect(page.getByText('Mention someone on this idea')).toBeVisible()
  await expect(picker.getByRole('option', { name: /Sven Lindqvist/ })).toBeVisible()
  await page.keyboard.press('Escape')
  await composer.fill('')
  await page.keyboard.type('@Farah')
  await expect(picker).toContainText('No one on this idea matches “Farah”')
  await page.keyboard.press('Escape')
  await composer.fill('')
})

test('RA-12 past Research the guest reads the answers but no longer changes them (lead decision D1)', async ({
  page,
  api,
}) => {
  const alice = await api('alice')
  const people = await newPeople(alice, ['nora'])
  const { nora } = people
  try {
    const project = await researchTeam(alice, 'Research done', 'before_evaluation', {})
    const idea = await alice.createIdea(project.slug, {
      title: `Quiet room on the fourth floor ${project.key}`,
      summary: 'Turn the small meeting room into a quiet room.',
    })
    await alice.setOwner(idea.key, 'alice')
    await alice.changeStatus(idea.key, 'research')
    await assignResearcher(alice, idea.key, nora.user, daysFromNow(3))
    await answerItem(nora.api, idea.key, CHECKLIST.elsewhere, 'Facilities: nothing planned.')
    const research = await answerRequired(alice, idea.key)
    await alice.changeStatus(idea.key, 'evaluating')

    await signInAs(page, nora)
    await page.goto(`/ideas/${idea.key}`)
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
    // Past Research the panel starts folded for her (she has nothing left to do there).
    const panel = page.getByRole('region', { name: 'Research' })
    await panel.getByRole('button', { name: 'Research', exact: true }).click()
    await expect(
      panel.getByText(
        'The idea has moved past Research, so only its owner or an admin can change these answers now.',
      ),
    ).toBeVisible()
    await expect(page.getByText('Facilities: nothing planned.')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Answer the checklist' })).toHaveCount(0)
    await expect(page.getByRole('textbox', { name: CHECKLIST.elsewhere })).toHaveCount(0)
    await expect(researcherLine(page).getByRole('button', { name: 'Hand back' })).toBeVisible()
    expect(await seriousViolations(page)).toEqual([])
    // The API says the same: 409 research_finished for her, the owner still edits.
    const item = research.items.find((candidate) => candidate.title === CHECKLIST.elsewhere)
    if (!item) throw new Error('no checklist item')
    const refused = await nora.api.raw('PUT', `/ideas/${idea.key}/research/items/${item.item_id}`, {
      answer: 'Rewritten after the move.',
    })
    expect(refused.status()).toBe(409)
    expect((await refused.json()).code).toBe('research_finished')
    expect((await ideaResearch(nora.api, idea.key)).permissions.can_answer).toBe(false)
    await answerItem(alice, idea.key, CHECKLIST.elsewhere, 'Facilities, 9 Oct: still nothing.')
  } finally {
    await disposePeople(people)
  }
})

test('RA-13 making an internal project private asks first, then ends outside researchers’ access (lead decision D2)', async ({
  page,
  api,
}) => {
  const alice = await api('alice')
  const people = await newPeople(alice, ['nora'])
  const { nora } = people
  try {
    const team = await researchTeam(alice, 'Going private', 'before_evaluation', {})
    await alice.send('PATCH', `/projects/${team.slug}`, { visibility: 'internal' })
    const idea = await alice.createIdea(team.slug, {
      title: `Shared bikes for site visits ${team.key}`,
      summary: 'Two pool bikes at reception.',
    })
    await alice.setOwner(idea.key, 'alice')
    await assignResearcher(alice, idea.key, nora.user, daysFromNow(5))
    expect((await alice.project(team.slug)).outside_researcher_count).toBe(1)
    expect((await nora.api.get<{ key: string }>(`/ideas/${idea.key}`)).key).toBe(idea.key)

    await signIn(page, 'alice')
    await page.goto(`/p/${team.slug}/settings`)
    await expect(heading(page, 'Project settings')).toBeVisible()
    await page.getByRole('radio', { name: /Private/ }).check()
    await page.getByRole('button', { name: /Save changes/ }).click()
    const confirm = page.getByRole('alertdialog', { name: 'Make this project private?' })
    await expect(confirm).toContainText(
      '1 person researching an idea here isn’t in the project and will lose access to it.',
    )
    await confirm.getByRole('button', { name: 'Make private' }).click()
    await expect(toast(page, 'Settings saved')).toBeVisible()

    const gone = await nora.api.raw('GET', `/ideas/${idea.key}`)
    expect(gone.status()).toBe(404)
    const research = await ideaResearch(alice, idea.key)
    expect(research.assignment.researcher).toBeNull()
    expect(research.assignment.due_at).not.toBeNull() // the due date is the idea's
    const [entry] = await alice.audit({ action: 'idea.researcher_change', target_id: idea.id })
    expect(entry?.details).toMatchObject({ reason: 'made_private', from_user_id: nora.user.id })
    expect((await alice.project(team.slug)).outside_researcher_count).toBe(0)
  } finally {
    await disposePeople(people)
  }
})
