import type { Locator, Page, Request } from '@playwright/test'

import { bestPracticeViolations, expect, seriousViolations, test, USERS } from './support'

/**
 * Phase 8b, assigning the research (contract-phase8b §10). The mock's fixtures
 * (src/mocks/phase8b-fixtures.ts): Ivan, in no project, researches TOOL-7 (the
 * private Internal Tools, owner Bob, asked by Alice, its admin; due in 3 days) as its
 * guest; Kofi, a member, researches TOOL-10; Alice researches GREEN-3 (Sustainability,
 * internal, owner Carol), due 2 days ago.
 */

const CAROL = '10000000-0000-4000-8000-000000000004'
const KOFI = '10000000-0000-4000-8000-00000000000c'
const PRIVATE_LINE =
  'They’ll see this idea, its comments and activity and its research checklist, not scores, evaluations or the proposal.'

const toast = (page: Page, text: string) => page.locator('[data-sonner-toast]', { hasText: text })
const researcherLine = (page: Page) => page.getByTestId('researcher-line')
const card = (scope: Page | Locator, key: string) =>
  scope.getByRole('link', { name: new RegExp(`\\(${key}\\)$`) })
const breadcrumb = (page: Page) => page.getByRole('navigation', { name: 'Breadcrumb' })

async function openIdea(page: Page, key: string, title: string) {
  await page.goto(`/ideas/${key}`)
  await expect(page.getByRole('heading', { level: 1, name: title })).toBeVisible()
}

test.describe('a guest researcher (no role in the private project)', () => {
  test.use({ signedInAs: USERS.ivan })

  test('sees that one idea, its checklist and feed, never scores, evaluation or proposal', async ({
    page,
  }) => {
    await openIdea(page, 'TOOL-7', 'Service health dashboard')
    await expect(
      page.getByText('You can see this idea because you’re researching it.'),
    ).toBeVisible()
    // The project by name only: never a link (its routes are 404 for a guest).
    await expect(breadcrumb(page).getByText('Internal Tools')).toBeVisible()
    await expect(breadcrumb(page).getByRole('link', { name: 'Internal Tools' })).toHaveCount(0)
    // No dead tabs, no evaluation area, no score, no AI, no status menu.
    await expect(page.getByRole('tab')).toHaveCount(0)
    const details = page.getByRole('complementary', { name: 'Idea details' })
    await expect(details.getByText('Evaluators')).toHaveCount(0)
    await expect(details.getByText('Score', { exact: true })).toHaveCount(0)
    await expect(page.getByRole('button', { name: /^AI/ })).toHaveCount(0)
    await expect(details.getByRole('button', { name: /Research/ }).first()).toBeVisible()
    await expect(details.getByRole('button', { name: /Status/ })).toHaveCount(0)
    // Who does it: you, with the due date; "Hand back". Never "not in this project" about
    // yourself: the callout above already says why you see it (UX review p2).
    await expect(researcherLine(page)).toContainText(/Research:.*You/)
    await expect(researcherLine(page)).not.toContainText('not in this project')
    await expect(details).not.toContainText('Not in this project')
    await expect(researcherLine(page)).toContainText('due')
    await expect(researcherLine(page).getByRole('button', { name: 'Hand back' })).toBeVisible()
    await expect(researcherLine(page).getByRole('button', { name: /Change/ })).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Answer the checklist' })).toBeVisible()
    // The feed says who asked, and by when, in one line (UX review m3).
    await expect(page.getByText(/asked Ivan Petrov to research, due /)).toBeVisible()
    await expect(page.getByText(/set the research due date/)).toHaveCount(0)
    expect(await seriousViolations(page)).toEqual([])
    expect(await bestPracticeViolations(page)).toEqual([])
  })

  test('mentions only people on the idea, never the directory (UX review M2)', async ({ page }) => {
    const searches: string[] = []
    page.on('request', (request: Request) => {
      const url = new URL(request.url())
      if (url.pathname === '/api/v1/users') searches.push(url.search)
    })
    await openIdea(page, 'TOOL-7', 'Service health dashboard')
    const box = page.getByRole('textbox', { name: 'Write a comment' })
    await box.click()
    await box.pressSequentially('@')
    const picker = page.getByRole('listbox', { name: 'People to mention' })
    await expect(picker).toBeVisible()
    await expect(page.getByText('Mention someone on this idea')).toBeVisible()
    // The owner and whoever asked them (in the feed); nobody else, and no search.
    await expect(picker.getByRole('option', { name: /Bob Chen/ })).toContainText('owner')
    await expect(picker.getByRole('option', { name: /Alice Anders/ })).toBeVisible()
    await expect(picker.getByRole('option', { name: /Carol Díaz/ })).toHaveCount(0)
    await box.pressSequentially('car')
    await expect(picker).toContainText('No one on this idea matches “car”')
    expect(searches).toEqual([])
  })

  test('access ends while the page is open: said plainly, focus on the heading', async ({
    page,
  }) => {
    await openIdea(page, 'TOOL-7', 'Service health dashboard')
    const answer = page.getByRole('textbox', { name: 'Departments or teams consulted' })
    await answer.fill('Half an answer')
    // Someone takes the research away meanwhile (here: the API, as Ivan, behind the page's
    // back); the tab regains focus and checks again (guest review N4).
    await page.evaluate(async () => {
      const csrf = /soundings_csrf=([^;]+)/.exec(document.cookie)?.[1] ?? ''
      await fetch('/api/v1/ideas/TOOL-7/research/assignment', {
        method: 'DELETE',
        headers: { 'X-CSRF-Token': decodeURIComponent(csrf) },
      })
      document.dispatchEvent(new Event('visibilitychange'))
      window.dispatchEvent(new Event('visibilitychange'))
    })
    const heading = page.getByRole('heading', {
      level: 1,
      name: 'You’re no longer researching TOOL-7',
    })
    await expect(heading).toBeVisible()
    await expect(page.getByText('What you typed is kept on this device.')).toBeVisible()
    await expect(heading).toBeFocused()
    await expect(page.getByText('Service health dashboard')).toHaveCount(0)
    expect(await seriousViolations(page)).toEqual([])
  })

  test('answers the checklist', async ({ page }) => {
    await openIdea(page, 'TOOL-7', 'Service health dashboard')
    await page.getByRole('button', { name: 'Answer the checklist' }).click()
    const answer = page.getByRole('textbox', { name: 'Departments or teams consulted' })
    await expect(answer).toBeFocused()
    await answer.fill('Platform and SRE leads: both want one overview.')
    await page.keyboard.press('ControlOrMeta+Enter')
    await expect(page.getByText('Answered by Ivan Petrov')).toBeVisible()
  })

  test('hands it back: off to My work, and the idea is gone', async ({ page }) => {
    await openIdea(page, 'TOOL-7', 'Service health dashboard')
    await researcherLine(page).getByRole('button', { name: 'Hand back' }).click()
    const confirm = page.getByRole('alertdialog', { name: 'Hand back the research of TOOL-7?' })
    await expect(confirm).toContainText('You’ll no longer see TOOL-7')
    await confirm.getByRole('button', { name: 'Hand back' }).click()
    await expect(page).toHaveURL(/\/$/)
    await expect(toast(page, 'You handed the research back')).toBeVisible()
    await expect(page.getByRole('heading', { level: 1, name: 'My work' })).toBeVisible()
    await expect(page.getByRole('heading', { name: /Research to do/ })).toHaveCount(0)
    // The idea's entry was replaced: Back never lands on a page they can't open (UX p6).
    await page.goBack()
    await expect(page).not.toHaveURL(/\/ideas\/TOOL-7$/)
  })

  test.describe('with no projects at all', () => {
    test.beforeEach(async ({ page }) => {
      await page.addInitScript(() => localStorage.setItem('soundings-mock-projects', 'private'))
    })

    test('the shell works: My work, the idea, settings; no project route is called', async ({
      page,
    }) => {
      const projectCalls: string[] = []
      page.on('request', (request: Request) => {
        const path = new URL(request.url()).pathname
        if (/^\/api\/v1\/projects\/[^/]+/.test(path)) projectCalls.push(path)
      })
      await page.goto('/')
      await expect(page.getByRole('heading', { level: 1, name: 'My work' })).toBeVisible()
      await expect(page.getByText('Research you’ve been asked to do.')).toBeVisible()
      const nav = page.getByRole('navigation', { name: 'Main' })
      // No "Projects" heading over nothing (UX review p5).
      await expect(nav.getByText('Projects', { exact: true })).toHaveCount(0)
      await expect(nav.getByText(/No projects/)).toHaveCount(0)
      await expect(nav.getByRole('link', { name: /^Evaluations/ })).toHaveCount(0)
      await expect(nav.getByRole('link', { name: /^Ideas I own/ })).toHaveCount(0)
      await expect(nav.getByRole('link', { name: 'Research, 1 to do' })).toBeVisible()
      // No "New idea" anywhere: nowhere to put one.
      await expect(page.getByRole('button', { name: 'New idea' })).toHaveCount(0)

      const row = page.getByRole('listitem').filter({ hasText: 'TOOL-7' })
      await expect(row).toContainText('Internal Tools')
      await expect(row.getByRole('link', { name: 'Internal Tools' })).toHaveCount(0)
      await expect(row.getByRole('img', { name: /1 required item open/ })).toHaveText('1 open')
      expect(await seriousViolations(page)).toEqual([])
      expect(await bestPracticeViolations(page)).toEqual([])

      await row.getByRole('link', { name: /^Answer the research checklist of TOOL-7/ }).click()
      await expect(
        page.getByRole('heading', { level: 1, name: 'Service health dashboard' }),
      ).toBeVisible()
      await expect(
        page.getByRole('textbox', { name: 'Departments or teams consulted' }),
      ).toBeFocused()

      await nav.getByRole('link', { name: 'Settings' }).click()
      await expect(page.getByRole('heading', { level: 1, name: 'Settings' })).toBeVisible()
      expect(projectCalls).toEqual([])
    })
  })
})

test.describe('past Research (lead decision D1)', () => {
  test.use({ signedInAs: USERS.ivan })

  test('the guest reads the answers but no longer changes them, and is told why', async ({
    page,
  }) => {
    await openIdea(page, 'TOOL-7', 'Service health dashboard')
    await expect(page.getByRole('button', { name: 'Answer the checklist' })).toBeVisible()
    // Alice (an Internal Tools admin) moves the idea on behind the page's back ("Move
    // anyway"); the tab regains focus and reads the idea again.
    await page.evaluate(
      async ([alice, ivan]) => {
        // Each sign-in starts a new CSRF token: read it for every request.
        const csrf = () =>
          decodeURIComponent(/soundings_csrf=([^;]+)/.exec(document.cookie)?.[1] ?? '')
        const send = (path: string, body: unknown) =>
          fetch(path, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf() },
            body: JSON.stringify(body),
          })
        await send('/api/v1/auth/dev/login', { user_id: alice })
        await send('/api/v1/ideas/TOOL-7/status', {
          status: 'evaluating',
          override_research: true,
        })
        await send('/api/v1/auth/dev/login', { user_id: ivan })
        document.dispatchEvent(new Event('visibilitychange'))
        window.dispatchEvent(new Event('visibilitychange'))
      },
      [USERS.alice, USERS.ivan],
    )
    await expect(
      page.getByText(
        'The idea has moved past Research, so only its owner or an admin can change these answers now.',
      ),
    ).toBeVisible()
    await expect(page.getByRole('button', { name: 'Answer the checklist' })).toHaveCount(0)
    await expect(page.getByRole('textbox', { name: 'Departments or teams consulted' })).toHaveCount(
      0,
    )
    // Still their assignment: they can hand it back.
    await expect(researcherLine(page).getByRole('button', { name: 'Hand back' })).toBeVisible()
    expect(await seriousViolations(page)).toEqual([])
  })
})

test.describe('making an internal project private (lead decision D2)', () => {
  test.use({ signedInAs: USERS.priya })

  test('asks first when people outside it research its ideas, then ends their research', async ({
    page,
  }) => {
    await page.goto('/')
    await expect(page.getByRole('heading', { level: 1, name: 'My work' })).toBeVisible()
    // Priya asks Ivan (no role in Sustainability, which is internal) to research GREEN-3,
    // then opens the project's settings in the same page (the mock keeps its data).
    await page.evaluate(async (ivan) => {
      const csrf = decodeURIComponent(/soundings_csrf=([^;]+)/.exec(document.cookie)?.[1] ?? '')
      await fetch('/api/v1/ideas/GREEN-3/research/assignment', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
        body: JSON.stringify({ researcher_id: ivan, due_at: null }),
      })
      window.history.pushState({}, '', '/p/sustainability/settings')
      window.dispatchEvent(new PopStateEvent('popstate'))
    }, USERS.ivan)
    await expect(page.getByRole('heading', { level: 1, name: 'Project settings' })).toBeVisible()
    await page.getByRole('radio', { name: /Private/ }).check()
    const save = page.getByRole('button', { name: /Save changes/ })
    // Cancel keeps everything as it was.
    await save.click()
    const confirm = page.getByRole('alertdialog', { name: 'Make this project private?' })
    await expect(confirm).toContainText(
      '1 person researching an idea here isn’t in the project and will lose access to it.',
    )
    await confirm.getByRole('button', { name: 'Cancel' }).click()
    await expect(confirm).toHaveCount(0)
    await expect(page.getByText('Unsaved changes')).toBeVisible()
    await save.click()
    await confirm.getByRole('button', { name: 'Make private' }).click()
    await expect(toast(page, 'Settings saved')).toBeVisible()
    await expect(confirm).toHaveCount(0)
    // No outsider any more: switching back and forth again asks nothing.
    await page.getByRole('radio', { name: /Internal/ }).check()
    await save.click()
    await expect(toast(page, 'Settings saved').first()).toBeVisible()
    await page.getByRole('radio', { name: /Private/ }).check()
    await save.click()
    await expect(page.getByRole('alertdialog')).toHaveCount(0)
  })
})

test.describe('a member researcher (Kofi on TOOL-10)', () => {
  test.use({ signedInAs: KOFI })

  test('hands it back: stays on the idea, focus on the Research heading (UX review M3)', async ({
    page,
  }) => {
    await openIdea(page, 'TOOL-10', 'Code owners linting')
    await researcherLine(page).getByRole('button', { name: 'Hand back' }).click()
    const confirm = page.getByRole('alertdialog', { name: 'Hand back the research of TOOL-10?' })
    await confirm.getByRole('button', { name: 'Hand back' }).click()
    await expect(confirm).toHaveCount(0)
    await expect(toast(page, 'You handed the research back')).toBeVisible()
    await expect(researcherLine(page).getByRole('button', { name: 'Hand back' })).toHaveCount(0)
    // The button went with the handing back: focus lands on the panel, not the page.
    await expect(page.getByRole('button', { name: 'Research', exact: true })).toBeFocused()
  })
})

test.describe('assigning (a project admin)', () => {
  test('changes the researcher and due date; outsiders are marked and explained', async ({
    page,
  }) => {
    await openIdea(page, 'TOOL-7', 'Service health dashboard')
    await expect(researcherLine(page)).toContainText('Ivan Petrov')
    const change = researcherLine(page).getByRole('button', {
      name: 'Change researcher or due date',
    })
    await change.click()
    const dialog = page.getByRole('dialog', { name: 'Who does the research' })
    await expect(dialog.getByRole('combobox', { name: 'Researcher' })).toHaveAttribute(
      'placeholder',
      'Search everyone…',
    )
    // The current choice is an outsider: the one line says what they'll see.
    await expect(dialog).toContainText('Chosen: Ivan Petrov · Not in this project')
    await expect(dialog).toContainText(PRIVATE_LINE)
    await expect(
      dialog.getByRole('option', { name: /Carol Díaz.*Not in this project/ }),
    ).toBeVisible()
    expect(await seriousViolations(page)).toEqual([])

    await dialog.getByRole('combobox', { name: 'Researcher' }).fill('dave')
    await dialog.getByRole('option', { name: /Dave Okafor/ }).click()
    await expect(dialog).toContainText('Chosen: Dave Okafor')
    await expect(dialog).not.toContainText(PRIVATE_LINE)
    await dialog.getByRole('button', { name: 'In a week' }).click()
    await dialog.getByRole('button', { name: /^Save/ }).click()
    await expect(dialog).toHaveCount(0)
    await expect(toast(page, 'Dave Okafor will do the research')).toBeVisible()
    await expect(researcherLine(page)).toContainText('Dave Okafor')
    await expect(researcherLine(page)).not.toContainText('not in this project')
    // Focus goes back to what opened the dialog.
    await expect(change).toBeFocused()
    await expect(
      page.getByText('asked Dave Okafor instead of Ivan Petrov to research'),
    ).toBeVisible()
  })

  test('removes the researcher by choosing the owner, told who loses the idea (UX S2)', async ({
    page,
  }) => {
    await openIdea(page, 'TOOL-7', 'Service health dashboard')
    // One path: no separate Remove (nor its Undo, which lost focus: UX M3).
    await expect(researcherLine(page).getByRole('button', { name: /Remove/ })).toHaveCount(0)
    const change = researcherLine(page).getByRole('button', {
      name: 'Change researcher or due date',
    })
    await change.click()
    const dialog = page.getByRole('dialog', { name: 'Who does the research' })
    await dialog.getByRole('option', { name: /Bob Chen \(owner\)/ }).click()
    await expect(dialog.getByRole('status')).toHaveText('Ivan Petrov will no longer see TOOL-7.')
    await dialog.getByRole('button', { name: /^Save/ }).click()
    await expect(dialog).toHaveCount(0)
    await expect(toast(page, 'Bob Chen (owner) will do the research')).toBeVisible()
    await expect(researcherLine(page)).toContainText('Bob Chen (owner)')
    await expect(change).toBeFocused()
    await expect(page.getByText('removed Ivan Petrov as researcher')).toBeVisible()
  })

  test('members are told a guest reads the comments (guest review L3)', async ({ page }) => {
    await openIdea(page, 'TOOL-7', 'Service health dashboard')
    await expect(researcherLine(page)).toContainText('Ivan Petrov')
    const note = page.getByText('Ivan Petrov (researching, not in this project) can read comments.')
    await expect(note).toBeVisible()
    await expect(
      page.getByRole('textbox', { name: 'Write a comment' }),
    ).toHaveAccessibleDescription(
      /Ivan Petrov \(researching, not in this project\) can read comments/,
    )
    // In the members' picker the guest is labelled as the researcher.
    const box = page.getByRole('textbox', { name: 'Write a comment' })
    await box.click()
    await box.pressSequentially('@iva')
    await expect(
      page.getByRole('listbox', { name: 'People to mention' }).getByRole('option', {
        name: /Ivan Petrov/,
      }),
    ).toContainText('researcher')
  })

  test('the picker lists the project’s people first, then everyone else (UX m9)', async ({
    page,
  }) => {
    await openIdea(page, 'TOOL-7', 'Service health dashboard')
    await researcherLine(page)
      .getByRole('button', { name: 'Change researcher or due date' })
      .click()
    const dialog = page.getByRole('dialog', { name: 'Who does the research' })
    const members = dialog.getByRole('group', { name: 'In this project', exact: true })
    const others = dialog.getByRole('group', { name: 'Not in this project', exact: true })
    await expect(members.getByRole('option').first()).toBeVisible()
    await expect(others.getByRole('option', { name: /Carol Díaz/ })).toBeVisible()
    await expect(members.getByRole('option', { name: /Not in this project/ })).toHaveCount(0)
  })

  test.describe('the owner, a member of a private project', () => {
    test.use({ signedInAs: USERS.bob })

    test('may pick only the project’s people (an admin names outsiders)', async ({ page }) => {
      await openIdea(page, 'TOOL-7', 'Service health dashboard')
      await researcherLine(page)
        .getByRole('button', { name: 'Change researcher or due date' })
        .click()
      const dialog = page.getByRole('dialog', { name: 'Who does the research' })
      const search = dialog.getByRole('combobox', { name: 'Researcher' })
      await expect(search).toHaveAttribute('placeholder', 'Search the project’s people…')
      // The outsider an admin asked has a row of their own (the list holds only the
      // project's people), chosen and highlighted: Enter keeps them.
      const kept = dialog.getByRole('option', { name: /Ivan .*, chosen/ })
      await expect(kept).toContainText('Not in this project')
      await expect(kept).toHaveAttribute('aria-selected', 'true')
      await search.press('Enter')
      await expect(dialog).toContainText(/Chosen: Ivan [^·]+· Not in this project/)
      await dialog.getByRole('option', { name: /You \(owner\)/ }).click()
      await expect(dialog.getByRole('status')).toHaveText('Ivan Petrov will no longer see TOOL-7.')
      await expect(dialog).toContainText(
        'Only a project admin can ask someone outside this project.',
      )
      await search.fill('carol')
      await expect(dialog).toContainText('No one in this project matches “carol”.')
    })
  })
})

test.describe('Start research (the owner)', () => {
  test.use({ signedInAs: CAROL })

  test('asks who does it and by when, then moves the idea into Research', async ({ page }) => {
    await openIdea(page, 'GREEN-3', 'Solar panels on the warehouse roof')
    await page.getByRole('button', { name: 'Start research' }).first().click()
    const dialog = page.getByRole('dialog', { name: 'Start research' })
    await expect(dialog).toContainText('GREEN-3 moves to Research.')
    await expect(dialog).toContainText('Chosen: Alice Anders')
    expect(await seriousViolations(page)).toEqual([])
    await dialog.getByRole('option', { name: /You \(owner\)/ }).click()
    await expect(dialog).toContainText('Chosen: You (owner)')
    await dialog.getByRole('button', { name: 'In 2 weeks' }).click()
    await dialog.getByRole('button', { name: /^Start research/ }).click()
    await expect(dialog).toHaveCount(0)
    // One toast, the status change's own (with Undo), saying who and by when (UX m4).
    await expect(toast(page, 'GREEN-3 moved to Research')).toHaveCount(1)
    await expect(toast(page, 'GREEN-3 moved to Research')).toContainText(
      /You do the research · due /,
    )
    const details = page.getByRole('complementary', { name: 'Idea details' })
    await expect(details.getByText('Research', { exact: true }).first()).toBeVisible()
    await expect(researcherLine(page)).toContainText('You (owner)')
  })
})

test.describe('an overdue research due date (UX review M1)', () => {
  test.use({ signedInAs: CAROL })

  test('stays valid until changed: Start research keeps it and starts', async ({ page }) => {
    await openIdea(page, 'GREEN-3', 'Solar panels on the warehouse roof')
    await page.getByRole('button', { name: 'Start research' }).first().click()
    const dialog = page.getByRole('dialog', { name: 'Start research' })
    // GREEN-3 was due 2 days ago: said in words, and the form still submits as it is.
    await expect(dialog).toContainText(/Was due .+ \(overdue\)\. Pick a new date, or keep it\./)
    await dialog.getByRole('button', { name: /^Start research/ }).click()
    await expect(dialog).toHaveCount(0)
    await expect(toast(page, 'GREEN-3 moved to Research')).toContainText(
      /Alice Anders does the research · overdue, was due /,
    )
  })

  test('a different researcher keeps the overdue date as it was', async ({ page }) => {
    await openIdea(page, 'GREEN-3', 'Solar panels on the warehouse roof')
    await researcherLine(page)
      .getByRole('button', { name: 'Change researcher or due date' })
      .click()
    const dialog = page.getByRole('dialog', { name: 'Who does the research' })
    await dialog.getByRole('option', { name: /You \(owner\)/ }).click()
    await dialog.getByRole('button', { name: /^Save/ }).click()
    await expect(dialog).toHaveCount(0)
    await expect(researcherLine(page)).toContainText(/You \(owner\).*overdue, was due/)
  })
})

test.describe('the owner does the research (nobody assigned)', () => {
  test.use({ signedInAs: CAROL })

  test('the highlight starts on the owner row, so Enter changes nothing (QA N1)', async ({
    page,
  }) => {
    await page.goto('/ideas/GREEN-1')
    // One thing to do here, so the sidebar's value opens it straight away.
    await page
      .getByRole('button', { name: /^Research: You \(owner\).*\. Change researcher or due date$/ })
      .click()
    const dialog = page.getByRole('dialog', { name: 'Who does the research' })
    await expect(dialog).toContainText('Chosen: You (owner)')
    const search = dialog.getByRole('combobox', { name: 'Researcher' })
    await expect(search).toBeFocused()
    await expect(dialog.getByRole('option', { name: /You \(owner\)/ })).toHaveAttribute(
      'aria-selected',
      'true',
    )
    await search.press('Enter')
    await expect(dialog).toContainText('Chosen: You (owner)')
  })
})

test.describe('the board', () => {
  test('Research cards show who researches them', async ({ page }) => {
    await page.goto('/p/internal-tools')
    const research = page.getByRole('region', { name: /^Research\b/ })
    const tool7 = card(research, 'TOOL-7')
    await expect(tool7.getByRole('img', { name: 'Researched by Ivan Petrov' })).toBeVisible()
    // In the card's description (its name stays "Title (KEY)").
    await expect(tool7).toHaveAccessibleDescription(/Researched by Ivan Petrov/)
    await expect(
      card(research, 'TOOL-10').getByRole('img', { name: 'Researched by Kofi Boateng' }),
    ).toBeVisible()
    expect(await seriousViolations(page)).toEqual([])
  })
})

test.describe('My work', () => {
  test('“Research to do”: overdue first, the open items, the sidebar badge', async ({ page }) => {
    await page.goto('/')
    const section = page.getByRole('region', { name: /Research to do/ })
    await expect(section).toBeVisible()
    const row = section.getByRole('listitem').filter({ hasText: 'GREEN-3' })
    await expect(row).toContainText('Overdue 2 days')
    await expect(row.getByRole('img', { name: /1 required item open/ })).toHaveText('1 open')
    await expect(row.getByRole('link', { name: 'Sustainability' })).toBeVisible()
    const nav = page.getByRole('navigation', { name: 'Main' })
    await expect(nav.getByRole('link', { name: 'Research, 1 to do, 1 overdue' })).toBeVisible()
    expect(await seriousViolations(page)).toEqual([])
    expect(await bestPracticeViolations(page)).toEqual([])
    await row.getByRole('link', { name: /^Answer the research checklist of GREEN-3/ }).click()
    await expect(page).toHaveURL(/\/ideas\/GREEN-3/)
    await expect(
      page.getByRole('textbox', { name: 'Departments or teams consulted' }),
    ).toBeFocused()
  })
})

test.describe('Restore puts removed rows back where they were (Phase 8 review D)', () => {
  test('a template section removed on another visit', async ({ page }) => {
    await page.goto('/p/internal-tools/settings?tab=proposal-template')
    const sections = page.getByRole('list', { name: 'Sections' }).getByRole('listitem')
    await expect(sections).toHaveCount(6)
    await page.getByRole('button', { name: 'Remove Solution' }).click()
    await page.getByRole('button', { name: 'Save template' }).click()
    await expect(toast(page, 'Proposal template saved')).toBeVisible()
    // Another tab and back: the editor starts afresh, so only the server's `position` knows.
    await page.getByRole('tab', { name: 'General' }).click()
    await page.getByRole('tab', { name: 'Proposal' }).click()
    await page.getByRole('button', { name: 'Restore Solution' }).click()
    await expect(sections.nth(2).getByRole('textbox', { name: 'Title' })).toHaveValue('Solution')
  })

  test('a checklist item removed on another visit', async ({ page }) => {
    await page.goto('/p/internal-tools/settings?tab=research')
    const items = page.getByRole('list', { name: 'Checklist items' }).getByRole('listitem')
    await expect(items).toHaveCount(3)
    const second = await items.nth(1).getByRole('textbox', { name: 'Title' }).inputValue()
    await page.getByRole('button', { name: `Remove ${second}` }).click()
    await page.getByRole('button', { name: 'Save research step' }).click()
    await expect(page.getByRole('heading', { name: 'Removed items' })).toBeVisible()
    await page.getByRole('tab', { name: 'General' }).click()
    await page.getByRole('tab', { name: 'Research' }).click()
    await page.getByRole('button', { name: `Restore ${second}` }).click()
    await expect(items.nth(1).getByRole('textbox', { name: 'Title' })).toHaveValue(second)
  })
})

const overflow = (page: Page) =>
  page.evaluate(() => {
    const main = document.getElementById('main')
    return Math.max(
      document.documentElement.scrollWidth - window.innerWidth,
      main ? main.scrollWidth - main.clientWidth : 0,
    )
  })

test.describe('dark mode', () => {
  test.use({ colorScheme: 'dark' })

  test.describe('as the guest researcher', () => {
    test.use({ signedInAs: USERS.ivan })

    test('the idea page has no serious violations', async ({ page }) => {
      await openIdea(page, 'TOOL-7', 'Service health dashboard')
      await expect(researcherLine(page)).toBeVisible()
      expect(await seriousViolations(page)).toEqual([])
    })
  })

  test('My work with research to do, and the assignment dialog, have none', async ({ page }) => {
    await page.goto('/')
    await expect(page.getByRole('region', { name: /Research to do/ })).toBeVisible()
    expect(await seriousViolations(page)).toEqual([])
    await openIdea(page, 'TOOL-7', 'Service health dashboard')
    await researcherLine(page)
      .getByRole('button', { name: 'Change researcher or due date' })
      .click()
    await expect(page.getByRole('dialog', { name: 'Who does the research' })).toBeVisible()
    expect(await seriousViolations(page)).toEqual([])
  })
})

test.describe('on a phone (390px)', () => {
  test.use({ viewport: { width: 390, height: 844 } })

  test('My work and the assignment dialog fit without sideways scrolling', async ({ page }) => {
    await page.goto('/')
    await expect(page.getByRole('region', { name: /Research to do/ })).toBeVisible()
    expect(await overflow(page)).toBeLessThanOrEqual(0)
    await openIdea(page, 'TOOL-7', 'Service health dashboard')
    expect(await overflow(page)).toBeLessThanOrEqual(0)
    await researcherLine(page)
      .getByRole('button', { name: 'Change researcher or due date' })
      .click()
    const dialog = page.getByRole('dialog', { name: 'Who does the research' })
    await expect(dialog).toBeVisible()
    // Full screen on phones, the actions in reach.
    await expect(dialog.getByRole('button', { name: /^Save/ })).toBeInViewport()
    // "No due date" sits by the date field, never on a row of its own (QA N2).
    await dialog.getByRole('button', { name: 'In a week' }).click()
    const field = await dialog.getByLabel('Research due date').boundingBox()
    const clear = await dialog.getByRole('button', { name: 'No due date' }).boundingBox()
    expect(
      field && clear && Math.abs(clear.y + clear.height / 2 - (field.y + field.height / 2)),
    ).toBeLessThan(4)
  })

  test.describe('as the guest researcher', () => {
    test.use({ signedInAs: USERS.ivan })

    test('the idea page fits, and Details holds no evaluation or score', async ({ page }) => {
      await openIdea(page, 'TOOL-7', 'Service health dashboard')
      expect(await overflow(page)).toBeLessThanOrEqual(0)
      await page.getByRole('button', { name: /Details/ }).click()
      const sheet = page.getByRole('dialog', { name: 'Details' })
      await expect(sheet.getByRole('term').filter({ hasText: /^Research$/ })).toBeVisible()
      await expect(sheet.getByText('Evaluators')).toHaveCount(0)
      await expect(sheet.getByText('Score', { exact: true })).toHaveCount(0)
    })
  })
})
