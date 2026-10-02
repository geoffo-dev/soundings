import { defaultRubricScores, uniqueSuffix } from './support/api'
import { links, Mailpit, outboxSettled, requireEmail, visibleText } from './support/email'
import { expect, signIn, test } from './support/fixtures'
import { PHONE, projectWithPublicForm, Visitor } from './support/public'

/**
 * The submitter's tracking page (contract-phase4 §3.7–3.9) against the real stack: it
 * shows only what they sent, whatever the team does with the idea; the token never
 * reaches a URL the server sees; status emails on and off; the confirmation again; and
 * "Delete my details", after which the link is dead and only the idea stays. Test plan:
 * PT-*.
 */

const SENT_TITLE = 'Late-night opening on Fridays'
const SENT_SUMMARY = 'Stay open until 10pm on Fridays for shift workers.'

test('PT-01: the tracking page shows only what was sent, and its token stays in the fragment', async ({
  page,
  api,
  baseURL,
}) => {
  const alice = await api('alice')
  const project = await projectWithPublicForm(alice, 'Tracking secrecy', {
    bob: 'member',
    carol: 'member',
  })
  const visitor = await Visitor.open(baseURL ?? '')
  const receipt = await visitor.submitted(project.slug, {
    title: SENT_TITLE,
    summary: SENT_SUMMARY,
    description_md: 'Two stores first.',
    name: 'Sam Sender',
  })
  const [queued] = (await alice.moderationQueue(project.slug)).items
  const key = queued?.key ?? ''
  await alice.approve(key)
  // The team works on it: new text, an owner, evaluators and scores, a comment, a tag.
  await alice.send('PATCH', `/ideas/${key}`, {
    title: 'Friday late opening (pilot: Leeds, Bristol)',
    summary: 'INTERNAL: margin is thin after 8pm; Finance to confirm.',
    description_md: 'Staff rota impact: two extra shifts.',
    tags: ['opening-hours'],
  })
  await alice.setOwner(key, 'bob')
  await alice.changeStatus(key, 'evaluating')
  await alice.invite(key, ['carol'])
  const carol = await api('carol')
  await carol.evaluate(key, defaultRubricScores(4, 3, 3, 4, 2), {
    recommendation: 'go',
    comment: 'Worth a pilot in two stores.',
  })
  await alice.comment(key, 'Internal note: talk to the union first.')

  const tracked = await visitor.tracked(receipt.tracking_token)
  await visitor.dispose()
  expect(Object.keys(tracked).sort()).toEqual(
    [
      'branding',
      'can_resend_verification',
      'email_hint',
      'email_verified',
      'held_for',
      'history',
      'project',
      'resolution',
      'status',
      'status_label',
      'submitted_at',
      'summary',
      'title',
      'wants_updates',
    ].sort(),
  )
  expect([tracked.title, tracked.summary, tracked.status_label]).toEqual([
    SENT_TITLE,
    SENT_SUMMARY,
    'Evaluating',
  ])
  const exposed = JSON.stringify(tracked)
  for (const internal of [
    key,
    'Leeds',
    'INTERNAL',
    'Staff rota',
    'opening-hours',
    'Bob Brown',
    'Carol Chen',
    'union',
    'Worth a pilot',
    'Sam Sender',
    alice.me.id,
  ]) {
    expect(exposed, internal).not.toContain(internal)
  }

  // In the browser: the page shows the same, and no request URL carries the token.
  const urls: string[] = []
  page.on('request', (request) => urls.push(request.url()))
  await page.goto(`/track#${receipt.tracking_token}`)
  await expect(page.getByRole('heading', { level: 1, name: SENT_TITLE })).toBeVisible()
  await expect(page.getByText(SENT_SUMMARY)).toBeVisible()
  const main = page.locator('main')
  for (const internal of [key, 'Leeds', 'INTERNAL', 'Bob Brown', 'Carol Chen', 'union']) {
    await expect(main).not.toContainText(internal)
  }
  await expect(main).not.toContainText(/\b[1-5]\.\d\b/)
  // The fragment stays (the link is meant to be bookmarked) and never reaches the server.
  expect(new URL(page.url()).hash).toBe(`#${receipt.tracking_token}`)
  // (A request URL never has a fragment: the browser doesn't send it.)
  expect(urls.filter((url) => url.includes(receipt.tracking_token))).toEqual([])
  const posted = urls.filter((url) => url.endsWith('/api/v1/public/track'))
  expect(posted.length).toBeGreaterThan(0)
  await page.reload()
  await expect(page.getByRole('heading', { level: 1, name: SENT_TITLE })).toBeVisible()
})

test('PT-02: updates on and off, the confirmation again, and “Delete my details”', async ({
  browser,
  api,
  baseURL,
}) => {
  const alice = await api('alice')
  await requireEmail(alice)
  const project = await projectWithPublicForm(
    alice,
    'Tracking actions',
    {},
    {
      form: { moderation_required: false },
    },
  )
  const address = `sam.${uniqueSuffix()}@example.com`
  const since = new Date()
  const visitor = await Visitor.open(baseURL ?? '')
  const receipt = await visitor.submitted(project.slug, {
    title: SENT_TITLE,
    summary: SENT_SUMMARY,
    name: 'Sam Sender',
    email: address,
    wants_updates: true,
  })
  const mailpit = new Mailpit()
  await mailpit.waitForMessage(address, { since, subject: /^Confirm your idea/ })

  const context = await browser.newContext({ ...PHONE, baseURL })
  const page = await context.newPage()
  await page.goto(`/track#${receipt.tracking_token}`)
  await expect(page.getByRole('heading', { level: 1, name: SENT_TITLE })).toBeVisible()
  await expect(page.getByText(/^s•••@example\.com · not confirmed yet$/)).toBeVisible()
  await expect(page.locator('main')).not.toContainText(address)
  // Unconfirmed: no status emails yet, whatever the switch says.
  const [idea] = (await alice.listIdeas(project.slug)).items
  await alice.changeStatus(idea?.key ?? '', 'evaluating')
  await outboxSettled(alice)
  expect(await mailpit.messagesTo(address, { since, subject: /is now/ })).toHaveLength(0)

  // The confirmation again: a second email, with a fresh confirmation link.
  await page.getByRole('button', { name: 'Send the confirmation email again' }).tap()
  await expect(page.getByText('Sent. It can take a minute to arrive.')).toBeVisible()
  await expect
    .poll(async () => (await mailpit.messagesTo(address, { since, subject: /^Confirm/ })).length)
    .toBe(2)
  const [latest] = await mailpit.messagesTo(address, { since, subject: /^Confirm/ })
  const message = await mailpit.message(latest?.ID ?? '')
  const verify = links(message).find((href) => href.includes('/verify#'))
  await page.goto(verify ?? '')
  await page.getByRole('button', { name: 'Confirm my email address' }).tap()
  await expect(
    page.getByRole('heading', { level: 1, name: 'Thanks, your address is confirmed' }),
  ).toBeVisible()
  // Confirmed and opted in: the next status change is emailed ...
  await alice.changeStatus(idea?.key ?? '', 'shortlisted')
  const shortlisted = await mailpit.waitForMessage(address, {
    since,
    subject: /is now Shortlisted/,
  })
  expect(visibleText(shortlisted.HTML)).toContain('Stop these emails')
  // ... until the switch is off.
  await page.goto(`/track#${receipt.tracking_token}`)
  const updates = page.getByRole('switch', { name: 'Email me when the status changes' })
  await expect(updates).toBeChecked()
  await updates.tap()
  await expect(updates).not.toBeChecked()
  await expect
    .poll(async () => (await visitor.tracked(receipt.tracking_token)).wants_updates)
    .toBe(false)
  await alice.changeStatus(idea?.key ?? '', 'proposal')
  await outboxSettled(alice)
  expect(await mailpit.messagesTo(address, { since, subject: /is now Proposal/ })).toHaveLength(0)

  // Delete my details: asked first, then gone; the link is dead, the idea stays.
  await page.reload()
  await page.getByRole('button', { name: 'Delete my details' }).tap()
  const dialog = page.getByRole('alertdialog', { name: 'Delete your details?' })
  await expect(dialog).toContainText('The idea stays with the team.')
  await dialog.getByRole('button', { name: 'Delete my details' }).tap()
  await expect(
    page.getByRole('heading', { level: 1, name: 'Your details are deleted' }),
  ).toBeFocused()
  await page.reload()
  await expect(
    page.getByRole('heading', { level: 1, name: 'We can’t find this submission' }),
  ).toBeVisible()
  const submission = await alice.submission(idea?.key ?? '')
  expect(submission.erased_at).not.toBeNull()
  expect(submission.name).toBeNull()
  expect((await alice.idea(idea?.key ?? '')).title).toBe(SENT_TITLE)
  const [entry] = await alice.audit({ action: 'submission.erase', target_id: idea?.id })
  expect(entry?.actor_id).toBeNull()
  expect(entry?.details).toMatchObject({ reason: 'submitter' })
  expect(JSON.stringify(entry)).not.toContain(address)
  expect(JSON.stringify(entry)).not.toContain('Sam Sender')
  // The admin's view of the idea says so too.
  const adminPage = await (await browser.newContext({ baseURL })).newPage()
  await signIn(adminPage, 'alice')
  await adminPage.goto(`/ideas/${idea?.key}`)
  await expect(adminPage.getByText(/Submitter’s details erased/)).toBeVisible()
  await expect(adminPage.getByRole('button', { name: /Erase submitter details/ })).toHaveCount(0)
  await adminPage.context().close()
  await context.close()
  await visitor.dispose()
})

test('PT-03: a confirmation link that doesn’t work changes nothing and says what to do', async ({
  page,
}) => {
  const posts: string[] = []
  page.on('request', (request) => {
    if (request.method() === 'POST') posts.push(new URL(request.url()).pathname)
  })
  // Opening the link posts nothing: mail scanners open links, some run JavaScript.
  await page.goto('/verify#eyJ2IjoxLCJzIjoiMDAwIn0.Zm9yZ2Vk')
  await expect(
    page.getByRole('heading', { level: 1, name: 'Confirm your email address' }),
  ).toBeVisible()
  await expect(page.getByText('Wasn’t you? Close this page')).toBeVisible()
  expect(posts).toEqual([])
  await page.getByRole('button', { name: 'Confirm my email address' }).click()
  await expect(
    page.getByRole('heading', { level: 1, name: 'This link has expired or isn’t valid' }),
  ).toBeVisible()
  await expect(page.getByText('Open your private tracking link')).toBeVisible()
  expect(posts).toEqual(['/api/v1/public/verify-email'])
  // Without a token at all.
  await page.goto('/verify')
  await expect(
    page.getByRole('heading', { level: 1, name: 'This link has expired or isn’t valid' }),
  ).toBeVisible()
})
