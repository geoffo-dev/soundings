import { execFileSync } from 'node:child_process'
import { mkdirSync, readdirSync, readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import type { Browser, Page } from '@playwright/test'

import { Api, daysFromNow, uniqueSuffix, type Person } from '../tests/support/api'
import {
  canControlMailpit,
  emailTo,
  Mailpit,
  newPeople,
  projectWithIdea,
  startMailpit,
  stopMailpit,
  unsubscribeLink,
  type Message,
} from '../tests/support/email'
import { expect, heading, settled, signIn, test } from '../tests/support/fixtures'

/**
 * Review screenshots of the Phase 3 screens from the real app (API, worker, Mailpit) with
 * the demo data, and of every email template. Not a regression test.
 *
 * `npm run screenshots:phase3` → docs/screenshots/phase-3/ (`SCREENSHOT_DIR` overrides):
 *
 * - <screen>-<1440-light|1440-dark|390-light>.png: the bell's inbox, the inbox page,
 *   Settings → Notifications (Carol's, with her own choices), Admin → Email with a failed
 *   send, the "emails aren't going out" banner, the unsubscribe page (a real link from an
 *   email), the mention picker. A second run with E2E_SMTP=0 (`@no-smtp`) adds the
 *   "email isn't set up" banner and the Email page's setup steps.
 * - emails/<template>-<desktop-light|desktop-dark|390-light|390-dark>.png: every
 *   template as `soundings email-preview` renders it (sample data, all thirteen types,
 *   Phases 4 and 8b included), and emails/mailpit-<subject>-…png: real emails this run sent,
 *   as Mailpit received them.
 *
 * The failed send needs a Mailpit container to stop (the local stack's). Needs freshly
 * seeded data (the local stack reseeds on start).
 */

const here = dirname(fileURLToPath(import.meta.url))
const repo = resolve(here, '../..')
const outDir = resolve(process.env.SCREENSHOT_DIR ?? join(here, '../../docs/screenshots/phase-3'))
const emailDir = join(outDir, 'emails')
mkdirSync(emailDir, { recursive: true })

const baseURL = () => test.info().project.use.baseURL ?? ''

test.describe.configure({ mode: 'serial' })

interface Prepared {
  unsubscribe: string | null
  failedSend: boolean
  mail: Message[]
}
let prepared: Prepared | undefined

/**
 * Once per run: a real unsubscribe link and a few real emails (a new person invited,
 * mentioned and made owner in a project that is archived again, so the seeded story
 * looks as seeded), and, with Mailpit stopped for a moment, a test email that failed.
 */
async function prepare(): Promise<Prepared> {
  if (prepared) return prepared
  const alice = await Api.as(baseURL(), 'alice')
  try {
    const summary = await alice.notificationSummary()
    if (!summary.email_available || !(await new Mailpit().isUp())) {
      prepared = { unsubscribe: null, failedSend: false, mail: [] }
      return prepared
    }
    const { theo } = await newPeople(alice, ['theo'])
    const { key } = await projectWithIdea(alice, 'Gift returns', [theo], {
      title: 'Gift returns without a receipt',
    })
    const since = new Date()
    await alice.inviteUsers(key, [theo.user], daysFromNow(6))
    const invitation = await emailTo(theo, /Please evaluate/, since)
    await alice.comment(
      key,
      `@[Theo Marsh](user:${theo.user.id}) the courier can collect from the door, can you check the costs?`,
    )
    const mention = await emailTo(theo, /mentioned you/, since)
    await alice.setOwnerUser(key, theo.user)
    const owner = await emailTo(theo, /owner/, since)
    await theo.api.dispose()
    await alice.archiveCreated()

    let failedSend = false
    if (canControlMailpit()) {
      await stopMailpit()
      try {
        const sent = await alice.sendTestEmail(`ops.${uniqueSuffix()}@example.com`)
        await expect
          .poll(async () => (await alice.outboxEmail(sent.id)).status, { timeout: 30_000 })
          .toBe('failed')
        failedSend = true
      } finally {
        await startMailpit()
      }
    }
    prepared = {
      unsubscribe:
        new URL(unsubscribeLink(invitation)).pathname + new URL(unsubscribeLink(invitation)).search,
      failedSend,
      mail: [invitation, mention, owner],
    }
    return prepared
  } finally {
    await alice.dispose()
  }
}

/** Hides the admins' "emails aren't going out" banner (dismissed for the session). */
async function dismissTroubleBanner(page: Page) {
  await page.addInitScript(() => sessionStorage.setItem('soundings-banner-dismissed:trouble', '1'))
}

interface Shot {
  name: string
  as: Person | null
  /** Keep the admins' email banner (only the banner shots). */
  banner?: boolean
  /** Only in the E2E_SMTP=0 run. */
  noSmtp?: boolean
  open: (page: Page, phone: boolean) => Promise<void>
}

const SHOTS: Shot[] = [
  {
    name: 'inbox-open',
    as: 'alice',
    open: async (page) => {
      await page.goto('/')
      await expect(heading(page, 'My work')).toBeVisible()
      await settled(page)
      await page.getByRole('button', { name: /^Notifications/ }).click()
      const panel = page.getByRole('dialog', { name: 'Notifications' })
      await expect(panel.getByRole('link', { name: /CUST-|TOOLS-|GREEN-/ }).first()).toBeVisible()
    },
  },
  {
    name: 'inbox-page',
    as: 'alice',
    open: async (page) => {
      await page.goto('/notifications')
      await expect(heading(page, 'Notifications')).toBeVisible()
      await expect(
        page
          .locator('main')
          .getByRole('link', { name: /CUST-|TOOLS-|GREEN-/ })
          .first(),
      ).toBeVisible()
    },
  },
  {
    name: 'notification-preferences',
    as: 'carol',
    open: async (page) => {
      await page.goto('/settings/notifications')
      await expect(
        page.getByRole('heading', { level: 2, name: 'Email notifications' }),
      ).toBeVisible()
      await expect(page.getByRole('radiogroup')).toHaveCount(9)
    },
  },
  {
    name: 'admin-email-failed-send',
    as: 'alice',
    banner: true,
    open: async (page) => {
      test.skip(!prepared?.failedSend, 'needs a Mailpit container to stop')
      await page.goto('/settings/email')
      await expect(page.getByRole('heading', { level: 2, name: 'Email' })).toBeVisible()
      const failed = page
        .getByRole('table', { name: 'Outbox emails' })
        .getByRole('row')
        .filter({ hasText: 'Failed' })
      await expect(failed).toBeVisible()
      // The outbox (open on failed email) at the top: the page's status callout is above.
      await page
        .getByRole('heading', { name: 'Outbox' })
        .evaluate((element) => element.scrollIntoView({ block: 'start' }))
    },
  },
  {
    name: 'admin-email-all',
    as: 'alice',
    open: async (page) => {
      await page.goto('/settings/email?status=all')
      await expect(page.getByRole('heading', { level: 2, name: 'Email' })).toBeVisible()
      await expect(
        page.getByRole('table', { name: 'Outbox emails' }).getByRole('row').nth(1),
      ).toBeVisible()
      await page.getByRole('heading', { name: 'Outbox' }).scrollIntoViewIfNeeded()
    },
  },
  {
    name: 'smtp-banner-trouble',
    as: 'alice',
    banner: true,
    open: async (page) => {
      test.skip(!prepared?.failedSend, 'needs a Mailpit container to stop')
      await page.goto('/')
      await expect(heading(page, 'My work')).toBeVisible()
      await expect(page.getByTestId('email-banner')).toBeVisible()
    },
  },
  {
    name: 'unsubscribe',
    as: null,
    open: async (page) => {
      test.skip(!prepared?.unsubscribe, 'needs email (E2E_SMTP=1)')
      await page.goto(prepared?.unsubscribe ?? '')
      await expect(page.getByRole('button', { name: 'Unsubscribe', exact: true })).toBeVisible()
    },
  },
  {
    name: 'unsubscribe-broken-link',
    as: null,
    open: async (page) => {
      await page.goto('/unsubscribe?token=this-link-was-cut-short')
      await expect(
        page.getByRole('heading', { level: 1, name: 'This unsubscribe link doesn’t work' }),
      ).toBeVisible()
    },
  },
  {
    name: 'mention-picker',
    as: 'alice',
    open: async (page) => {
      await page.goto('/ideas/CUST-7')
      await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
      await settled(page)
      const composer = page.getByRole('textbox', { name: 'Write a comment' })
      await composer.scrollIntoViewIfNeeded()
      await composer.click()
      await page.keyboard.type('Thanks, @')
      await expect(
        page.getByRole('listbox', { name: 'People to mention' }).getByRole('option').nth(2),
      ).toBeVisible()
    },
  },
  {
    name: 'smtp-banner-not-configured',
    as: 'alice',
    banner: true,
    noSmtp: true,
    open: async (page) => {
      await page.goto('/')
      await expect(heading(page, 'My work')).toBeVisible()
      await expect(page.getByTestId('email-banner')).toContainText('Email isn’t set up')
    },
  },
  {
    name: 'admin-email-not-configured',
    as: 'alice',
    noSmtp: true,
    open: async (page) => {
      await page.goto('/settings/email')
      await expect(page.getByRole('heading', { name: 'Set up email' })).toBeVisible()
    },
  },
]

const VARIANTS = [
  {
    suffix: '1440-light',
    viewport: { width: 1440, height: 900 },
    colorScheme: 'light',
    phone: false,
  },
  {
    suffix: '1440-dark',
    viewport: { width: 1440, height: 900 },
    colorScheme: 'dark',
    phone: false,
  },
  { suffix: '390-light', viewport: { width: 390, height: 844 }, colorScheme: 'light', phone: true },
] as const

async function shoot(page: Page, path: string, fullPage = false) {
  await settled(page)
  await page.evaluate(() => document.fonts.ready)
  await page.waitForTimeout(500) // enter animations
  await page.screenshot({ path, animations: 'disabled', caret: 'hide', fullPage })
}

test.beforeAll(async () => {
  await prepare()
})

for (const variant of VARIANTS) {
  test.describe(variant.suffix, () => {
    test.use({
      viewport: variant.viewport,
      colorScheme: variant.colorScheme,
      isMobile: variant.phone,
      hasTouch: variant.phone,
    })

    for (const shot of SHOTS) {
      const tag = shot.noSmtp ? ['@no-smtp'] : []
      test(`${shot.name}-${variant.suffix}`, { tag }, async ({ page }) => {
        const email = (await (await Api.as(baseURL(), 'alice')).notificationSummary())
          .email_available
        test.skip(Boolean(shot.noSmtp) === email, shot.noSmtp ? 'E2E_SMTP=0 only' : 'needs SMTP')
        if (!shot.banner) await dismissTroubleBanner(page)
        if (shot.as) await signIn(page, shot.as)
        await shot.open(page, variant.phone)
        await shoot(page, join(outDir, `${shot.name}-${variant.suffix}.png`))
      })
    }
  })
}

// --- Emails -------------------------------------------------------------------------------
const EMAIL_VARIANTS = [
  { suffix: 'desktop-light', viewport: { width: 1024, height: 900 }, colorScheme: 'light' },
  { suffix: 'desktop-dark', viewport: { width: 1024, height: 900 }, colorScheme: 'dark' },
  { suffix: '390-light', viewport: { width: 390, height: 844 }, colorScheme: 'light' },
  { suffix: '390-dark', viewport: { width: 390, height: 844 }, colorScheme: 'dark' },
] as const

/** Every template with sample data: `soundings email-preview` (backend), into a temp dir. */
function previewTemplates(): { name: string; html: string }[] {
  const dir = join(tmpdir(), `soundings-email-preview-${process.pid}`)
  execFileSync(
    'uv',
    ['run', '--quiet', 'soundings', 'email-preview', '-o', dir, '--base-url', baseURL()],
    {
      cwd: join(repo, 'backend'),
      stdio: 'ignore',
    },
  )
  return readdirSync(dir)
    .filter((file) => file.endsWith('.html') && file !== 'index.html')
    .sort()
    .map((file) => ({
      name: file.replace(/\.html$/, ''),
      html: readFileSync(join(dir, file), 'utf8'),
    }))
}

async function shootEmail(browser: Browser, html: string, name: string) {
  for (const variant of EMAIL_VARIANTS) {
    const context = await browser.newContext({
      viewport: variant.viewport,
      colorScheme: variant.colorScheme,
      isMobile: variant.suffix.startsWith('390'),
    })
    const page = await context.newPage()
    await page.setContent(html, { waitUntil: 'load' })
    await page.screenshot({ path: join(emailDir, `${name}-${variant.suffix}.png`), fullPage: true })
    await context.close()
  }
}

test('emails: every template (email-preview) and real emails from Mailpit', async ({ browser }) => {
  test.setTimeout(180_000)
  const email = (await (await Api.as(baseURL(), 'alice')).notificationSummary()).email_available
  test.skip(!email, 'needs SMTP')
  for (const template of previewTemplates()) await shootEmail(browser, template.html, template.name)
  const slug = (subject: string) =>
    subject
      .toLowerCase()
      .replace(/\[[^\]]*\]/g, '')
      .replace(/[^a-z]+/g, '-')
      .replace(/^-|-$/g, '')
      .slice(0, 40)
  for (const message of prepared?.mail ?? []) {
    await shootEmail(browser, message.HTML, `mailpit-${slug(message.Subject)}`)
  }
})
