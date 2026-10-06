import type { Browser, Page } from '@playwright/test'

import { Api, createTeamProject, type Person } from './support/api'
import { expect, signIn, test, toast } from './support/fixtures'

/**
 * The proposal editor against the real API (contract-phase4 §3.1–3.3, role matrix E):
 * two people saving the same section (409 → the conflict prompt, Keep your version / Use {name}’s version),
 * different sections side by side, margin threads (comment, reply, resolve, reopen,
 * delete), who may write, comment and export, and the editor at 390 px. Test plan: PR4-*.
 */

/** A shortlisted idea owned by Bob with its proposal started, in a fresh project. */
async function proposalIdea(alice: Api): Promise<{ key: string; slug: string }> {
  const project = await createTeamProject(alice, 'Proposals', {
    bob: 'member',
    carol: 'member',
    dave: 'member',
    erin: 'viewer',
  })
  const idea = await alice.createIdea(project.slug, {
    title: 'Same-day delivery in city centres',
    summary: 'Cargo bikes deliver orders placed before noon the same day.',
  })
  await alice.setOwner(idea.key, 'bob')
  await alice.changeStatus(idea.key, 'shortlisted')
  const bob = await Api.as(alice.baseURL, 'bob')
  await bob.startProposal(idea.key)
  await bob.dispose()
  return { key: idea.key, slug: project.slug }
}

async function editorFor(browser: Browser, baseURL: string, person: Person, key: string) {
  const context = await browser.newContext({ baseURL, viewport: { width: 1440, height: 900 } })
  const page = await context.newPage()
  await signIn(page, person)
  await page.goto(`/ideas/${key}?tab=proposal`)
  await expect(page.getByRole('heading', { level: 2, name: /Problem$/ })).toBeVisible()
  return page
}

const section = (page: Page, title: string) =>
  page.getByRole('textbox', { name: title, exact: true })
const saved = (page: Page) => page.getByRole('status').filter({ hasText: /^Saved/ })

test.describe('PR4-01: two people, one section', () => {
  test('a stale save gets the conflict prompt; Keep your version saves over theirs', async ({
    browser,
    api,
    baseURL,
  }) => {
    const alice = await api('alice')
    const { key } = await proposalIdea(alice)
    // Both open the proposal while Problem is still empty (version 1).
    const bob = await editorFor(browser, baseURL ?? '', 'bob', key)
    const admin = await editorFor(browser, baseURL ?? '', 'alice', key)

    await section(bob, 'Problem').fill('Customers wait three days for a parcel.')
    await expect(saved(bob)).toBeVisible()
    await expect
      .poll(async () => (await alice.proposal(key)).proposal?.sections[1]?.version)
      .toBe(2)

    await section(admin, 'Problem').fill('Orders after noon miss the van.')
    const prompt = admin.getByRole('alert').filter({ hasText: 'changed this section' })
    await expect(prompt).toContainText('Bob Brown changed this section while you were editing')
    await expect(prompt.getByRole('figure').first()).toContainText('Bob Brown’s version')
    await expect(prompt.getByRole('figure').first()).toContainText(
      'Customers wait three days for a parcel.',
    )
    await expect(prompt.getByRole('figure').nth(1)).toContainText('Your version')
    await expect(admin.getByText('A section changed while you were editing')).toBeVisible()
    // Nothing of Alice's is saved until she chooses.
    expect((await alice.proposal(key)).proposal?.sections[1]?.body_md).toBe(
      'Customers wait three days for a parcel.',
    )
    await prompt.getByRole('button', { name: 'Keep your version' }).click()
    await expect(prompt).toHaveCount(0)
    await expect(saved(admin)).toBeVisible()
    await expect
      .poll(async () => (await alice.proposal(key)).proposal?.sections[1])
      .toMatchObject({ body_md: 'Orders after noon miss the van.', version: 3 })

    // Bob's view is now the stale one: his next edit conflicts; he takes Alice's.
    await section(bob, 'Problem').fill('Customers wait three days. Really.')
    const bobPrompt = bob.getByRole('alert').filter({ hasText: 'changed this section' })
    await expect(bobPrompt).toContainText('Alice Anders changed this section')
    await bobPrompt.getByRole('button', { name: 'Use Alice Anders’s version' }).click()
    await expect(bobPrompt).toHaveCount(0)
    await expect(section(bob, 'Problem')).toHaveValue('Orders after noon miss the van.')
    expect((await alice.proposal(key)).proposal?.sections[1]?.version).toBe(3)
    await bob.context().close()
    await admin.context().close()
  })

  test('different sections save side by side without a conflict', async ({
    browser,
    api,
    baseURL,
  }) => {
    const alice = await api('alice')
    const { key } = await proposalIdea(alice)
    const bob = await editorFor(browser, baseURL ?? '', 'bob', key)
    const admin = await editorFor(browser, baseURL ?? '', 'alice', key)
    await Promise.all([
      section(bob, 'Solution').fill('Cargo bikes from two city hubs.'),
      section(admin, 'Risks').fill('Rain; bike theft; rider availability.'),
    ])
    await Promise.all([expect(saved(bob)).toBeVisible(), expect(saved(admin)).toBeVisible()])
    await expect
      .poll(async () => {
        const sections = (await alice.proposal(key)).proposal?.sections ?? []
        return [sections[2]?.body_md, sections[6]?.body_md]
      })
      .toEqual(['Cargo bikes from two city hubs.', 'Rain; bike theft; rider availability.'])
    await expect(bob.getByRole('alert').filter({ hasText: 'changed this section' })).toHaveCount(0)
    await expect(admin.getByRole('alert').filter({ hasText: 'changed this section' })).toHaveCount(
      0,
    )
    // Text is stored exactly as typed: indentation and trailing blank lines included.
    const verbatim = '    indented code\n\nlast line\n\n'
    await section(bob, 'Cost & effort').fill(verbatim)
    await expect
      .poll(async () => (await alice.proposal(key)).proposal?.sections[4]?.body_md)
      .toBe(verbatim)
    await bob.context().close()
    await admin.context().close()
  })
})

test('PR4-02: margin threads: comment, reply, resolve, reopen, delete', async ({
  browser,
  api,
  baseURL,
}) => {
  const alice = await api('alice')
  const { key } = await proposalIdea(alice)
  const carol = await editorFor(browser, baseURL ?? '', 'carol', key)
  const margin = carol.getByRole('complementary', { name: 'Comments on Problem' })
  await margin.getByRole('button', { name: 'Comment on Problem' }).click()
  await margin
    .getByRole('textbox', { name: 'Comment on Problem' })
    .fill('Do we have numbers for **missed** deliveries?')
  await carol.keyboard.press('ControlOrMeta+Enter')
  const thread = margin.getByRole('article', { name: /^Thread by Carol Chen on Problem/ })
  await expect(thread).toContainText('Do we have numbers for missed deliveries?')
  await expect(thread.locator('strong')).toHaveText('missed') // Markdown, rendered

  // Bob replies in the margin and resolves the thread: it collapses to one line.
  const bob = await editorFor(browser, baseURL ?? '', 'bob', key)
  const bobMargin = bob.getByRole('complementary', { name: 'Comments on Problem' })
  const bobThread = bobMargin.getByRole('article', { name: /^Thread by Carol Chen/ })
  await bobThread.getByRole('button', { name: 'Reply' }).click()
  await bobThread
    .getByRole('textbox', { name: 'Reply to Carol Chen’s thread' })
    .fill('Yes: 1,200 last quarter, in the ops report.')
  await bobThread.getByRole('button', { name: 'Reply' }).click()
  await expect(bobThread.getByText('Yes: 1,200 last quarter')).toBeVisible()
  await bobThread.getByRole('button', { name: 'Resolve' }).click()
  const collapsed = bobMargin.getByRole('button', { name: /^Resolved · Carol Chen/ })
  await expect(collapsed).toBeVisible()
  await expect(collapsed).toHaveAttribute('aria-expanded', 'false')
  // The margin collapses the thread at once (optimistic); the save lands a moment later.
  await expect
    .poll(async () => (await alice.threads(key))[0]?.resolved_by?.display_name)
    .toBe('Bob Brown')
  const [resolved] = await alice.threads(key)

  // Bob can't delete Carol's comment (403 not_author); an admin could.
  const bobApi = await api('bob')
  const carolComment = resolved?.comments[0]
  expect(carolComment?.can_delete).toBe(true) // for Alice, the admin
  const refused = await bobApi.raw(
    'DELETE',
    `/ideas/${key}/proposal/threads/${resolved?.id}/comments/${carolComment?.id}`,
  )
  expect(refused.status()).toBe(403)
  expect(((await refused.json()) as { code: string }).code).toBe('not_author')

  // A reply to a resolved thread reopens it (Carol's view, after a reload).
  const carolApi = await api('carol')
  const reopened = await carolApi.reply(key, resolved?.id ?? '', 'Thanks, adding it to Problem.')
  expect(reopened.resolved_at).toBeNull()
  await carol.reload()
  await expect(thread).toContainText('Thanks, adding it to Problem.')
  await expect(thread.getByRole('button', { name: 'Resolve' })).toBeVisible()

  // Carol deletes her own last comment: Undo, then it goes.
  await thread.getByRole('button', { name: 'Delete Carol Chen’s comment' }).last().click()
  await expect(toast(carol, /Comment deleted/)).toBeVisible()
  await expect
    .poll(
      async () =>
        (await carolApi.threads(key))[0]?.comments.filter((comment) => comment.deleted).length,
      { timeout: 20_000 },
    )
    .toBe(1)
  await carol.reload()
  await expect(thread.getByText('Comment deleted')).toBeVisible()
  await expect(thread).not.toContainText('Thanks, adding it to Problem.')
  await carol.context().close()
  await bob.context().close()
})

test('PR4-03: who may write, comment and export', async ({ page, browser, api, baseURL }) => {
  const alice = await api('alice')
  const { key } = await proposalIdea(alice)
  await (await api('bob')).writeSections(key, { problem: 'Parcels take **three days**.' })

  // A viewer reads the rendered Markdown and may export; no editor, no comments.
  await signIn(page, 'erin')
  await page.goto(`/ideas/${key}?tab=proposal`)
  await expect(page.getByRole('heading', { level: 2, name: /Problem$/ })).toBeVisible()
  await expect(page.locator('main strong', { hasText: 'three days' })).toBeVisible()
  await expect(page.getByRole('textbox', { name: 'Problem', exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: /^Comment/ })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Export' })).toBeVisible()
  const erin = await api('erin')
  expect(
    (
      await erin.raw('PUT', `/ideas/${key}/proposal/sections/risks`, {
        body_md: 'x',
        base_version: 1,
      })
    ).status(),
  ).toBe(403)
  expect(
    (
      await erin.raw('POST', `/ideas/${key}/proposal/threads`, {
        section_key: 'risks',
        body_md: 'x',
      })
    ).status(),
  ).toBe(403)
  expect((await erin.exportProposal(key, 'markdown')).response.status()).toBe(200)

  // A member who isn't the owner comments but doesn't write.
  const dave = await editorFor(browser, baseURL ?? '', 'dave', key)
  await expect(dave.getByRole('textbox', { name: 'Problem', exact: true })).toHaveCount(0)
  await expect(
    dave
      .getByRole('complementary', { name: 'Comments on Problem' })
      .getByRole('button', { name: 'Comment on Problem' }),
  ).toBeVisible()
  const daveApi = await api('dave')
  expect(
    (
      await daveApi.raw('PUT', `/ideas/${key}/proposal/sections/risks`, {
        body_md: 'x',
        base_version: 1,
      })
    ).status(),
  ).toBe(403)
  await dave.context().close()

  // Back to Evaluating: read-only for the owner too (409), still readable and exportable.
  await alice.changeStatus(key, 'evaluating')
  const bob = await editorFor(browser, baseURL ?? '', 'bob', key)
  await expect(
    bob.getByText('This proposal is read-only while the idea isn’t Shortlisted or in Proposal'),
  ).toBeVisible()
  await expect(bob.getByRole('textbox', { name: 'Problem', exact: true })).toHaveCount(0)
  const bobApi = await api('bob')
  const stale = await bobApi.raw('PUT', `/ideas/${key}/proposal/sections/risks`, {
    body_md: 'x',
    base_version: 1,
  })
  expect(stale.status()).toBe(409)
  expect(((await stale.json()) as { code: string }).code).toBe('proposal_not_available')
  expect((await bobApi.exportProposal(key, 'pdf')).response.status()).toBe(200)
  await bob.context().close()

  // Before it is shortlisted, members see what to expect.
  const project = (await alice.idea(key)).project.slug
  const other = await alice.createIdea(project, {
    title: 'Gift wrapping at the till',
    summary: 'Paid gift wrapping.',
  })
  await signIn(page, 'carol')
  await page.goto(`/ideas/${other.key}?tab=proposal`)
  await expect(
    page.getByRole('heading', { level: 2, name: 'Available once the idea is shortlisted' }),
  ).toBeVisible()
})

test('PR4-04: at 390 px written sections open in Preview and comments open in a sheet', async ({
  browser,
  api,
  baseURL,
}) => {
  const alice = await api('alice')
  const { key } = await proposalIdea(alice)
  const bobApi = await api('bob')
  await bobApi.writeSections(key, { problem: 'Parcels take three days.' })
  const context = await browser.newContext({
    baseURL,
    viewport: { width: 390, height: 844 },
    isMobile: true,
    hasTouch: true,
  })
  const page = await context.newPage()
  await signIn(page, 'bob')
  await page.goto(`/ideas/${key}?tab=proposal`)
  await expect(page.getByRole('heading', { level: 2, name: /Problem$/ })).toBeVisible()
  await expect(page.getByRole('region', { name: 'Problem (preview)' })).toContainText(
    'Parcels take three days.',
  )
  await expect(page.getByRole('combobox', { name: 'Jump to section' })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
  await page.getByRole('button', { name: 'Comment on Problem' }).tap()
  const sheet = page.getByRole('dialog', { name: 'Comments on Problem' })
  await expect(sheet).toBeVisible()
  await sheet
    .getByRole('textbox', { name: 'Comment on Problem' })
    .fill('Source for the three days?')
  await sheet.getByRole('button', { name: 'Comment', exact: true }).tap()
  await expect(sheet.getByText('Source for the three days?')).toBeVisible()
  await context.close()
})

test('PR4-05: moving around the editor scrolls the editor, never the whole app', async ({
  page,
  api,
}) => {
  const alice = await api('alice')
  const { key } = await proposalIdea(alice)
  const carol = await api('carol')
  const thread = await carol.startThread(key, 'risks', 'Is rain really a risk for cargo bikes?')
  await (await api('bob')).resolveThread(key, thread.id)
  await carol.startThread(key, 'next_steps', 'Who signs off the pilot?')
  await signIn(page, 'bob')
  await page.goto(`/ideas/${key}?tab=proposal`)
  await expect(page.getByRole('heading', { level: 2, name: /Problem$/ })).toBeVisible()
  await expect(page.getByText('Who signs off the pilot?')).toBeVisible()
  // The shell is the viewport: only <main> scrolls.
  const overflow = () =>
    page.evaluate(
      () => document.documentElement.scrollHeight - document.documentElement.clientHeight,
    )
  expect(await overflow()).toBe(0)
  await page
    .getByRole('navigation', { name: 'Outline' })
    .getByRole('link', { name: /^Next steps \/ the ask/ })
    .click()
  await expect(page.getByRole('textbox', { name: 'Next steps / the ask' })).toBeFocused()
  expect(await page.evaluate(() => window.scrollY)).toBe(0)
  await expect(page.getByRole('button', { name: 'Export' })).toBeInViewport()
})
