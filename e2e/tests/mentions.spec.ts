import type { Page } from '@playwright/test'

import { createTeamProject, uniqueKey } from './support/api'
import {
  disposePeople,
  emailCount,
  emailTo,
  expectNoScoreData,
  links,
  newPeople,
  projectWithIdea,
  requireEmail,
  signInAs,
  visibleText,
} from './support/email'
import { expect, openIdea, test } from './support/fixtures'

/**
 * @mentions (contract-phase3 §3.8) on the real stack: the picker offers the project's
 * people only; a mention notifies people with a role in the project who can view the
 * idea, in the app and by email (a link to the comment); labels can't impersonate; an
 * edit notifies only people newly mentioned. Test plan: ME-*.
 */

const composer = (page: Page) => page.getByRole('textbox', { name: 'Write a comment' })
const picker = (page: Page) => page.getByRole('listbox', { name: 'People to mention' })
const token = (person: { name: string; user: { id: string } }) =>
  `@[${person.name}](user:${person.user.id})`

test('ME-01: the picker offers the project’s people; the mention arrives in the app and by email, linking to the comment', async ({
  page,
  browser,
  api,
}) => {
  const alice = await api('alice')
  await requireEmail(alice)
  const people = await newPeople(alice, ['nora', 'theo', 'owen'])
  const { nora, theo, owen } = people
  try {
    const { key, title } = await projectWithIdea(alice, 'Mentions', [nora, theo], { owner: nora })
    const base = (await alice.emailConfig()).links_base_url.replace(/\/$/, '')

    await signInAs(page, nora)
    await openIdea(page, key)
    await composer(page).click()
    // Owen has an account but no role here: not offered.
    await page.keyboard.type('@Ow')
    await expect(picker(page).getByRole('option', { name: /Owen Pike/ })).toHaveCount(0)
    await page.keyboard.press('Escape')
    await composer(page).fill('')
    await page.keyboard.type('Thanks @The')
    await expect(picker(page).getByRole('option', { name: /Theo Marsh/ })).toBeVisible()
    await expect(picker(page)).not.toContainText('Nora Quinn') // not yourself
    await page.keyboard.press('Enter')
    await expect(picker(page)).toBeHidden()
    await page.keyboard.type('can you check the courier API?')
    await expect(composer(page)).toHaveValue(`Thanks ${token(theo)} can you check the courier API?`)
    const since = new Date()
    await composer(page).press('ControlOrMeta+Enter')
    const posted = page
      .locator('article[data-comment-id]')
      .filter({ hasText: 'can you check the courier API?' })
    await expect(posted.locator('[data-mention]')).toHaveText('@Theo Marsh')
    await expect(posted.locator('a[href^="user:"]')).toHaveCount(0)

    // In the app: one mention for Theo; nothing for Owen.
    // (The comment shows at once; the request lands a moment later.)
    await expect
      .poll(async () => (await theo.api.notifications()).map((item) => item.type))
      .toEqual(['mention'])
    const [notice] = await theo.api.notifications()
    const commentId = notice && 'comment' in notice ? notice.comment.id : ''
    // The posted comment (shown at once, then saved) carries that id.
    await expect(posted).toHaveAttribute('data-comment-id', commentId)
    expect(await owen.api.notifications()).toEqual([])

    // By email (immediate by default): who, where, the excerpt with @Name, the link.
    const mail = await emailTo(theo, /mentioned you/, since)
    expect(mail.Subject).toBe(`[${key}] Nora Quinn mentioned you on "${title}"`)
    const html = visibleText(mail.HTML)
    for (const text of [html, mail.Text]) {
      expect(text).toContain('@Theo Marsh can you check the courier API?')
      expect(text).not.toContain('user:')
    }
    expectNoScoreData('mention email', mail.Subject, html, mail.Text)
    const link = `${base}/ideas/${key}#comment-${commentId}`
    expect(links(mail)).toContain(link)
    expect(mail.Text).toContain(link)
    expect(await emailCount(owen, since)).toBe(0)

    // The email's link, as Theo: the idea opens at the comment.
    const theoPage = await (async () => {
      const context = await browser.newContext({ baseURL: test.info().project.use.baseURL })
      const opened = await context.newPage()
      await signInAs(opened, theo)
      return opened
    })()
    try {
      await theoPage.goto(link)
      const article = theoPage.locator(`article[data-comment-id="${commentId}"]`)
      await expect(article).toBeFocused()
      await expect(article).toBeInViewport()
    } finally {
      await theoPage.context().close()
    }
  } finally {
    await disposePeople(people)
  }
})

test('ME-02: only people with a role in the project are notified; never the author; an edit notifies only newcomers', async ({
  api,
}) => {
  const alice = await api('alice')
  const people = await newPeople(alice, ['nora', 'theo', 'lena', 'owen'])
  const { nora, theo, lena, owen } = people
  try {
    const { project, key } = await projectWithIdea(alice, 'Mention access', [nora, theo], {
      owner: nora,
    })
    await alice.addMemberUser(project.slug, lena.user, 'viewer') // a role, read-only

    // Private project: Owen can't see it. Nora mentions herself too.
    const { comment } = await nora.api.comment(
      key,
      `${token(theo)}, ${token(owen)} and ${token(nora)}: thoughts?`,
    )
    expect((await theo.api.notifications()).map((n) => n.type)).toEqual(['mention'])
    expect(await owen.api.notifications()).toEqual([])
    expect((await nora.api.notifications()).filter((n) => n.type === 'mention')).toEqual([])

    // Edited to add Lena (a viewer has a role): only Lena hears about it.
    await nora.api.send('PATCH', `/comments/${comment.id}`, {
      body_md: `${token(theo)}, ${token(owen)}, ${token(lena)} and ${token(nora)}: thoughts?`,
    })
    expect((await lena.api.notifications()).map((n) => n.type)).toEqual(['mention'])
    expect((await theo.api.notifications()).filter((n) => n.type === 'mention')).toHaveLength(1)
    expect(await owen.api.notifications()).toEqual([])

    // Internal project: Owen can view it but has no role there, so still nothing.
    const internalKey = uniqueKey('I')
    const internal = await alice.createProject({
      name: `Mentions internal ${internalKey}`,
      slug: `e2e-${internalKey.toLowerCase()}`,
      key: internalKey,
      visibility: 'internal',
    })
    await alice.addMemberUser(internal.slug, nora.user)
    const idea = await alice.createIdea(internal.slug, {
      title: `Open to all ${internalKey}`,
      summary: 'Anyone in the organisation can read this.',
    })
    expect((await owen.api.raw('GET', `/ideas/${idea.key}`)).status()).toBe(200)
    await nora.api.comment(idea.key, `${token(owen)} have a look?`)
    expect(await owen.api.notifications()).toEqual([])
  } finally {
    await disposePeople(people)
  }
})

test('ME-03: a mention can’t impersonate: labels are rewritten to the person’s name; unknown people become plain text', async ({
  page,
  api,
}) => {
  const alice = await api('alice')
  const people = await newPeople(alice, ['nora', 'theo'])
  const { nora, theo } = people
  try {
    const { key } = await createTeamProject(alice, 'Impersonation', {}).then(async (project) => {
      for (const person of [nora, theo]) await alice.addMemberUser(project.slug, person.user)
      const idea = await alice.createIdea(project.slug, {
        title: `Who said that ${project.key}`,
        summary: 'Labels are names.',
      })
      return { key: idea.key }
    })
    const ghost = '00000000-0000-4000-8000-00000000dead'
    const { comment } = await nora.api.comment(
      key,
      `@[Alice Anders (CEO)](user:${theo.user.id}) and @[Ghost](user:${ghost}) approve`,
    )
    expect(comment.body_md).toBe(`${token(theo)} and @Ghost approve`)
    const notice = (await theo.api.notifications()).find((n) => n.type === 'mention')
    expect(notice && 'comment' in notice ? notice.comment.excerpt : '').toBe(
      '@Theo Marsh and @Ghost approve',
    )

    await signInAs(page, theo)
    await openIdea(page, key)
    const article = page.locator(`article[data-comment-id="${comment.id}"]`)
    await expect(article.locator('[data-mention]')).toHaveText('@Theo Marsh')
    await expect(article).not.toContainText('CEO')
  } finally {
    await disposePeople(people)
  }
})
