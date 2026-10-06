import type { Page } from '@playwright/test'

import { createTeamProject, PEOPLE, type Api, type IdeaDetail } from './support/api'
import {
  details,
  expect,
  heading,
  openIdea,
  signIn,
  switchUserInUi,
  test,
  toast,
} from './support/fixtures'

/**
 * Keyboard flows from the Phase 1 UX review, against the real stack (the page-test
 * twin is frontend/tests/keyboard-flow.spec.ts): focus comes back after overlays and
 * inline edits close, pickers work as "type a name, press Enter", ⌘/Ctrl+Enter submits
 * Invite, ⌘K highlights its top row, settings ask before throwing edits away, and an
 * unsent draft never reaches the next person on the browser. Test plan: KB-08…KB-13.
 */

/** A fresh project (Alice admin; Bob, Carol, Kenji members) with one idea owned by Bob. */
async function ideaInOwnProject(alice: Api, name: string): Promise<IdeaDetail> {
  const project = await createTeamProject(alice, name, {
    bob: 'member',
    carol: 'member',
    kenji: 'member',
  })
  const idea = await alice.createIdea(project.slug, {
    title: `${name} idea`,
    summary: 'Made by the keyboard-flow tests.',
  })
  await alice.setOwner(idea.key, 'bob')
  return idea
}

async function openPalette(page: Page) {
  await page.keyboard.press('ControlOrMeta+k')
  const palette = page.getByRole('dialog', { name: 'Command palette' })
  await expect(palette.getByRole('combobox')).toBeFocused()
  return palette
}

test('KB-08: focus goes back to where it was when an overlay closes', async ({ page, api }) => {
  const idea = await ideaInOwnProject(await api('alice'), 'Focus')
  await signIn(page, 'alice')
  await openIdea(page, idea.key)

  const invite = details(page).getByRole('button', { name: 'Invite evaluators' })
  await invite.focus()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('dialog', { name: 'Invite evaluators' })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(invite).toBeFocused()

  // New idea, the palette, the "?" sheet, the status and owner pickers.
  for (const key of ['n', 'ControlOrMeta+k', '?', 's', 'a']) {
    await page.keyboard.press(key)
    await expect(page.getByRole('dialog'), `opened by ${key}`).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(page.getByRole('dialog')).toBeHidden()
    await expect(invite, `after ${key}`).toBeFocused()
  }

  // A dialog opened from a menu returns to the menu's button.
  const more = page.getByRole('button', { name: 'More actions' })
  await more.click()
  await page.getByRole('menuitem', { name: /Delete idea/ }).click()
  await expect(page.getByRole('alertdialog')).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(more).toBeFocused()

  // An inline edit hands focus back to its button.
  await page.getByRole('button', { name: 'Edit title' }).click()
  await page.keyboard.press('End')
  await page.keyboard.type(' v2')
  await page.keyboard.press('Enter')
  await expect(heading(page, `${idea.title} v2`)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Edit title' })).toBeFocused()
})

test('KB-09: the owner picker: type a name, press Enter', async ({ page, api }) => {
  const alice = await api('alice')
  const idea = await ideaInOwnProject(alice, 'Owner picker')
  await signIn(page, 'alice')
  await openIdea(page, idea.key)

  await page.keyboard.press('a')
  const dialog = page.getByRole('dialog', { name: 'Change owner' })
  await expect(dialog).toBeVisible()
  await page.keyboard.type('kenj')
  await expect(dialog.getByRole('option', { name: new RegExp(PEOPLE.kenji) })).toHaveAttribute(
    'aria-selected',
    'true',
  )
  // "Remove owner" steps aside while you search, so Enter can't pick it by accident.
  await expect(dialog.getByRole('option', { name: 'Remove owner' })).toBeHidden()
  await page.keyboard.press('Enter')
  await expect(dialog).toBeHidden()
  await expect(details(page).getByRole('button', { name: /^Owner: Kenji Watanabe/ })).toBeVisible()
  // The sidebar shows the new owner as soon as it is picked (optimistic); the save lands
  // a moment later, which a loaded machine stretches.
  await expect.poll(async () => (await alice.idea(idea.key)).owner?.display_name).toBe(PEOPLE.kenji)
})

test('KB-10: Invite: type, Enter picks, ⌘/Ctrl+Enter invites', async ({ page, api }) => {
  const alice = await api('alice')
  const idea = await ideaInOwnProject(alice, 'Invite')
  await signIn(page, 'alice')
  await openIdea(page, idea.key)

  await details(page).getByRole('button', { name: 'Invite evaluators' }).click()
  const dialog = page.getByRole('dialog', { name: 'Invite evaluators' })
  await page.keyboard.type('caro')
  await expect(dialog.getByRole('option', { name: new RegExp(PEOPLE.carol) })).toHaveAttribute(
    'aria-selected',
    'true',
  )
  await page.keyboard.press('Enter')
  await expect(dialog.getByRole('list', { name: 'Selected people' })).toContainText(PEOPLE.carol)

  // With focus still in the search field: invites, doesn't toggle Carol off again.
  await page.keyboard.press('ControlOrMeta+Enter')
  await expect(dialog).toBeHidden()
  await expect(toast(page, `Invited ${PEOPLE.carol}`)).toBeVisible()
  const saved = await alice.idea(idea.key)
  expect(saved.evaluators.map((evaluator) => evaluator.user.display_name)).toEqual([PEOPLE.carol])
})

test('KB-11: ⌘K highlights the top row, and commands sit above ideas', async ({ page }) => {
  await signIn(page, 'alice')
  await page.goto('/')
  await expect(heading(page, 'My work')).toBeVisible()

  for (const [query, top] of [
    ['new', /New idea/],
    // "sign out", not "sign": platform admins also have "Sign-in (SSO)" (Phase 2).
    ['sign out', /Sign out/],
    ['whatsapp', /WhatsApp order updates/],
  ] as const) {
    const palette = await openPalette(page)
    await page.keyboard.type(query)
    await expect(palette.getByRole('option').first()).toHaveText(top)
    await expect(palette.getByRole('option', { selected: true })).toHaveText(top)
    await page.keyboard.press('Escape')
    await expect(palette).toBeHidden()
  }
})

test('KB-12: settings ask before leaving with unsaved changes', async ({ page, api }) => {
  const alice = await api('alice')
  const project = await createTeamProject(alice, 'Unsaved', { bob: 'member' })
  await signIn(page, 'alice')
  await page.goto(`/p/${project.slug}/settings?tab=rubric`)
  await expect(heading(page, 'Project settings')).toBeVisible()
  const firstName = page
    .getByRole('list', { name: 'Criteria' })
    .getByRole('listitem')
    .first()
    .getByRole('textbox', { name: 'Name' })
  await firstName.fill('Customer value')
  // The save bar stays in view while there are changes.
  await expect(page.getByRole('button', { name: /Save rubric/ })).toBeInViewport()

  const myWork = page.getByRole('link', { name: 'My work' }).first()
  await myWork.click()
  const confirm = page.getByRole('alertdialog', { name: 'Leave without saving?' })
  await expect(confirm).toContainText('the rubric')
  await confirm.getByRole('button', { name: 'Keep editing' }).click()
  await expect(page).toHaveURL(/\/settings/)
  await expect(firstName).toHaveValue('Customer value')

  await myWork.click()
  await confirm.getByRole('button', { name: 'Discard changes' }).click()
  await expect(heading(page, 'My work')).toBeVisible()
  // Nothing was saved.
  const rubric = (await alice.project(project.slug)).rubric
  expect(rubric.map((criterion) => criterion.name)).not.toContain('Customer value')
})

test('KB-13: an unsent New idea draft stays with its author', async ({ page }) => {
  await signIn(page, 'alice')
  await page.goto('/')
  await expect(heading(page, 'My work')).toBeVisible()
  await page.keyboard.press('n')
  await page.getByRole('textbox', { name: 'Title' }).fill('Alice: confidential plan')
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog', { name: 'New idea' })).toBeHidden()

  await switchUserInUi(page, 'bob')
  await expect(heading(page, 'My work')).toBeVisible()
  await page.keyboard.press('n')
  await expect(page.getByRole('textbox', { name: 'Title' })).toHaveValue('')
  expect(
    await page.evaluate(() => Object.keys(localStorage).filter((key) => key.includes('draft'))),
  ).toEqual([])
})
