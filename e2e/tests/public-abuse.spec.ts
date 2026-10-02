import type { APIResponse } from '@playwright/test'

import { createTeamProject, uniqueSuffix, type AltchaChallenge, type Api } from './support/api'
import { Mailpit, outboxSettled } from './support/email'
import { expect, test } from './support/fixtures'
import {
  fillPublicForm,
  humanCheckDone,
  PHONE,
  projectWithPublicForm,
  solveAltcha,
  Visitor,
} from './support/public'

/**
 * Public-form anti-abuse against the real stack (contract-phase4 §1, §3.5, §3.7): the
 * honeypot, replayed and foreign ALTCHA solutions, the identical 404 of a form that isn't
 * available, JSON-only writes, and the per-address throttles. Test plan: PA-*.
 *
 * The rules are unit-tested by identity (backend/tests/public/); these show them through
 * the browser and the deployed app (proxy headers, the SPA's recovery and messages).
 *
 * Every request of the run comes from 127.0.0.1, which the stack's API trusts as its
 * proxy (one hop, the Phase 2 default): PA-05 exhausts the tracking and challenge
 * throttles as a client address of its own (X-Forwarded-For, a random IPv6 /64), so the
 * rest of the run is unaffected, and waits until they let it through again. PA-06 needs
 * a stack started with a low per-address submission limit (`E2E_PUBLIC_PER_IP=5`); with
 * the default (1000) it skips. An untrusted peer's own X-Forwarded-For can't be shown from
 * here (every peer is the trusted loopback): backend tests/test_proxy_headers.py and
 * tests/public/test_submit.py cover it.
 */

const API = '/api/v1/public'

async function problem(response: APIResponse, status: number, code: string) {
  const body = (await response.json()) as { code: string; request_id?: string; instance?: string }
  expect(response.status(), JSON.stringify(body)).toBe(status)
  expect(body.code).toBe(code)
  // What differs between any two answers: the request id, and the path asked for.
  return { ...body, request_id: undefined, instance: undefined }
}

async function ideaCount(admin: Api, slug: string): Promise<number> {
  return (await admin.project(slug)).idea_count
}

test.describe('PA-01: the honeypot', () => {
  test('a filled honeypot gets a normal-looking receipt and nothing is kept', async ({
    browser,
    api,
    baseURL,
  }) => {
    const alice = await api('alice')
    const project = await projectWithPublicForm(
      alice,
      'Honeypot',
      {},
      {
        form: { moderation_required: false },
      },
    )
    const address = `bot.${uniqueSuffix()}@example.com`
    const email = (await alice.notificationSummary()).email_available
    const since = new Date()
    const context = await browser.newContext({ ...PHONE, baseURL })
    const page = await context.newPage()
    await page.goto(`/${project.slug}/submit`)
    await fillPublicForm(page, {
      title: 'Cheap watches',
      summary: 'Buy cheap watches here.',
      // Without SMTP the form asks for no address at all.
      ...(email ? { email: address, updates: true } : {}),
    })
    // What an autofilling bot does: the off-screen field, hidden from people and AT.
    const honeypot = page.locator('#hp_ref')
    await expect(honeypot).toHaveAttribute('tabindex', '-1')
    await expect(honeypot).toHaveAttribute('autocomplete', 'off')
    await expect(page.locator('[aria-hidden="true"]:has(#hp_ref)')).toHaveCount(1)
    await honeypot.fill('https://spam.example/watches', { force: true })
    await humanCheckDone(page)
    const posted = page.waitForRequest((request) => request.url().endsWith('/submissions'))
    await page.getByRole('button', { name: 'Send idea' }).tap()
    expect((await posted).postDataJSON()).toMatchObject({ website: 'https://spam.example/watches' })
    // A receipt like any other: a private link, "the team can see it now".
    await expect(
      page.getByRole('heading', { level: 1, name: 'Thanks! Your idea is in' }),
    ).toBeVisible()
    await expect(page.getByText('The team can see it now')).toBeVisible()
    const link = await page.getByRole('textbox', { name: 'Your private link' }).inputValue()
    expect(link).toMatch(/\/track#[A-Za-z0-9_-]{43}$/)
    // ... that tracks nothing; no idea, no email.
    await page.getByRole('link', { name: 'Open your tracking page' }).tap()
    await expect(
      page.getByRole('heading', { level: 1, name: 'We can’t find this submission' }),
    ).toBeVisible()
    expect(await ideaCount(alice, project.slug)).toBe(0)
    expect((await alice.listIdeas(project.slug)).items).toEqual([])
    if (email) {
      await outboxSettled(alice)
      expect(await new Mailpit().messagesTo(address, { since })).toHaveLength(0)
    }
    await context.close()
  })

  test('any honeypot value (5,000 characters) is accepted alike; checks before it still apply', async ({
    api,
    baseURL,
  }) => {
    const alice = await api('alice')
    const project = await projectWithPublicForm(alice, 'Honeypot API', {})
    const visitor = await Visitor.open(baseURL ?? '')
    try {
      const real = await visitor.submitted(project.slug, {
        title: 'Refill stations',
        summary: 'Refill stations for cleaning products.',
      })
      const lookalike = await visitor.submitted(project.slug, {
        title: 'Spam',
        summary: 'Spam.',
        website: 'x'.repeat(5000),
      })
      // The same shape and values as a real receipt (held for moderation here).
      expect(Object.keys(lookalike).sort()).toEqual(Object.keys(real).sort())
      expect(lookalike.held_for).toBe(real.held_for)
      expect(lookalike.email_sent).toBe(real.email_sent)
      expect(lookalike.tracking_token).toMatch(/^[A-Za-z0-9_-]{43}$/)
      expect((await visitor.track(lookalike.tracking_token)).status()).toBe(404)
      expect((await visitor.track(real.tracking_token)).status()).toBe(200)
      expect((await alice.moderationQueue(project.slug)).total).toBe(1)
      // A filled honeypot with a bad proof of work: 422, exactly as a real submission.
      const bad = await visitor.submit(project.slug, {
        title: 'Spam',
        summary: 'Spam.',
        website: 'https://spam.example',
        altcha: Buffer.from('{"challenge":{},"solution":{}}').toString('base64'),
      })
      await problem(bad, 422, 'challenge_failed')
    } finally {
      await visitor.dispose()
    }
  })
})

test.describe('PA-02: ALTCHA solutions are accepted once, for their own form', () => {
  test('a replayed, foreign, tampered or malformed solution is 422 challenge_failed', async ({
    api,
    baseURL,
  }) => {
    const alice = await api('alice')
    const first = await projectWithPublicForm(alice, 'Replay', {})
    const other = await projectWithPublicForm(alice, 'Replay other', {})
    const visitor = await Visitor.open(baseURL ?? '')
    try {
      const payload = await visitor.solve(first.slug)
      const fields = { title: 'Water refill points', summary: 'Free water refills in store.' }
      expect((await visitor.submit(first.slug, { ...fields, altcha: payload })).status()).toBe(201)
      // The same solution again (also with other fields, also as a honeypot hit).
      await problem(
        await visitor.submit(first.slug, { ...fields, altcha: payload }),
        422,
        'challenge_failed',
      )
      await problem(
        await visitor.submit(first.slug, { title: 'Other', summary: 'Other.', altcha: payload }),
        422,
        'challenge_failed',
      )
      // A challenge fetched for another project's form.
      const foreign = await visitor.solve(other.slug)
      await problem(
        await visitor.submit(first.slug, { ...fields, altcha: foreign }),
        422,
        'challenge_failed',
      )
      // Tampered parameters (a later expiry: the signature no longer matches).
      const challenge = (await (await visitor.challenge(first.slug)).json()) as AltchaChallenge
      const tampered = await solveAltcha({
        ...challenge,
        parameters: { ...challenge.parameters, expiresAt: challenge.parameters.expiresAt + 3600 },
      })
      await problem(
        await visitor.submit(first.slug, { ...fields, altcha: tampered }),
        422,
        'challenge_failed',
      )
      // Malformed.
      await problem(
        await visitor.submit(first.slug, { ...fields, altcha: 'not-base64-json' }),
        422,
        'challenge_failed',
      )
      expect((await alice.moderationQueue(first.slug)).total).toBe(1)
      expect((await alice.moderationQueue(other.slug)).total).toBe(0)
    } finally {
      await visitor.dispose()
    }
  })

  test('the form recovers by itself when the server refuses a solution', async ({
    page,
    api,
    baseURL,
  }) => {
    const alice = await api('alice')
    const project = await projectWithPublicForm(alice, 'Replay UI', {})
    const visitor = await Visitor.open(baseURL ?? '')
    // A solution already used once: the browser's first send carries it instead of its own.
    const used = await visitor.solve(project.slug)
    await visitor.submitted(project.slug, { title: 'First', summary: 'First.', altcha: used })
    await visitor.dispose()
    const sent: string[] = []
    let replayed = false
    await page.route('**/api/v1/public/projects/*/submissions', async (route) => {
      const body = route.request().postDataJSON() as Record<string, unknown>
      if (!replayed) {
        replayed = true
        body.altcha = used
      }
      sent.push(String(body.altcha))
      await route.continue({ postData: JSON.stringify(body) })
    })
    await page.goto(`/${project.slug}/submit`)
    await fillPublicForm(page, { title: 'Bike parking', summary: 'Covered bike parking.' })
    await humanCheckDone(page)
    await page.getByRole('button', { name: 'Send idea' }).click()
    // Refused once (422 challenge_failed), a new challenge solved, sent again: accepted.
    await expect(
      page.getByRole('heading', { level: 1, name: 'Thanks! Your idea is in' }),
    ).toBeVisible({
      timeout: 30_000,
    })
    expect(sent).toHaveLength(2)
    expect(sent[0]).toBe(used)
    expect(sent[1]).not.toBe(used)
    const queue = await alice.moderationQueue(project.slug)
    expect(queue.items.map((item) => item.title).sort()).toEqual(['Bike parking', 'First'])
  })
})

test.describe('PA-03: a form that isn’t available', () => {
  test('off, archived, unknown and reserved read the same 404, in the API and the page', async ({
    page,
    api,
    baseURL,
  }) => {
    const alice = await api('alice')
    const off = await createTeamProject(alice, 'Form off', {})
    const archived = await projectWithPublicForm(alice, 'Form archived', {})
    await alice.send('PATCH', `/projects/${archived.slug}`, { archived: true })
    const visitor = await Visitor.open(baseURL ?? '')
    try {
      const bodies = []
      for (const slug of [off.slug, archived.slug, `no-such-${uniqueSuffix()}`, 'settings']) {
        bodies.push(await problem(await visitor.project(slug), 404, 'not_found'))
        bodies.push(await problem(await visitor.challenge(slug), 404, 'not_found'))
        bodies.push(
          await problem(
            await visitor.submit(slug, { title: 'x', summary: 'x', altcha: 'x' }),
            404,
            'not_found',
          ),
        )
      }
      // No hint which: every answer is the same document.
      for (const body of bodies) expect(body).toEqual(bodies[0])
    } finally {
      await visitor.dispose()
    }
    const pages: [string, string][] = [
      [off.slug, off.name],
      [archived.slug, archived.name],
      ['no-such-form', 'no-such-form'],
    ]
    for (const [slug, name] of pages) {
      await page.goto(`/${slug}/submit`)
      await expect(
        page.getByRole('heading', { level: 1, name: 'This form isn’t available' }),
      ).toBeVisible()
      await expect(page.locator('body')).not.toContainText(name)
    }
  })

  test('turning the form off keeps tracking links working', async ({ page, api, baseURL }) => {
    const alice = await api('alice')
    const project = await projectWithPublicForm(alice, 'Form turned off', {})
    const visitor = await Visitor.open(baseURL ?? '')
    const receipt = await visitor.submitted(project.slug, {
      title: 'Quiet hours',
      summary: 'An hour a day with dimmed lights for autistic shoppers.',
    })
    await visitor.dispose()
    await alice.updatePublicForm(project.slug, { enabled: false })
    await page.goto(`/${project.slug}/submit`)
    await expect(
      page.getByRole('heading', { level: 1, name: 'This form isn’t available' }),
    ).toBeVisible()
    await page.goto(`/track#${receipt.tracking_token}`)
    await expect(page.getByRole('heading', { level: 1, name: 'Quiet hours' })).toBeVisible()
    await expect(page.getByText('Waiting for review', { exact: true })).toBeVisible()
  })
})

test.describe('PA-04: public writes are JSON only, and the fields are checked', () => {
  test('text/plain, a form post or no Content-Type is 415 before anything happens', async ({
    api,
    baseURL,
  }) => {
    const alice = await api('alice')
    const project = await projectWithPublicForm(alice, 'JSON only', {})
    const url = `${baseURL}${API}/projects/${project.slug}/submissions`
    const body = JSON.stringify({ title: 'x', summary: 'x', altcha: 'x' })
    for (const [label, headers, payload] of [
      ['text/plain', { 'Content-Type': 'text/plain' }, body],
      ['form', { 'Content-Type': 'application/x-www-form-urlencoded' }, 'title=x&summary=x'],
      ['multipart', { 'Content-Type': 'multipart/form-data; boundary=x' }, '--x--'],
      ['none', {}, new TextEncoder().encode(body)],
    ] as const) {
      const response = await fetch(url, { method: 'POST', headers, body: payload })
      expect(response.status, label).toBe(415)
      expect(((await response.json()) as { code: string }).code, label).toBe(
        'unsupported_media_type',
      )
    }
    const track = await fetch(`${baseURL}${API}/track`, {
      method: 'POST',
      headers: { 'Content-Type': 'text/plain' },
      body: JSON.stringify({ token: 'A'.repeat(43) }),
    })
    expect(track.status).toBe(415)
    expect(await ideaCount(alice, project.slug)).toBe(0)
    expect((await alice.moderationQueue(project.slug)).total).toBe(0)
  })

  test('a required address, updates without an address and unknown fields are 422', async ({
    page,
    api,
    baseURL,
  }) => {
    const alice = await api('alice')
    test.skip(!(await alice.notificationSummary()).email_available, 'needs SMTP (email required)')
    const project = await projectWithPublicForm(
      alice,
      'Email required',
      {},
      {
        form: { require_email_verification: true },
      },
    )
    const visitor = await Visitor.open(baseURL ?? '')
    try {
      const fields = { title: 'Late opening', summary: 'Open until 10pm on Fridays.' }
      await problem(await visitor.submit(project.slug, fields), 422, 'email_required')
      const other = await projectWithPublicForm(alice, 'Updates need email', {})
      await problem(
        await visitor.submit(other.slug, { ...fields, wants_updates: true }),
        422,
        'validation_error',
      )
      await problem(
        await visitor.submit(other.slug, { ...fields, tags: ['vip'] } as typeof fields),
        422,
        'validation_error',
      )
    } finally {
      await visitor.dispose()
    }
    // The page asks for the address up front and says why.
    await page.goto(`/${project.slug}/submit`)
    const email = page.getByRole('textbox', { name: 'Your email' })
    await expect(email).toBeVisible()
    await fillPublicForm(page, { title: 'Late opening', summary: 'Open until 10pm on Fridays.' })
    await page.getByRole('button', { name: 'Send idea' }).click()
    await expect(email).toBeFocused()
    await expect(email).toHaveAttribute('aria-invalid', 'true')
    expect(await ideaCount(alice, project.slug)).toBe(0)
  })
})

/** Requests until one answers 429 (at most `max`); returns that response. */
async function until429(send: () => Promise<Response>, max: number): Promise<Response> {
  for (let attempt = 0; attempt < max; attempt++) {
    const response = await send()
    if (response.status === 429) return response
  }
  throw new Error(`no 429 after ${max} requests`)
}

/** A random client address in a documentation /64 (IPv6), one per run. */
function clientNetwork(): string {
  const hex = () => Math.floor(Math.random() * 0xffff).toString(16)
  return `2001:db8:${hex()}:${hex()}`
}

test('PA-05: the tracking and challenge throttles count per client address and /64', async ({
  browser,
  api,
  baseURL,
}) => {
  test.skip(
    Boolean(process.env.E2E_BASE_URL) && process.env.E2E_TRUSTS_FORWARDED !== '1',
    'needs an app that trusts this runner as its proxy (the local stack; E2E_TRUSTS_FORWARDED=1)',
  )
  test.setTimeout(240_000)
  const alice = await api('alice')
  const project = await projectWithPublicForm(alice, 'Throttles', {})
  const visitor = await Visitor.open(baseURL ?? '')
  const receipt = await visitor.submitted(project.slug, {
    title: 'Pram parking',
    summary: 'Pram parking by the entrance.',
  })
  await visitor.dispose()

  // The stack's API trusts its loopback peer as the proxy (one hop, the Phase 2 default),
  // so a client address can be given in X-Forwarded-For: this test is its own client
  // (an IPv6 /64), and exhausting its throttles leaves the rest of the run alone.
  const network = clientNetwork()
  const client = `${network}::1`
  const as = (address: string, extra: Record<string, string> = {}) => ({
    'X-Forwarded-For': address,
    ...extra,
  })
  const track = (address = client) =>
    fetch(`${baseURL}${API}/track`, {
      method: 'POST',
      headers: as(address, { 'Content-Type': 'application/json' }),
      body: JSON.stringify({ token: 'A'.repeat(43) }),
    })
  // Tracking, confirming and erasing share 60 requests a minute per client.
  const limited = await until429(() => track(), 62)
  expect(((await limited.json()) as { code: string }).code).toBe('too_many_attempts')
  const retryAfter = Number(limited.headers.get('retry-after'))
  expect(retryAfter).toBeGreaterThan(0)
  expect(retryAfter).toBeLessThanOrEqual(60)
  // Another address in the same /64 is the same client; prepending a made-up address
  // doesn't help either (only the entry the trusted proxy added counts) ...
  expect((await track(`${network}::beef`)).status).toBe(429)
  expect((await track(`203.0.113.50, ${client}`)).status).toBe(429)
  // ... while another network, and everyone else, are unaffected.
  expect((await track(`${clientNetwork()}::1`)).status).toBe(404)
  expect((await trackAsLoopback(baseURL ?? '', receipt.tracking_token)).status).toBe(200)

  // Challenges: 30 a minute per client.
  const challenge = () =>
    fetch(`${baseURL}${API}/projects/${project.slug}/altcha`, { headers: as(client) })
  const noChallenge = await until429(challenge, 32)
  expect(Number(noChallenge.headers.get('retry-after'))).toBeGreaterThan(0)

  // What this visitor sees meanwhile: calm messages with a way forward.
  const context = await browser.newContext({ baseURL, extraHTTPHeaders: as(client) })
  const page = await context.newPage()
  await page.goto(`/track#${receipt.tracking_token}`)
  await expect(
    page.getByRole('heading', { level: 1, name: 'Too many requests just now' }),
  ).toBeVisible({ timeout: 15_000 })
  await expect(page.getByText('Wait a minute, then try again.')).toBeVisible()
  const form = await context.newPage()
  await form.goto(`/${project.slug}/submit`)
  await fillPublicForm(form, { title: 'Pram parking 2', summary: 'More pram parking.' })
  await expect(form.getByText('We couldn’t verify this browser')).toBeVisible({ timeout: 20_000 })
  const retry = form.getByRole('button', { name: 'Retry', exact: true })
  await expect(retry).toBeVisible()

  // About a minute later both let this client through again.
  await expect
    .poll(async () => (await track()).status, { timeout: 90_000, intervals: [5_000] })
    .toBe(404)
  await expect
    .poll(async () => (await challenge()).status, { timeout: 90_000, intervals: [5_000] })
    .toBe(200)
  await page.getByRole('button', { name: 'Try again' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Pram parking' })).toBeVisible()
  await retry.click()
  await humanCheckDone(form)
  await form.getByRole('button', { name: 'Send idea' }).click()
  await expect(
    form.getByRole('heading', { level: 1, name: 'Thanks! Your idea is in' }),
  ).toBeVisible()
  await context.close()
})

/** POST /public/track as a plain (loopback) client. */
function trackAsLoopback(baseURL: string, token: string) {
  return fetch(`${baseURL}${API}/track`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token }),
  })
}

test('PA-06: the per-address submission limit (a stack with E2E_PUBLIC_PER_IP ≤ 20)', async ({
  browser,
  api,
  baseURL,
}) => {
  const limit = Number(process.env.E2E_PUBLIC_PER_IP ?? 1000)
  test.skip(
    limit > 20 || Boolean(process.env.E2E_BASE_URL),
    'needs the local stack with a low limit: E2E_PUBLIC_PER_IP=5 … --grep PA-06 (backend: tests/public/test_submit.py)',
  )
  test.setTimeout(180_000)
  const alice = await api('alice')
  const project = await projectWithPublicForm(alice, 'Per address', {})
  const client = `${clientNetwork()}::1`
  const visitor = await Visitor.open(baseURL ?? '', client)
  let retryAfter = 0
  try {
    let refused: APIResponse | undefined
    for (let attempt = 0; attempt <= limit && !refused; attempt++) {
      const response = await visitor.submit(project.slug, {
        title: `Idea ${attempt}`,
        summary: 'x',
      })
      if (response.status() === 429) refused = response
      else expect(response.status()).toBe(201)
    }
    if (!refused) throw new Error(`no 429 within ${limit + 1} submissions`)
    retryAfter = Number(refused.headers()['retry-after'])
    await problem(refused, 429, 'too_many_attempts')
  } finally {
    await visitor.dispose()
  }
  expect(retryAfter).toBeGreaterThan(0)
  expect((await alice.moderationQueue(project.slug)).total).toBe(limit)
  // Another client is fine.
  const other = await Visitor.open(baseURL ?? '', `${clientNetwork()}::1`)
  expect((await other.submit(project.slug, { title: 'Other', summary: 'x' })).status()).toBe(201)
  await other.dispose()
  // The page says so and keeps what was typed.
  const context = await browser.newContext({
    baseURL,
    extraHTTPHeaders: { 'X-Forwarded-For': client },
  })
  const page = await context.newPage()
  await page.goto(`/${project.slug}/submit`)
  await fillPublicForm(page, { title: 'One more', summary: 'One more idea.' })
  await humanCheckDone(page)
  await page.getByRole('button', { name: 'Send idea' }).click()
  await expect(page.getByText('You’ve sent several ideas in a short time')).toBeVisible()
  await expect(page.getByRole('textbox', { name: 'Title' })).toHaveValue('One more')
  await context.close()
})
