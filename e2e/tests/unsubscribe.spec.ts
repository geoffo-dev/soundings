import { request } from '@playwright/test'

import { daysFromNow, type Api, type UnsubscribeInfo } from './support/api'
import {
  disposePeople,
  emailCount,
  emailTo,
  Mailpit,
  newPeople,
  projectWithIdea,
  requireEmail,
  unsubscribeAllLink,
  unsubscribeLink,
  type Someone,
} from './support/email'
import { expect, test } from './support/fixtures'

/**
 * Unsubscribe links (contract-phase3 §3.5) from real emails: the footer link opens the
 * public page, which changes nothing until confirmed; the List-Unsubscribe header's URL
 * redirects a browser to the page and takes a mail client's one-click POST without
 * cookies; links keep working (idempotent); broken or forged tokens get a calm "doesn't
 * work" page and a 404 from the API. The browser here is never signed in, like a mail
 * client's. Test plan: UN-*.
 */

const API = '/api/v1'

async function modes(person: Someone): Promise<Record<string, string>> {
  const preferences = await person.api.preferences()
  return Object.fromEntries(preferences.items.map((item) => [item.type, item.mode]))
}

/** Invites `person` to a new idea in `slug` and returns the invitation email. */
async function invitation(alice: Api, slug: string, person: Someone, title: string) {
  const idea = await alice.createIdea(slug, { title, summary: 'Short and sweet.' })
  await alice.changeStatus(idea.key, 'evaluating')
  const since = new Date()
  await alice.inviteUsers(idea.key, [person.user], daysFromNow(6))
  return { key: idea.key, mail: await emailTo(person, /Please evaluate/, since), since }
}

test('UN-01: the email’s footer link opens the page; nothing changes until “Unsubscribe”; later invitations stay in-app', async ({
  page,
  api,
}) => {
  const alice = await api('alice')
  await requireEmail(alice)
  const people = await newPeople(alice, ['theo'])
  const { theo } = people
  try {
    const { project } = await projectWithIdea(alice, 'Unsubscribe', [theo])
    const { mail } = await invitation(alice, project.slug, theo, `Gift returns ${project.key}`)
    const link = unsubscribeLink(mail)
    expect(mail.Text).toContain(link) // the text part has the same link
    expect(link).toMatch(/\/unsubscribe\?token=[A-Za-z0-9_.-]{16,512}$/)

    await page.goto(link)
    // The type named as the email's footer names it (“Unsubscribe from evaluation requests”).
    await expect(
      page.getByRole('heading', { level: 1, name: 'Unsubscribe from evaluation requests?' }),
    ).toBeVisible()
    await expect(page.getByText(`${theo.email[0]}•••@example.com`)).toBeVisible()
    await expect(page.locator('body')).not.toContainText(theo.email)
    await expect(page).toHaveTitle('Unsubscribe · Soundings')
    // Opening the link (a scanner prefetching it) changed nothing.
    expect((await modes(theo)).evaluator_invited).toBe('immediate')

    await page.getByRole('button', { name: 'Unsubscribe', exact: true }).click()
    await expect(page.getByRole('heading', { level: 1, name: 'You’re unsubscribed' })).toBeFocused()
    await expect(
      page.getByText(
        `Soundings won’t email ${theo.email[0]}•••@example.com about evaluation requests any more.`,
      ),
    ).toBeVisible()
    expect(await modes(theo)).toMatchObject({ evaluator_invited: 'off', mention: 'immediate' })

    // The next invitation: in the inbox, not in the mail.
    const idea = await alice.createIdea(project.slug, {
      title: `Exchange first ${project.key}`,
      summary: 'Offer an exchange.',
    })
    await alice.changeStatus(idea.key, 'evaluating')
    const since = new Date()
    await alice.inviteUsers(idea.key, [theo.user])
    expect((await theo.api.notifications()).filter((n) => n.idea.key === idea.key)).toHaveLength(1)
    expect(
      (await alice.outbox({ type: 'evaluator_invited' })).filter(
        (email) => email.recipient?.id === theo.user.id && email.idea?.key === idea.key,
      ),
    ).toEqual([])
    await page.waitForTimeout(2000)
    expect(await emailCount(theo, since)).toBe(0)
  } finally {
    await disposePeople(people)
  }
})

test('UN-02: the same link again says “already unsubscribed”; it can’t turn off all email, the footer’s “all email” link does', async ({
  page,
  api,
  baseURL,
}) => {
  const alice = await api('alice')
  await requireEmail(alice)
  const people = await newPeople(alice, ['iris'])
  const { iris } = people
  try {
    const { project } = await projectWithIdea(alice, 'Unsubscribe again', [iris])
    const { mail } = await invitation(alice, project.slug, iris, `Gift returns ${project.key}`)
    const link = unsubscribeLink(mail)

    await page.goto(link)
    await page.getByRole('button', { name: 'Unsubscribe', exact: true }).click()
    await expect(page.getByRole('heading', { level: 1, name: 'You’re unsubscribed' })).toBeVisible()

    // Reused: the link still works and says where things stand.
    await page.goto(link)
    await expect(
      page.getByRole('heading', { level: 1, name: 'You’re already unsubscribed' }),
    ).toBeVisible()
    await expect(page.getByRole('button', { name: /all Soundings email/ })).toHaveCount(0)

    // A type's link can't be widened to every email (lead decision L8): 403, no change.
    const client = await request.newContext({ baseURL })
    try {
      const token = new URL(link).searchParams.get('token') ?? ''
      const widened = await client.post(`${API}/unsubscribe?token=${token}&all=true`)
      expect(widened.status()).toBe(403)
      expect(((await widened.json()) as { code: string }).code).toBe('insufficient_scope')
    } finally {
      await client.dispose()
    }
    const afterOne = await modes(iris)
    expect(afterOne.evaluator_invited).toBe('off')
    expect(afterOne.owner_assigned).toBe('immediate')

    // The footer's “Unsubscribe from all email” link turns every type off.
    const all = unsubscribeAllLink(mail)
    expect(all).not.toBe(link)
    expect(mail.Text).toContain(`Unsubscribe from all email: ${all}`)
    await page.goto(all)
    await expect(
      page.getByRole('heading', { level: 1, name: 'Unsubscribe from all Soundings email?' }),
    ).toBeVisible()
    await page.getByRole('button', { name: 'Unsubscribe', exact: true }).click()
    await expect(
      page.getByText(/^Soundings won’t email \S+•••@example\.com any more\./),
    ).toBeVisible()
    expect(new Set(Object.values(await modes(iris)))).toEqual(new Set(['off']))

    // "Email preferences" leads to sign-in, then the preferences page.
    await page.getByRole('link', { name: 'Email preferences' }).click()
    await expect(page).toHaveURL(/\/login\?next=%2Fsettings%2Fnotifications/)
  } finally {
    await disposePeople(people)
  }
})

test('UN-03: the List-Unsubscribe URL: a browser lands on the page; a one-click POST without cookies unsubscribes', async ({
  page,
  api,
  baseURL,
}) => {
  const alice = await api('alice')
  await requireEmail(alice)
  const people = await newPeople(alice, ['owen'])
  const { owen } = people
  try {
    const { project } = await projectWithIdea(alice, 'One-click', [owen])
    const { mail } = await invitation(alice, project.slug, owen, `Gift returns ${project.key}`)
    const headers = await new Mailpit().headers(mail.ID)
    const header = headers['List-Unsubscribe']?.[0] ?? ''
    const url = /^<([^>]+)>$/.exec(header)?.[1] ?? ''
    expect(url).toContain('/api/v1/unsubscribe?token=')
    const token = new URL(url).searchParams.get('token') ?? ''
    expect(unsubscribeLink(mail)).toContain(`token=${token}`) // the same token as the footer
    expect(headers['List-Unsubscribe-Post']).toEqual(['List-Unsubscribe=One-Click'])

    // A browser opening the header's URL is sent to the page (303), which changes nothing.
    await page.goto(url)
    await expect(page).toHaveURL(new RegExp(`/unsubscribe\\?token=${token}$`))
    await expect(
      page.getByRole('heading', { level: 1, name: 'Unsubscribe from evaluation requests?' }),
    ).toBeVisible()
    expect((await modes(owen)).evaluator_invited).toBe('immediate')

    // A mail client: POST with the RFC 8058 form body, no cookies, no CSRF token.
    const client = await request.newContext({ baseURL })
    try {
      for (let attempt = 0; attempt < 2; attempt++) {
        const response = await client.post(new URL(url).pathname + new URL(url).search, {
          headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
          data: 'List-Unsubscribe=One-Click',
        })
        expect(response.status()).toBe(200) // idempotent
        const info = (await response.json()) as UnsubscribeInfo
        expect(info).toMatchObject({ scope: 'evaluator_invited', unsubscribed: true })
        expect(info.email_hint).toBe(`${owen.email[0]}•••@example.com`)
      }
    } finally {
      await client.dispose()
    }
    expect((await modes(owen)).evaluator_invited).toBe('off')
  } finally {
    await disposePeople(people)
  }
})

test('UN-04: forged, truncated and malformed links don’t work, and change nothing', async ({
  page,
  api,
  baseURL,
}) => {
  const alice = await api('alice')
  await requireEmail(alice)
  const people = await newPeople(alice, ['lena', 'ravi'])
  const { lena, ravi } = people
  try {
    const { project } = await projectWithIdea(alice, 'Forged', [lena, ravi])
    const { mail } = await invitation(alice, project.slug, lena, `Gift returns ${project.key}`)
    const token = new URL(unsubscribeLink(mail)).searchParams.get('token') ?? ''
    const [payload = '', signature = ''] = token.split('.')
    // Someone else's id in the payload, with Lena's signature.
    const decoded = JSON.parse(Buffer.from(payload, 'base64url').toString()) as { u: string }
    const forgedPayload = Buffer.from(
      JSON.stringify({ ...decoded, u: ravi.user.id }).replace(/\s/g, ''),
    ).toString('base64url')
    const lastChar = signature.at(-1) === 'A' ? 'B' : 'A'
    const broken = [
      `${forgedPayload}.${signature}`, // another user
      `${payload}.${signature.slice(0, -1)}${lastChar}`, // tampered signature
      token.slice(0, Math.floor(token.length / 2)), // truncated
      'not a token!',
    ]

    const client = await request.newContext({ baseURL })
    try {
      for (const bad of broken) {
        const query = `token=${encodeURIComponent(bad)}`
        const get = await client.get(`${API}/unsubscribe?${query}`, {
          headers: { Accept: 'application/json' },
        })
        expect([404, 422], bad).toContain(get.status())
        expect(get.headers()['content-type']).toContain('application/problem+json')
        const post = await client.post(`${API}/unsubscribe?${query}&all=true`)
        expect([404, 422], bad).toContain(post.status())

        await page.goto(`/unsubscribe?${query}`)
        await expect(
          page.getByRole('heading', { level: 1, name: 'This unsubscribe link doesn’t work' }),
        ).toBeVisible()
        await expect(
          page.getByRole('link', { name: 'Sign in to your email preferences' }),
        ).toHaveAttribute('href', '/login?next=%2Fsettings%2Fnotifications')
      }
    } finally {
      await client.dispose()
    }
    for (const person of [lena, ravi]) {
      expect(new Set(Object.values(await modes(person))), person.name).not.toContain('off')
    }
  } finally {
    await disposePeople(people)
  }
})
