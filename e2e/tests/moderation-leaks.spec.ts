import type { Page } from '@playwright/test'

import { uniqueSuffix, type Api, type Person, type Project } from './support/api'
import { Mailpit, links, requireEmail } from './support/email'
import { expect, heading, signIn, test, toast } from './support/fixtures'
import { fragmentToken, projectWithPublicForm, Visitor } from './support/public'

/**
 * Held ideas (contract-phase4 §3.6; role matrix c12, c19) against the real stack: an idea
 * waiting for moderation or for its sender's email confirmation is on no board, list,
 * search, count, My work or inbox, for anyone; members get a 404 for its page, admins a
 * read-only page with Approve / Reject; nothing can change it until it is approved.
 * Test plan: ML-*.
 */

// A list row is named from its key; a board card "Title (KEY)" (Phase 7).
const ideaLink = (scope: Page, key: string) =>
  scope.getByRole('link', { name: new RegExp(`^${key}\\b|\\(${key}\\)$`) })

interface Held {
  project: Project
  key: string
  title: string
  visible: string
  token: string
}

/**
 * A project (Alice admin, Bob member, Erin viewer) with one ordinary idea and one sent
 * through its moderated public form, still waiting. Titles carry a run-unique word.
 */
async function heldIdea(alice: Api, baseURL: string): Promise<Held> {
  const word = `kiosk${uniqueSuffix()}`
  const project = await projectWithPublicForm(alice, 'Held ideas', {
    bob: 'member',
    erin: 'viewer',
  })
  const visible = await alice.createIdea(project.slug, {
    title: `Visible ${word} idea`,
    summary: 'An idea the team wrote.',
    tags: ['stores'],
  })
  const visitor = await Visitor.open(baseURL)
  const receipt = await visitor.submitted(project.slug, {
    title: `Held ${word} self-checkout`,
    summary: 'Self-checkout kiosks in every store.',
  })
  await visitor.dispose()
  expect(receipt.held_for).toBe('moderation')
  const [queued] = (await alice.moderationQueue(project.slug)).items
  if (!queued) throw new Error('nothing in the queue')
  return {
    project,
    key: queued.key,
    title: queued.title,
    visible: visible.key,
    token: receipt.tracking_token,
  }
}

/** Every list, count and search the API has, for `client`: the held key must be absent. */
async function expectAbsentEverywhere(client: Api, held: Held, word: string) {
  const who = client.me.display_name
  const slug = held.project.slug
  const list = await client.listIdeas(slug, 'limit=100')
  expect(
    list.items.map((idea) => idea.key),
    `${who}: list`,
  ).not.toContain(held.key)
  expect(
    list.items.map((idea) => idea.key),
    `${who}: list`,
  ).toContain(held.visible)
  const board = await client.get<{ columns: { items: { key: string }[]; count?: number }[] }>(
    `/projects/${slug}/board`,
  )
  const onBoard = board.columns.flatMap((column) => column.items.map((item) => item.key))
  expect(onBoard, `${who}: board`).not.toContain(held.key)
  expect(onBoard, `${who}: board`).toEqual([held.visible])
  expect((await client.project(slug)).idea_count, `${who}: idea_count`).toBe(1)
  const search = await client.get<{ ideas: { key: string }[] }>(`/search?q=${word}`)
  expect(
    search.ideas.map((idea) => idea.key),
    `${who}: search`,
  ).toEqual([held.visible])
  const work = JSON.stringify(await client.get('/me/work'))
  expect(work, `${who}: My work`).not.toContain(held.key)
  const owned = JSON.stringify(await client.get('/me/owned-ideas'))
  expect(owned, `${who}: owned ideas`).not.toContain(held.key)
  const tags = JSON.stringify(await client.get(`/projects/${slug}/tags`))
  expect(tags, `${who}: tags`).not.toContain(held.key)
  const inbox = JSON.stringify(await client.notifications())
  expect(inbox, `${who}: inbox`).not.toContain(held.key)
  expect(inbox, `${who}: inbox`).not.toContain(held.title)
}

test('ML-01: an idea waiting for review is on no list, board, search, count or inbox, for anyone', async ({
  page,
  api,
  baseURL,
}) => {
  const alice = await api('alice')
  const held = await heldIdea(alice, baseURL ?? '')
  const word = held.title.split(' ')[1] ?? ''
  for (const person of ['bob', 'erin', 'alice'] as Person[]) {
    await expectAbsentEverywhere(await api(person), held, word)
  }
  // A member: the board, the list, ⌘K, My work and the bell show nothing of it.
  await signIn(page, 'bob')
  await page.goto(`/p/${held.project.slug}?view=board`)
  await expect(ideaLink(page, held.visible)).toBeVisible()
  await expect(ideaLink(page, held.key)).toHaveCount(0)
  await expect(page.getByText(/waiting for review/)).toHaveCount(0)
  await page.goto(`/p/${held.project.slug}?view=list`)
  await expect(ideaLink(page, held.visible)).toBeVisible()
  await expect(page.locator('main')).not.toContainText(held.title)
  await page.keyboard.press('ControlOrMeta+k')
  const palette = page.getByRole('dialog', { name: 'Command palette' })
  await expect(palette.getByRole('combobox')).toBeFocused()
  await page.keyboard.type(word)
  await expect(palette.getByRole('option', { name: new RegExp(`Visible ${word}`) })).toBeVisible()
  await expect(palette.getByRole('option', { name: new RegExp(`Held ${word}`) })).toHaveCount(0)
  await page.keyboard.press('Escape')
  await page.goto('/')
  await expect(heading(page, 'My work')).toBeVisible()
  await expect(page.locator('main')).not.toContainText(held.key)
  // Its page, by link: a member gets the plain 404 page.
  await page.goto(`/ideas/${held.key}`)
  await expect(
    page.getByRole('heading', { name: 'This idea doesn’t exist or you don’t have access' }),
  ).toBeVisible()
  await expect(page.locator('main')).not.toContainText(held.title)
  const bob = await api('bob')
  for (const path of [
    `/ideas/${held.key}`,
    `/ideas/${held.key}/activity`,
    `/ideas/${held.key}/submission`,
    `/ideas/${held.key}/proposal`,
  ]) {
    expect((await bob.raw('GET', path)).status(), path).toBe(404)
  }
  expect((await bob.raw('GET', `/projects/${held.project.slug}/moderation`)).status()).toBe(403)
  const erin = await api('erin')
  expect((await erin.raw('GET', `/ideas/${held.key}`)).status()).toBe(404)
})

test('ML-02: admins see it only in the queue and on its own read-only page; writes wait', async ({
  page,
  api,
  baseURL,
}) => {
  const alice = await api('alice')
  const held = await heldIdea(alice, baseURL ?? '')
  // Read-only for admins: every permission but delete is off, and writes are 409.
  const detail = await alice.idea(held.key)
  expect(detail.held_for).toBe('moderation')
  expect(detail.via_public_form).toBe(true)
  const allowed = Object.entries(detail.permissions)
    .filter(([, value]) => value === true)
    .map(([name]) => name)
  expect(allowed).toEqual(['can_delete'])
  await alice.addMember(held.project.slug, 'dave')
  const dave = await api('dave')
  for (const [method, path, body] of [
    ['POST', `/ideas/${held.key}/status`, { status: 'evaluating' }],
    ['PATCH', `/ideas/${held.key}`, { title: 'Edited' }],
    ['PUT', `/ideas/${held.key}/owner`, { user_id: dave.me.id }],
    ['POST', `/ideas/${held.key}/comments`, { body_md: 'A comment' }],
    ['PUT', `/ideas/${held.key}/vote`, undefined],
    ['PUT', `/ideas/${held.key}/watch`, undefined],
    ['POST', `/ideas/${held.key}/evaluators`, { user_ids: [dave.me.id] }],
    ['POST', `/ideas/${held.key}/proposal`, undefined],
  ] as const) {
    const response = await alice.raw(method, path, body)
    expect(response.status(), `${method} ${path}`).toBe(409)
    expect(((await response.json()) as { code: string }).code, path).toBe('awaiting_moderation')
  }
  expect((await alice.idea(held.key)).title).toBe(held.title)

  // The board's notice, the queue, the idea's page with its banner.
  await signIn(page, 'alice')
  await page.goto(`/p/${held.project.slug}?view=board`)
  await expect(ideaLink(page, held.key)).toHaveCount(0)
  await expect(page.getByText('1 idea from the public form is waiting for review.')).toBeVisible()
  await page.goto(`/ideas/${held.key}`)
  await expect(heading(page, held.title)).toBeVisible()
  const banner = page.getByRole('region', { name: 'Waiting for review' })
  await expect(banner).toContainText('Only project admins can see it')
  await expect(banner.getByRole('button', { name: 'Approve' })).toBeVisible()
  await expect(banner.getByRole('button', { name: 'Reject' })).toBeVisible()
  await expect(page.getByRole('button', { name: /^Watch/ })).toHaveCount(0)
  await expect(page.getByRole('textbox', { name: 'Write a comment' })).toHaveCount(0)

  // Approved from its page: it's in New, first by activity, for members too.
  await banner.getByRole('button', { name: 'Approve' }).click()
  await expect(toast(page, `${held.key} approved`)).toBeVisible()
  await expect
    .poll(async () => (await alice.moderationQueue(held.project.slug)).total, {
      timeout: 20_000,
    })
    .toBe(0)
  const board = await dave.get<{ columns: { status: string; items: { key: string }[] }[] }>(
    `/projects/${held.project.slug}/board`,
  )
  const fresh = board.columns.find((column) => column.status === 'new')
  expect(fresh?.items[0]?.key).toBe(held.key)
  expect((await dave.idea(held.key)).held_for).toBeNull()
  // Writes work again.
  await alice.changeStatus(held.key, 'evaluating')
})

test('ML-03: a rejected idea is deleted; its tracking link says so', async ({
  page,
  api,
  baseURL,
}) => {
  const alice = await api('alice')
  const held = await heldIdea(alice, baseURL ?? '')
  await signIn(page, 'alice')
  await page.goto(`/p/${held.project.slug}/review`)
  const item = page.getByRole('article').filter({ hasText: held.title })
  await item.getByRole('button', { name: `Reject and delete ${held.key}` }).click()
  await expect(toast(page, `${held.key} rejected and deleted`)).toBeVisible()
  await expect(item).toHaveCount(0)
  await expect
    .poll(async () => (await alice.raw('GET', `/ideas/${held.key}`)).status(), {
      timeout: 20_000,
    })
    .toBe(404)
  await expect(page.getByRole('heading', { name: 'Nothing waiting for review' })).toBeVisible()
  const visitor = await Visitor.open(baseURL ?? '')
  expect((await visitor.track(held.token)).status()).toBe(404)
  await visitor.dispose()
  await page.goto(`/track#${held.token}`)
  await expect(
    page.getByRole('heading', { level: 1, name: 'We can’t find this submission' }),
  ).toBeVisible()
  await expect(page.getByText('It may have been removed')).toBeVisible()
})

test('ML-04: an idea waiting for its sender’s confirmation is invisible even to admins', async ({
  page,
  api,
  baseURL,
}) => {
  const alice = await api('alice')
  await requireEmail(alice)
  const project = await projectWithPublicForm(
    alice,
    'Confirm first',
    { bob: 'member' },
    {
      form: { require_email_verification: true, moderation_required: true },
    },
  )
  const address = `sender.${uniqueSuffix()}@example.com`
  const since = new Date()
  const visitor = await Visitor.open(baseURL ?? '')
  const receipt = await visitor.submitted(project.slug, {
    title: 'Click and collect lockers',
    summary: 'Parcel lockers in the car park.',
    email: address,
  })
  expect(receipt.held_for).toBe('email_verification')
  // Nowhere: not in the queue, no page, no count, for the project and platform admin.
  expect((await alice.moderationQueue(project.slug)).total).toBe(0)
  expect((await alice.project(project.slug)).idea_count).toBe(0)
  expect((await alice.publicForm(project.slug)).awaiting_moderation).toBe(0)
  expect((await alice.raw('GET', `/ideas/${project.key}-1`)).status()).toBe(404)
  // The receipt and tracking page say what to do.
  const tracked = await visitor.tracked(receipt.tracking_token)
  expect(tracked.held_for).toBe('email_verification')
  await page.goto(`/track#${receipt.tracking_token}`)
  await expect(
    page.getByText('Waiting for you to confirm your email address', { exact: true }),
  ).toBeVisible()
  // Confirmed (also after the form is turned off): now it waits for review.
  const mail = await new Mailpit().waitForMessage(address, {
    since,
    subject: `Confirm your idea for ${project.name}`,
  })
  const verify = links(mail).find((href) => href.includes('/verify#'))
  if (!verify) throw new Error('no confirmation link')
  await alice.updatePublicForm(project.slug, { enabled: false })
  const verified = await visitor.verify(fragmentToken(verify))
  expect(verified.held_for).toBe('moderation')
  await visitor.dispose()
  expect((await alice.moderationQueue(project.slug)).total).toBe(1)
  const bob = await api('bob')
  expect((await bob.listIdeas(project.slug)).items).toEqual([])
  expect((await bob.raw('GET', `/ideas/${project.key}-1`)).status()).toBe(404)
})
