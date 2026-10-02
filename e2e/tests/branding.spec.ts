import { createTeamProject, uniqueSuffix, type BrandingSettings } from './support/api'
import { Mailpit, newPeople, requireEmail, visibleText } from './support/email'
import { expect, signIn, test, toast } from './support/fixtures'
import { embedsFont, pdfColours, readPdf } from './support/pdf'
import {
  brandingUpdate,
  projectWithPublicForm,
  rootVar,
  solidPng,
  svgLogo,
  Visitor,
} from './support/public'

/**
 * Branding (contract-phase4 §3.10–3.11) against the real stack: the global profile on the
 * signed-in app, the sign-in page and staff emails; a project's override, applied live in
 * its settings' preview and then on its public form, its submitters' emails and its
 * exported PDF, never on the signed-in app; images only as <img>, served sandboxed.
 * Test plan: BR-*.
 *
 * BR-01 changes the global branding, which every page and email shows: `@serial` (after
 * the other specs, alone), and it puts the profile back.
 */

const PROJECT_PRIMARY = '#b42318'

function restoreOf(settings: BrandingSettings) {
  return brandingUpdate({
    app_name: settings.app_name,
    primary_color: settings.primary_color,
    accent_color: settings.accent_color,
    font: settings.font,
    email_footer: settings.email_footer,
    logo_asset_id: settings.logo?.id ?? null,
    favicon_asset_id: settings.favicon?.id ?? null,
  })
}

test(
  'BR-01: the global branding reaches every signed-in page, the sign-in page and staff email',
  {
    tag: ['@serial'],
  },
  async ({ page, browser, api, baseURL }) => {
    const alice = await api('alice')
    const original = await alice.globalBranding()
    const appName = `Northwind Ideas`
    try {
      await signIn(page, 'alice')
      await page.goto('/settings/branding')
      await page.getByLabel('App name').fill(appName)
      await page.getByRole('button', { name: 'Teal (#0f766e)' }).first().click()
      await page.getByRole('radio', { name: /Atkinson Hyperlegible/ }).click()
      await page
        .getByRole('textbox', { name: 'Email footer' })
        .fill('Northwind Ltd · 2 Example Road')
      const favicon = page.getByRole('group', { name: 'Favicon' })
      await favicon.locator('input[type="file"]').setInputFiles({
        name: 'favicon.png',
        mimeType: 'image/png',
        buffer: solidPng(32, 32, [15, 118, 110]),
      })
      await expect(favicon.getByText(/PNG · 32 × 32/)).toBeVisible()
      await page.getByRole('button', { name: /Save branding/ }).click()
      await expect(toast(page, 'Branding saved')).toBeVisible()
      const saved = await alice.globalBranding()
      expect(saved.effective).toMatchObject({
        app_name: appName,
        primary_color: '#0f766e',
        font: 'atkinson_hyperlegible',
      })

      // Someone else's next page load: name, colour, font, favicon and tab title.
      const context = await browser.newContext({ baseURL })
      const bob = await context.newPage()
      await signIn(bob, 'bob')
      await bob.goto('/')
      await expect(bob).toHaveTitle(new RegExp(`${appName}$`))
      await expect.poll(() => rootVar(bob, '--brand-primary')).toBe('#0f766e')
      expect(await rootVar(bob, '--brand-font')).toContain('Atkinson Hyperlegible')
      await expect(bob.locator('link[rel="icon"]').first()).toHaveAttribute(
        'href',
        saved.favicon?.url ?? '',
      )
      // The sign-in page (signed out) too.
      await context.clearCookies()
      await bob.goto('/login')
      await expect(bob.getByText(appName).first()).toBeVisible()
      await expect.poll(() => rootVar(bob, '--brand-primary')).toBe('#0f766e')
      await context.close()

      // A staff email (the admin test email): the global name, colour and footer.
      if ((await alice.notificationSummary()).email_available) {
        const people = await newPeople(alice, ['ravi'], { platformAdmins: ['ravi'] })
        const to = `ops.${uniqueSuffix()}@example.com`
        const since = new Date()
        await people.ravi.api.sendTestEmail(to)
        const mail = await new Mailpit().waitForMessage(to, { since, subject: /test email/ })
        expect(mail.Subject).toBe(`${appName} test email`)
        expect(visibleText(mail.HTML)).toContain('Northwind Ltd · 2 Example Road')
        expect(mail.HTML.toLowerCase()).toContain('#0f766e')
        expect(mail.Text).toContain('Northwind Ltd · 2 Example Road')
        expect(mail.HTML.toLowerCase()).not.toContain('<img')
        await people.ravi.api.dispose()
      }
    } finally {
      await alice.setGlobalBranding(restoreOf(original))
    }
  },
)

test('BR-02: a project’s override: live preview, then its public form, never the app', async ({
  page,
  browser,
  api,
  baseURL,
}) => {
  const alice = await api('alice')
  const project = await projectWithPublicForm(alice, 'Branded form', { bob: 'member' })
  const global = (await alice.globalBranding()).effective
  await signIn(page, 'alice')
  await page.goto(`/p/${project.slug}/settings?tab=branding`)
  const panel = page.getByRole('tabpanel', { name: 'Branding' })
  await expect(panel.getByText('From the global branding').first()).toBeVisible()
  await panel
    .getByRole('button', { name: `Brick (${PROJECT_PRIMARY})` })
    .first()
    .click()
  await panel.getByRole('radio', { name: /Source Serif 4/ }).click()
  await panel
    .getByRole('group', { name: 'Logo' })
    .locator('input[type="file"]')
    .setInputFiles({
      name: 'logo.svg',
      mimeType: 'image/svg+xml',
      buffer: svgLogo('Branded form', PROJECT_PRIMARY),
    })
  await expect(
    panel.getByRole('group', { name: 'Logo' }).getByRole('img', { name: 'The logo you chose' }),
  ).toBeVisible()
  // The preview follows before Save; the app (global branding) doesn't change at all.
  const preview = panel.getByTestId('branding-preview').first()
  await expect
    .poll(() =>
      preview.evaluate((el) => getComputedStyle(el).getPropertyValue('--brand-primary').trim()),
    )
    .toBe(PROJECT_PRIMARY)
  await expect(panel.getByRole('tab', { name: 'App' })).toHaveCount(0)
  await panel.getByRole('tab', { name: 'Public form' }).click()
  await expect(preview).toContainText('Send idea')
  await panel.getByRole('button', { name: /Save branding/ }).click()
  await expect(toast(page, 'Project branding saved')).toBeVisible()
  expect(await rootVar(page, '--brand-primary')).toBe(global.primary_color)
  const settings = await alice.projectBranding(project.slug)
  // A logo of its own and no app name: the project is its own brand, so its name is
  // the wordmark (its emails, PDF header and public pages' name; UX review M3).
  expect(settings.effective).toMatchObject({
    primary_color: PROJECT_PRIMARY,
    font: 'source_serif_4',
    app_name: project.name,
  })
  const logoUrl = settings.logo?.url ?? ''
  expect(logoUrl).toMatch(/^\/api\/v1\/branding\/assets\//)

  // The public form, signed out: the override, the logo only ever as an <img>.
  const visitor = await browser.newContext({ baseURL })
  const form = await visitor.newPage()
  await form.goto(`/${project.slug}/submit`)
  await expect(form.getByRole('heading', { level: 1 })).toContainText(project.name)
  await expect.poll(() => rootVar(form, '--brand-primary')).toBe(PROJECT_PRIMARY)
  expect(await rootVar(form, '--brand-font')).toContain('Source Serif 4')
  await expect(form.locator('header img')).toHaveAttribute('src', logoUrl)
  await expect(form.locator('header svg')).toHaveCount(0)
  // The logo stands alone (its name is for screen readers only, K4-2): the project's...
  await expect(form.locator('header').getByText(project.name, { exact: true })).toHaveClass(
    /sr-only/,
  )
  // ...and in dark mode it sits on a light (softened, UX m8) plate, so dark lettering
  // stays readable: its lightness, whatever colour syntax the browser reports.
  await form.evaluate(() => document.documentElement.classList.add('dark'))
  const plate = await form.locator('header img').evaluate((image) => {
    const canvas = document.createElement('canvas').getContext('2d')
    if (!canvas) return 0
    canvas.fillStyle = getComputedStyle(image).backgroundColor
    canvas.fillRect(0, 0, 1, 1)
    const [red = 0, green = 0, blue = 0, alpha = 0] = canvas.getImageData(0, 0, 1, 1).data
    return alpha === 255 ? (red + green + blue) / 3 : 0
  })
  expect(plate).toBeGreaterThan(200)
  await form.evaluate(() => document.documentElement.classList.remove('dark'))
  // The tracking page of a submission to it, too.
  const anonymous = await Visitor.open(baseURL ?? '')
  const receipt = await anonymous.submitted(project.slug, {
    title: 'Paper bags only',
    summary: 'Swap plastic bags for paper.',
  })
  await anonymous.dispose()
  await form.goto(`/track#${receipt.tracking_token}`)
  await expect(form.getByRole('heading', { level: 1, name: 'Paper bags only' })).toBeVisible()
  await expect.poll(() => rootVar(form, '--brand-primary')).toBe(PROJECT_PRIMARY)
  await visitor.close()

  // A member's signed-in app keeps the global branding, also on this project's pages.
  await signIn(page, 'bob')
  await page.goto(`/p/${project.slug}`)
  await expect.poll(() => rootVar(page, '--brand-primary')).toBe(global.primary_color)

  // The image is served as itself, sandboxed: an SVG opened directly can't run script.
  const served = await page.request.get(logoUrl)
  expect(served.status()).toBe(200)
  expect(served.headers()['content-type']).toBe('image/svg+xml')
  expect(served.headers()['x-content-type-options']).toBe('nosniff')
  expect(served.headers()['content-security-policy']).toContain('sandbox')
  expect(served.headers()['cache-control']).toContain('immutable')
  const etag = served.headers().etag ?? ''
  expect((await page.request.get(logoUrl, { headers: { 'If-None-Match': etag } })).status()).toBe(
    304,
  )
})

test('BR-03: hostile images and values are refused with a reason', async ({ page, api }) => {
  const alice = await api('alice')
  const project = await createTeamProject(alice, 'Hostile branding', {})
  for (const [label, svg] of [
    ['script', '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'],
    ['onload', '<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"><rect/></svg>'],
    [
      'external image',
      '<svg xmlns="http://www.w3.org/2000/svg"><image href="http://169.254.169.254/x"/></svg>',
    ],
    [
      'doctype',
      '<!DOCTYPE svg [<!ENTITY x "x">]><svg xmlns="http://www.w3.org/2000/svg"><text>&x;</text></svg>',
    ],
    [
      'style url',
      '<svg xmlns="http://www.w3.org/2000/svg"><rect style="fill:url(http://evil.test/x)"/></svg>',
    ],
  ] as const) {
    const response = await alice.rawBody(
      `/projects/${project.slug}/branding/assets?kind=logo`,
      Buffer.from(svg),
      'image/svg+xml',
    )
    expect(response.status(), label).toBe(422)
    expect(((await response.json()) as { code: string }).code, label).toBe('invalid_image')
  }
  const html = await alice.rawBody(
    `/projects/${project.slug}/branding/assets?kind=favicon`,
    Buffer.from('<html><script>alert(1)</script></html>'),
    'image/png',
  )
  expect(html.status()).toBe(422)
  // CSS injection through a colour or font: the schema refuses it.
  for (const update of [
    { primary_color: 'red; } body { display: none' },
    { accent_color: '#12345' },
    { font: 'Comic Sans", serif; x: "' },
    { app_name: 'Two\nlines' },
  ]) {
    const response = await alice.raw(
      'PUT',
      `/projects/${project.slug}/branding`,
      brandingUpdate(update as never),
    )
    expect(response.status(), JSON.stringify(update)).toBe(422)
  }
  // An image of another profile can't be borrowed.
  const other = await createTeamProject(alice, 'Other branding', {})
  const theirs = await alice.uploadBrandAsset(
    'logo',
    solidPng(8, 8, [0, 0, 0]),
    'image/png',
    other.slug,
  )
  const borrowed = await alice.raw(
    'PUT',
    `/projects/${project.slug}/branding`,
    brandingUpdate({ logo_asset_id: theirs.id }),
  )
  expect(borrowed.status()).toBe(422)
  expect(((await borrowed.json()) as { code: string }).code).toBe('invalid_asset')
  // The settings page says why, and keeps the form.
  await signIn(page, 'alice')
  await page.goto(`/p/${project.slug}/settings?tab=branding`)
  const favicon = page.getByRole('tabpanel', { name: 'Branding' }).getByRole('group', {
    name: 'Favicon',
  })
  await favicon.locator('input[type="file"]').setInputFiles({
    name: 'icon.svg',
    mimeType: 'image/svg+xml',
    buffer: Buffer.from('<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'),
  })
  await expect(favicon.getByRole('alert')).toContainText('That image can’t be used')
})

test('BR-04: a project’s submitters’ emails and its exported PDF use its branding', async ({
  api,
  baseURL,
}) => {
  const alice = await api('alice')
  await requireEmail(alice)
  const project = await projectWithPublicForm(
    alice,
    'Branded mail',
    {},
    {
      form: { moderation_required: false },
      branding: {
        primary_color: PROJECT_PRIMARY,
        font: 'source_serif_4',
        email_footer: 'Branded Mail team · 3 Example Lane',
      },
    },
  )
  const global = (await alice.globalBranding()).effective
  // The confirmation email: the project's colour and footer, the (global) app name.
  const address = `brand.${uniqueSuffix()}@example.com`
  const since = new Date()
  const visitor = await Visitor.open(baseURL ?? '')
  await visitor.submitted(project.slug, {
    title: 'Refill pouches',
    summary: 'Sell refills in pouches.',
    email: address,
  })
  await visitor.dispose()
  const mail = await new Mailpit().waitForMessage(address, {
    since,
    subject: `Confirm your idea for ${project.name}`,
  })
  expect(mail.HTML.toLowerCase()).toContain(PROJECT_PRIMARY)
  expect(visibleText(mail.HTML)).toContain('Branded Mail team · 3 Example Lane')
  expect(mail.Text).toContain('Branded Mail team · 3 Example Lane')
  expect(visibleText(mail.HTML)).toContain(global.app_name)
  expect(mail.HTML.toLowerCase()).not.toContain('<img')
  expect(mail.HTML).not.toContain('url(')

  // The exported PDF: the project's colour and font.
  const [idea] = (await alice.listIdeas(project.slug)).items
  if (!idea) throw new Error('the submission is not visible')
  await alice.setOwner(idea.key, 'alice')
  await alice.changeStatus(idea.key, 'shortlisted')
  await alice.startProposal(idea.key)
  await alice.writeSections(idea.key, { problem: 'Plastic bottles everywhere.' })
  const { response, body } = await alice.exportProposal(idea.key, 'pdf')
  expect(response.status()).toBe(200)
  expect(pdfColours(body)).toContain(PROJECT_PRIMARY)
  expect(embedsFont(body, 'Source Serif 4')).toBe(true)
  const read = await readPdf(body)
  expect(read.creator).toBe(global.app_name)
  expect(read.pages.join('\n')).toContain('Plastic bottles everywhere.')
})
