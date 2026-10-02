import { readFileSync } from 'node:fs'

import type { Browser, Page } from '@playwright/test'

import {
  createTeamProject,
  defaultRubricScores,
  uniqueSuffix,
  type BrandingSettings,
  type Project,
} from './support/api'
import { expectNoScoreData, links, Mailpit, requireEmail, visibleText } from './support/email'
import { details, expect, heading, settled, signIn, test, toast } from './support/fixtures'
import { embedsFont, pdfColours, pdfImageCount, readPdf } from './support/pdf'
import {
  brandingUpdate,
  fillPublicForm,
  fragmentToken,
  humanCheckDone,
  PHONE,
  rootVar,
  solidPng,
  Visitor,
} from './support/public'

/**
 * Phase 4 acceptance (SPEC section 13; contract-phase4 §3.16) through the browser, against
 * the real stack (API, worker, Mailpit, the PDF renderer). Test plan: AC4-01.
 *
 * Anonymous idea → evaluated → shortlisted → exported branded proposal:
 *
 * 1. Alice (platform admin) sets the global branding on Settings → Branding (live preview
 *    before Save, the shell after); as the project's admin she turns its public form on
 *    (moderated) and gives it its own colour.
 * 2. A visitor on a phone, signed out, sends an idea: the form is in the project's
 *    branding, the ALTCHA solves by itself, the receipt shows the private link; the
 *    fixed-text confirmation email arrives; the visitor confirms on /verify.
 * 3. The idea is on no board, list or search for members; Alice sees "1 idea … waiting
 *    for review", approves it, and it is in New.
 * 4. The owner edits its summary, three evaluators score it, it is Shortlisted: the
 *    submitter's email and tracking page say so, with only what they sent.
 * 5. The owner starts the proposal (the idea moves to Proposal: another email), writes
 *    sections; a member comments on Problem in the margin; the owner resolves it.
 * 6. The owner exports PDF (cover in the project's colour, the logo, IBM Plex Sans, page
 *    numbers, the aggregate score) and Markdown (the same text). A pending evaluator's
 *    export has no score.
 * 7. Alice erases the submitter's details: the tracking link stops working, the idea
 *    and its proposal stay.
 *
 * `@serial`: it changes the global branding ("Acme Ideas" in every title and email), so
 * it runs after the other specs, alone, and puts the branding back.
 */

const GLOBAL_PRIMARY = '#7c3aed'
const PROJECT_PRIMARY = '#0b6e4f'
const TITLE = 'Recycle packaging at the till'
const SUMMARY = 'Let customers hand back packaging when they pay, so it gets recycled.'
const DESCRIPTION = 'Bins by every till, emptied by the recycling partner on Fridays.'
const EDITED = 'Packaging take-back at the tills (internal: pilot in Leeds, ask Finance).'
const PROBLEM = 'Shoppers throw away 12 tonnes of our packaging a month.'
const SOLUTION = 'A take-back bin at every till, emptied weekly by our partner.'
const INTRO = 'Tell us how to make shopping with us better. We read every idea.'

/** The global profile as it was, to put back afterwards (images by id). */
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

async function signedOutPhone(browser: Browser, baseURL: string): Promise<Page> {
  const context = await browser.newContext({ ...PHONE, baseURL })
  return context.newPage()
}

test(
  'AC4-01: an anonymous idea is evaluated, shortlisted and exported as a branded proposal',
  {
    tag: ['@serial'],
  },
  async ({ page, browser, api, baseURL }) => {
    test.setTimeout(420_000)
    const alice = await api('alice')
    await requireEmail(alice)
    const original = await alice.globalBranding()
    const mailpit = new Mailpit()
    const run = uniqueSuffix()
    const visitorEmail = `jo.${run}@example.com`
    const appName = `Acme Ideas`
    let project: Project | undefined
    try {
      // --- 1. Branding ---------------------------------------------------------------
      await signIn(page, 'alice')
      await page.goto('/settings/branding')
      await expect(page.getByRole('heading', { level: 2, name: 'Branding' })).toBeVisible()
      await page.getByLabel('App name').fill(appName)
      await page.getByRole('textbox', { name: 'Primary colour', exact: true }).fill(GLOBAL_PRIMARY)
      await page.getByRole('radio', { name: /IBM Plex Sans/ }).click()
      await page
        .getByRole('textbox', { name: 'Email footer' })
        .fill('Acme Ideas Ltd\n1 Example Street')
      const logoGroup = page.getByRole('group', { name: 'Logo' })
      await logoGroup.locator('input[type="file"]').setInputFiles({
        name: 'acme.png',
        mimeType: 'image/png',
        buffer: solidPng(240, 64, [124, 58, 237]),
      })
      await expect(logoGroup.getByRole('img', { name: 'The logo you chose' })).toBeVisible()
      // Live preview before Save: the preview has the new colour, the app doesn't yet.
      const preview = page.getByTestId('branding-preview').first()
      await expect
        .poll(() =>
          preview.evaluate((el) => getComputedStyle(el).getPropertyValue('--brand-primary').trim()),
        )
        .toBe(GLOBAL_PRIMARY)
      await expect(preview).toContainText(appName)
      expect(await rootVar(page, '--brand-primary')).not.toBe(GLOBAL_PRIMARY)
      await page.getByRole('button', { name: /Save branding/ }).click()
      await expect(toast(page, 'Branding saved')).toBeVisible()
      // The shell: colour, font, name and the tab title.
      await expect.poll(() => rootVar(page, '--brand-primary')).toBe(GLOBAL_PRIMARY)
      expect(await rootVar(page, '--brand-font')).toContain('IBM Plex Sans')
      await expect(page).toHaveTitle(new RegExp(`${appName}$`))
      const saved = await alice.globalBranding()
      expect(saved.effective).toMatchObject({ app_name: appName, font: 'ibm_plex_sans' })
      expect(saved.logo?.content_type).toBe('image/png')

      // The project (Alice is its admin): public form on, moderated, its own colour.
      project = await createTeamProject(alice, 'Customer Innovation', {
        bob: 'member',
        carol: 'member',
        dave: 'member',
        farah: 'member',
        kenji: 'member',
        mateo: 'member',
      })
      const slug = project.slug
      await page.goto(`/p/${slug}/settings?tab=public-form`)
      const form = page.getByRole('form', { name: 'Public form' })
      await form.getByRole('switch', { name: 'Accept ideas through the public form' }).click()
      await expect(
        form.getByRole('switch', { name: 'Review new ideas before the team sees them' }),
      ).toBeChecked()
      await form.getByRole('textbox', { name: 'Intro' }).fill(INTRO)
      await form.getByRole('button', { name: /^Save/ }).click()
      await expect(toast(page, 'The public form is on')).toBeVisible()
      await page.goto(`/p/${slug}/settings?tab=branding`)
      const brandingPanel = page.getByRole('tabpanel', { name: 'Branding' })
      await brandingPanel
        .getByRole('textbox', { name: 'Primary colour', exact: true })
        .fill(PROJECT_PRIMARY)
      await brandingPanel.getByRole('button', { name: /Save branding/ }).click()
      await expect(toast(page, 'Project branding saved')).toBeVisible()
      // The signed-in app keeps the global branding.
      expect(await rootVar(page, '--brand-primary')).toBe(GLOBAL_PRIMARY)

      // --- 2. The public form on a phone, signed out --------------------------------------
      const phone = await signedOutPhone(browser, baseURL ?? '')
      const since = new Date()
      await phone.goto(`/${slug}/submit`)
      await expect(
        phone.getByRole('heading', { level: 1, name: `Share an idea with ${project.name}` }),
      ).toBeVisible()
      await expect(phone.getByText(INTRO)).toBeVisible()
      await expect.poll(() => rootVar(phone, '--brand-primary')).toBe(PROJECT_PRIMARY)
      expect(await rootVar(phone, '--brand-font')).toContain('IBM Plex Sans')
      await expect(phone.locator('header img')).toHaveAttribute('src', saved.logo?.url ?? '')
      await expect(phone.locator('header')).toContainText(appName)
      await fillPublicForm(phone, {
        title: TITLE,
        summary: SUMMARY,
        description: DESCRIPTION,
        name: 'Jo Public',
        email: visitorEmail,
        updates: true,
      })
      await humanCheckDone(phone)
      await phone.getByRole('button', { name: 'Send idea' }).tap()
      await expect(
        phone.getByRole('heading', { level: 1, name: 'Thanks! Your idea is in' }),
      ).toBeFocused()
      await expect(phone.getByText(`“${TITLE}” was sent to ${project.name}.`)).toBeVisible()
      await expect(phone.getByText('The team reviews new ideas first')).toBeVisible()
      const privateLink = await phone
        .getByRole('textbox', { name: 'Your private link' })
        .inputValue()
      expect(privateLink).toMatch(/\/track#[A-Za-z0-9_-]{43}$/)
      const token = fragmentToken(privateLink)
      await phone.getByRole('link', { name: 'Open your tracking page' }).tap()
      await expect(phone).toHaveURL(new RegExp(`/track#${token}$`))
      await expect(phone.getByRole('heading', { level: 1, name: TITLE })).toBeVisible()
      await expect(phone.getByText('Waiting for review', { exact: true })).toBeVisible()

      // The confirmation email: fixed text (nothing the visitor typed) and both links.
      const confirmation = await mailpit.waitForMessage(visitorEmail, {
        since,
        subject: `Confirm your idea for ${project.name}`,
      })
      const confirmationText = `${confirmation.Subject}\n${visibleText(confirmation.HTML)}\n${confirmation.Text}`
      for (const typed of [TITLE, SUMMARY, DESCRIPTION, 'Jo Public', 'packaging']) {
        expect(confirmationText, 'the confirmation email is fixed text').not.toContain(typed)
      }
      expect(visibleText(confirmation.HTML)).toContain(appName)
      expect(confirmation.HTML.toLowerCase()).toContain(PROJECT_PRIMARY)
      const verifyLink = links(confirmation).find((href) => href.includes('/verify#'))
      const trackLink = links(confirmation).find((href) => href.includes('/track#'))
      expect(trackLink).toBe(privateLink)
      if (!verifyLink) throw new Error('no confirmation link in the email')
      // Opening it changes nothing; the click confirms.
      await phone.goto(verifyLink)
      await expect(
        phone.getByRole('heading', { level: 1, name: 'Confirm your email address' }),
      ).toBeVisible()
      const visitor = await Visitor.open(baseURL ?? '')
      expect((await visitor.tracked(token)).email_verified).toBe(false)
      await phone.getByRole('button', { name: 'Confirm my email address' }).tap()
      await expect(
        phone.getByRole('heading', { level: 1, name: 'Thanks, your address is confirmed' }),
      ).toBeVisible()
      // Only the project, never the submitted title (anyone can type in someone's address).
      await expect(phone.getByText(`Your idea for ${project.name}`)).toBeVisible()
      await expect(phone.getByText(TITLE)).toHaveCount(0)
      expect((await visitor.tracked(token)).email_verified).toBe(true)

      // --- 3. Held: nowhere for members; reviewed and approved ----------------------------
      const [queued] = (await alice.moderationQueue(slug)).items
      if (!queued) throw new Error('the idea is not in the moderation queue')
      const key = queued.key
      const bob = await api('bob')
      expect((await bob.listIdeas(slug)).items).toHaveLength(0)
      const found = await bob.get<{ ideas: { key: string }[] }>(
        '/search?q=recycle%20packaging%20till',
      )
      expect(found.ideas.map((idea) => idea.key)).not.toContain(key)
      const bobPage = await (await browser.newContext({ baseURL })).newPage()
      await signIn(bobPage, 'bob')
      await bobPage.goto(`/p/${slug}?view=board`)
      // The held idea is the project's only one: the board is empty for members.
      await expect(bobPage.getByRole('heading', { name: 'No ideas yet' })).toBeVisible()
      await expect(bobPage.getByText(TITLE)).toHaveCount(0)
      await expect(bobPage.getByText(/waiting for review/)).toHaveCount(0)

      await page.goto(`/p/${slug}?view=board`)
      await expect(
        page.getByText('1 idea from the public form is waiting for review.'),
      ).toBeVisible()
      // The board's notice (the sidebar has a "Review new ideas" link too).
      await page.getByRole('main').getByRole('link', { name: 'Review', exact: true }).click()
      await expect(page).toHaveURL(new RegExp(`/p/${slug}/review$`))
      const item = page.getByRole('article').filter({ hasText: TITLE })
      await expect(item).toContainText(SUMMARY)
      await expect(item).toContainText('From Jo Public')
      await item.getByRole('button', { name: `Approve ${key}` }).click()
      await expect(toast(page, `${key} approved`)).toBeVisible()
      // The approval is sent when its Undo toast closes.
      await expect
        .poll(async () => (await alice.moderationQueue(slug)).total, { timeout: 20_000 })
        .toBe(0)
      await bobPage.reload()
      await expect(
        bobPage
          .getByRole('region', { name: /^New\b/ })
          .getByRole('link', { name: new RegExp(`^${key}\\b`) }),
      ).toBeVisible()

      // --- 4. Owner, evaluations, Shortlisted --------------------------------------------
      await alice.setOwner(key, 'bob')
      await bob.send('PATCH', `/ideas/${key}`, { summary: EDITED })
      await bob.changeStatus(key, 'evaluating')
      await bob.invite(key, ['carol', 'dave', 'farah', 'kenji'])
      const scores = { carol: 4, dave: 5, farah: 3 } as const
      for (const [person, value] of Object.entries(scores) as [keyof typeof scores, number][]) {
        const evaluator = await api(person)
        await evaluator.evaluate(key, defaultRubricScores(value, value, 3, value, 2), {
          recommendation: 'go',
          comment: `${person}: worth a pilot`,
        })
      }
      await bob.changeStatus(key, 'shortlisted')
      const shortlisted = await mailpit.waitForMessage(visitorEmail, {
        since,
        subject: `Your idea "${TITLE}" is now Shortlisted`,
      })
      const statusText = `${visibleText(shortlisted.HTML)}\n${shortlisted.Text}`
      for (const internal of [EDITED, 'Bob Brown', 'Carol', 'worth a pilot', key]) {
        expect(statusText, 'the status email shows only what the visitor sent').not.toContain(
          internal,
        )
      }
      expectNoScoreData('status email', shortlisted.Subject, visibleText(shortlisted.HTML))
      expect(links(shortlisted)).toContain(privateLink)

      await phone.goto(privateLink)
      await phone.reload()
      await expect(phone.getByRole('heading', { level: 1, name: TITLE })).toBeVisible()
      await expect(phone.getByText(SUMMARY)).toBeVisible()
      await expect(phone.getByText(EDITED)).toHaveCount(0)
      const history = phone.getByRole('list').filter({ hasText: 'Sent' })
      await expect(history.getByRole('listitem')).toHaveText([
        /^Sent/,
        /^Evaluating/,
        /^Shortlisted/,
      ])
      await expect(phone.locator('main')).not.toContainText(key)
      await expect(phone.locator('main')).not.toContainText('Bob Brown')

      // --- 5. The proposal ------------------------------------------------------------------
      await signIn(page, 'bob')
      await page.goto(`/ideas/${key}?tab=proposal`)
      await expect(
        page.getByRole('heading', { level: 2, name: 'Write the proposal' }),
      ).toBeVisible()
      await page.getByRole('button', { name: 'Start proposal' }).click()
      const problem = page.getByRole('textbox', { name: 'Problem', exact: true })
      await expect(problem).toBeVisible()
      await expect.poll(async () => (await bob.idea(key)).status).toBe('proposal')
      await problem.fill(PROBLEM)
      await page.getByRole('textbox', { name: 'Solution', exact: true }).fill(SOLUTION)
      await expect(page.getByRole('status').filter({ hasText: /^Saved/ })).toBeVisible()
      await expect
        .poll(async () => (await bob.proposal(key)).proposal?.sections[2]?.body_md)
        .toBe(SOLUTION)
      await mailpit.waitForMessage(visitorEmail, {
        since,
        subject: `Your idea "${TITLE}" is now Proposal`,
      })

      // A member comments on Problem in the margin; the owner resolves the thread.
      const mateoPage = await (await browser.newContext({ baseURL })).newPage()
      await signIn(mateoPage, 'mateo')
      await mateoPage.goto(`/ideas/${key}?tab=proposal`)
      const margin = mateoPage.getByRole('complementary', { name: 'Comments on Problem' })
      await margin.getByRole('button', { name: 'Comment on Problem' }).click()
      await margin
        .getByRole('textbox', { name: 'Comment on Problem' })
        .fill('Where does the 12 tonnes figure come from?')
      await margin.getByRole('button', { name: 'Comment', exact: true }).click()
      await expect(margin.getByText('Where does the 12 tonnes figure come from?')).toBeVisible()
      await mateoPage.context().close()

      await page.reload()
      const ownerMargin = page.getByRole('complementary', { name: 'Comments on Problem' })
      await expect(
        ownerMargin.getByText('Where does the 12 tonnes figure come from?'),
      ).toBeVisible()
      await ownerMargin.getByRole('button', { name: 'Resolve' }).click()
      await expect(ownerMargin.getByText(/^Resolved · Mateo Rodríguez/)).toBeVisible()
      const [thread] = await bob.threads(key)
      expect(thread?.resolved_by?.display_name).toBe('Bob Brown')

      // --- 6. Exports -------------------------------------------------------------------------
      await page.getByRole('button', { name: 'Export' }).click()
      const pdfDownload = page.waitForEvent('download')
      await page.getByRole('menuitem', { name: /PDF/ }).click()
      const pdfFile = await pdfDownload
      expect(pdfFile.suggestedFilename()).toBe(`${key}-proposal.pdf`)
      const pdf = readFileSync(await pdfFile.path())
      const read = await readPdf(pdf)
      expect([read.title, read.author, read.creator]).toEqual([TITLE, 'Bob Brown', appName])
      const text = read.pages.join('\n')
      expect(read.pages[0]).toContain(project.name)
      expect(read.pages[0]).toMatch(/Aggregate score \d\.\d from 3 evaluations/)
      for (const section of [
        'Summary',
        'Problem',
        'Solution',
        'Market & users',
        'Cost & effort',
        'Benefits / revenue',
        'Risks',
        'Next steps / the ask',
      ]) {
        expect(text).toContain(section)
      }
      expect(text).toContain(PROBLEM)
      expect(text).toContain(SOLUTION)
      expect(read.pages[1]).toContain(`Page 2 of ${read.pages.length}`)
      expect(read.pages[1]).toContain(appName)
      expect(text).not.toContain('Where does the 12 tonnes') // comments are never exported
      expect(pdfColours(pdf)).toContain(PROJECT_PRIMARY)
      expect(pdfColours(pdf)).not.toContain(GLOBAL_PRIMARY)
      expect(embedsFont(pdf, 'IBM Plex Sans')).toBe(true)
      expect(pdfImageCount(pdf)).toBeGreaterThan(0) // the PNG logo on the cover

      await page.getByRole('button', { name: 'Export' }).click()
      const mdDownload = page.waitForEvent('download')
      await page.getByRole('menuitem', { name: /Markdown/ }).click()
      const mdFile = await mdDownload
      expect(mdFile.suggestedFilename()).toBe(`${key}-proposal.md`)
      const markdown = readFileSync(await mdFile.path(), 'utf8')
      expect(markdown).toContain(`# ${TITLE}`)
      expect(markdown).toContain(`- Project: ${project.name}`)
      expect(markdown).toMatch(/- Aggregate score \d\.\d from 3 evaluations/)
      expect(markdown).toContain(`## Problem\n\n${PROBLEM}\n`)
      expect(markdown).toContain(`## Solution\n\n${SOLUTION}\n`)

      // A pending evaluator (Kenji) gets no score in either format.
      const kenji = await api('kenji')
      for (const format of ['markdown', 'pdf'] as const) {
        const { response, body } = await kenji.exportProposal(key, format)
        expect(response.status()).toBe(200)
        const content = format === 'pdf' ? (await readPdf(body)).pages.join('\n') : body.toString()
        expect(content.toLowerCase(), format).not.toContain('score')
        expect(content, format).not.toContain('from 3 evaluations')
      }

      // --- 7. Erasure ---------------------------------------------------------------------------
      await signIn(page, 'alice')
      await page.goto(`/ideas/${key}`)
      await expect(heading(page, TITLE)).toBeVisible()
      await settled(page)
      const panel = details(page)
      await expect(panel.getByText('Sent by Jo Public')).toBeVisible()
      await expect(panel.getByText(visitorEmail)).toBeVisible()
      await panel.getByRole('button', { name: /Erase submitter details/ }).click()
      const dialog = page.getByRole('alertdialog', { name: 'Erase the submitter’s details?' })
      await expect(dialog).toContainText(
        'Jo Public’s name, email address and private tracking link',
      )
      await dialog.getByRole('button', { name: 'Erase details' }).click()
      await expect(toast(page, 'Submitter details erased')).toBeVisible()
      await expect(panel.getByText(/Submitter’s details erased/)).toBeVisible()
      await phone.reload()
      await expect(
        phone.getByRole('heading', { level: 1, name: 'We can’t find this submission' }),
      ).toBeVisible()
      expect((await visitor.track(token)).status()).toBe(404)
      const kept = await alice.idea(key)
      expect([kept.title, kept.status, kept.via_public_form]).toEqual([TITLE, 'proposal', true])
      expect((await alice.proposal(key)).proposal?.sections[1]?.body_md).toBe(PROBLEM)
      await visitor.dispose()
      await phone.context().close()
      await bobPage.context().close()
    } finally {
      await alice.setGlobalBranding(restoreOf(original))
    }
  },
)
