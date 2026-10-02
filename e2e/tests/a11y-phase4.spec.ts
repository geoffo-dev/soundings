import type { Page } from '@playwright/test'

import { Api, type Person } from './support/api'
import { expect, heading, seriousViolations, settled, signIn, test } from './support/fixtures'
import {
  brandingUpdate,
  fillPublicForm,
  humanCheckDone,
  projectWithPublicForm,
  svgLogo,
  Visitor,
} from './support/public'

/**
 * axe (WCAG 2.2 AA rules) on the Phase 4 screens against the real app, light and dark: no
 * serious or critical violations. Then the same screens at 390 px: no sideways scrolling.
 * The public pages are in a project's branding (the seeded Customer Innovation form, and
 * a fresh project with the same green, IBM Plex Sans and an SVG logo): branded colours
 * must stay readable. Test plan: A11Y4-* and MO4-*.
 */

const baseURL = () => test.info().project.use.baseURL ?? ''

interface Prepared {
  slug: string
  token: string
  heldKey: string
  approvedKey: string
  proposalKey: string
}

let prepared: Promise<Prepared> | undefined

/** Once per worker: a branded project with a public form, ideas in every state, a proposal. */
function prepare(): Promise<Prepared> {
  prepared ??= (async () => {
    const alice = await Api.as(baseURL(), 'alice')
    try {
      const project = await projectWithPublicForm(alice, 'A11y public', {
        bob: 'member',
        carol: 'member',
        erin: 'viewer',
      })
      const logo = await alice.uploadBrandAsset(
        'logo',
        svgLogo('A11y public', '#0b6e4f'),
        'image/svg+xml',
        project.slug,
      )
      await alice.setProjectBranding(
        project.slug,
        brandingUpdate({
          primary_color: '#0b6e4f',
          accent_color: '#c2410c',
          font: 'ibm_plex_sans',
          logo_asset_id: logo.id,
        }),
      )
      const visitor = await Visitor.open(baseURL())
      const tracked = await visitor.submitted(project.slug, {
        title: 'Quiet hour on Tuesday mornings',
        summary: 'Dim the lights and turn the music off for an hour a week.',
        name: 'Sam',
      })
      await visitor.submitted(project.slug, {
        title: 'Free water refills',
        summary: 'A tap by the entrance for refilling bottles.',
        description_md: 'Lots of stores do this already.\n\n- cheap\n- popular',
      })
      const approved = await visitor.submitted(project.slug, {
        title: 'Recycling point for batteries',
        summary: 'A box by the tills for old batteries.',
        name: 'Jo Public',
      })
      await visitor.dispose()
      const queue = await alice.moderationQueue(project.slug)
      const byTitle = (title: string) => queue.items.find((item) => item.title === title)?.key ?? ''
      const approvedKey = byTitle('Recycling point for batteries')
      await alice.approve(approvedKey)
      expect(approved.held_for).toBe('moderation')

      const idea = await alice.createIdea(project.slug, {
        title: 'Same-day delivery in city centres',
        summary: 'Cargo bikes deliver orders placed before noon the same day.',
      })
      await alice.setOwner(idea.key, 'bob')
      await alice.changeStatus(idea.key, 'shortlisted')
      const bob = await Api.as(baseURL(), 'bob')
      await bob.startProposal(idea.key)
      await bob.writeSections(idea.key, {
        problem: 'Customers wait **three days** for a parcel.\n\n- 1,200 complaints a quarter',
        solution: 'Cargo bikes from two city hubs.',
      })
      const carol = await Api.as(baseURL(), 'carol')
      const thread = await carol.startThread(idea.key, 'problem', 'Where do the 1,200 come from?')
      await bob.reply(idea.key, thread.id, 'The ops report, Q3.')
      const done = await carol.startThread(idea.key, 'solution', 'Two hubs or three?')
      await bob.resolveThread(idea.key, done.id)
      await bob.dispose()
      await carol.dispose()
      return {
        slug: project.slug,
        token: tracked.tracking_token,
        heldKey: byTitle('Quiet hour on Tuesday mornings'),
        approvedKey,
        proposalKey: idea.key,
      }
    } finally {
      await alice.dispose()
    }
  })()
  return prepared
}

interface Screen {
  name: string
  as: Person | null
  /** `phone`: at 390 px (written sections open in Preview, threads in a sheet). */
  open: (page: Page, data: Prepared, phone: boolean) => Promise<void>
}

const SCREENS: Screen[] = [
  {
    name: 'public: the seeded Customer Innovation form',
    as: null,
    open: async (page) => {
      await page.goto('/customer-innovation/submit')
      await expect(
        page.getByRole('heading', { level: 1, name: 'Share an idea with Customer Innovation' }),
      ).toBeVisible()
      await expect(page.locator('header img')).toBeVisible()
    },
  },
  {
    name: 'public: the receipt after sending',
    as: null,
    open: async (page, data) => {
      await page.goto(`/${data.slug}/submit`)
      await fillPublicForm(page, {
        title: 'Seats by the fitting rooms',
        summary: 'Somewhere to sit while you wait.',
      })
      await humanCheckDone(page)
      await page.getByRole('button', { name: 'Send idea' }).click()
      await expect(
        page.getByRole('heading', { level: 1, name: 'Thanks! Your idea is in' }),
      ).toBeVisible()
    },
  },
  {
    name: 'public: the tracking page',
    as: null,
    open: async (page, data) => {
      await page.goto(`/track#${data.token}`)
      await expect(
        page.getByRole('heading', { level: 1, name: 'Quiet hour on Tuesday mornings' }),
      ).toBeVisible()
    },
  },
  {
    name: 'public: a tracking link that doesn’t work',
    as: null,
    open: async (page) => {
      await page.goto(`/track#${'A'.repeat(43)}`)
      await expect(
        page.getByRole('heading', { level: 1, name: 'We can’t find this submission' }),
      ).toBeVisible()
    },
  },
  {
    name: 'public: confirm your email address',
    as: null,
    open: async (page) => {
      await page.goto('/verify#eyJ2IjoxfQ.c2lnbmF0dXJl')
      await expect(
        page.getByRole('heading', { level: 1, name: 'Confirm your email address' }),
      ).toBeVisible()
    },
  },
  {
    name: 'proposal: the editor with margin threads (owner)',
    as: 'bob',
    open: async (page, data, phone) => {
      await page.goto(`/ideas/${data.proposalKey}?tab=proposal`)
      if (phone) {
        await expect(page.getByRole('region', { name: 'Problem (preview)' })).toBeVisible()
        return
      }
      await expect(page.getByRole('textbox', { name: 'Problem', exact: true })).toBeVisible()
      await expect(page.getByText('Where do the 1,200 come from?')).toBeVisible()
    },
  },
  {
    name: 'proposal: the export menu',
    as: 'bob',
    open: async (page, data) => {
      await page.goto(`/ideas/${data.proposalKey}?tab=proposal`)
      await expect(page.getByRole('heading', { level: 2, name: /Problem$/ })).toBeVisible()
      await page.getByRole('button', { name: 'Export' }).click()
      await expect(page.getByRole('menuitem', { name: /PDF/ })).toBeVisible()
    },
  },
  {
    name: 'proposal: a viewer reading it',
    as: 'erin',
    open: async (page, data) => {
      await page.goto(`/ideas/${data.proposalKey}?tab=proposal`)
      await expect(page.getByRole('heading', { level: 2, name: /Problem$/ })).toBeVisible()
      await expect(page.getByText('Cargo bikes from two city hubs.')).toBeVisible()
    },
  },
  {
    name: 'moderation: the review queue',
    as: 'alice',
    open: async (page, data) => {
      await page.goto(`/p/${data.slug}/review`)
      await expect(page.getByRole('list', { name: 'Ideas waiting for review' })).toBeVisible()
      await expect(page.getByText('Free water refills')).toBeVisible()
    },
  },
  {
    name: 'moderation: an idea waiting for review (admin)',
    as: 'alice',
    open: async (page, data) => {
      await page.goto(`/ideas/${data.heldKey}`)
      await expect(page.getByRole('region', { name: 'Waiting for review' })).toBeVisible()
    },
  },
  {
    name: 'idea: the public submission panel',
    as: 'alice',
    open: async (page, data, phone) => {
      await page.goto(`/ideas/${data.approvedKey}`)
      await expect(heading(page, 'Recycling point for batteries')).toBeVisible()
      // On phones the details (with the panel) are a sheet behind the summary line.
      if (!phone) await expect(page.getByText('Sent by Jo Public')).toBeVisible()
    },
  },
  {
    name: 'settings: branding with its live preview',
    as: 'alice',
    open: async (page) => {
      await page.goto('/settings/branding')
      await expect(page.getByRole('heading', { level: 2, name: 'Branding' })).toBeVisible()
      await expect(page.getByTestId('branding-preview').first()).toBeVisible()
    },
  },
  {
    name: 'project settings: public form',
    as: 'alice',
    open: async (page, data) => {
      await page.goto(`/p/${data.slug}/settings?tab=public-form`)
      await expect(
        page.getByRole('switch', { name: 'Accept ideas through the public form' }),
      ).toBeChecked()
    },
  },
  {
    name: 'project settings: branding',
    as: 'alice',
    open: async (page, data) => {
      await page.goto(`/p/${data.slug}/settings?tab=branding`)
      await expect(
        page.getByRole('tabpanel', { name: 'Branding' }).getByTestId('branding-preview').first(),
      ).toBeVisible()
    },
  },
]

for (const colorScheme of ['light', 'dark'] as const) {
  test.describe(`${colorScheme} theme`, () => {
    test.use({ colorScheme })

    for (const screen of SCREENS) {
      test(`A11Y4: ${screen.name} has no serious or critical violations`, async ({ page }) => {
        const data = await prepare()
        if (screen.as) await signIn(page, screen.as)
        await screen.open(page, data, false)
        await settled(page)
        await expect(page.locator('html')).toHaveClass(
          colorScheme === 'dark' ? /\bdark\b/ : /^(?!.*\bdark\b)/,
        )
        await page.waitForTimeout(300) // enter animations: axe sees final colours
        expect(await seriousViolations(page)).toEqual([])
      })
    }
  })
}

test.describe('on a phone (390 px)', () => {
  test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true })

  test('MO4-01: the Phase 4 screens fit without sideways scrolling', async ({ page }) => {
    test.setTimeout(180_000)
    const data = await prepare()
    const overflow = () =>
      page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      )
    for (const screen of SCREENS) {
      await test.step(screen.name, async () => {
        await page.context().clearCookies()
        if (screen.as) await signIn(page, screen.as)
        await screen.open(page, data, true)
        await page.waitForTimeout(200)
        expect(await overflow(), screen.name).toBe(0)
      })
    }
  })

  test('MO4-02: the public form is comfortable to use with a thumb', async ({ page, api }) => {
    const alice = await api('alice')
    test.skip(
      !(await alice.notificationSummary()).email_available,
      'needs SMTP (the address field)',
    )
    await page.goto('/customer-innovation/submit')
    const form = page.getByRole('form', { name: 'Your idea' })
    await expect(form).toBeVisible()
    // Fields are 44 px tall on phones (iOS HIG); the full-width button at least 40 px.
    for (const field of [
      form.getByRole('textbox', { name: 'Title' }),
      form.getByRole('textbox', { name: 'Your name (optional)' }),
      form.getByRole('textbox', { name: /^Your email/ }),
    ]) {
      expect((await field.boundingBox())?.height ?? 0).toBeGreaterThanOrEqual(44)
    }
    const send = await form.getByRole('button', { name: 'Send idea' }).boundingBox()
    expect(send?.height ?? 0).toBeGreaterThanOrEqual(40)
    expect(send?.width ?? 0).toBeGreaterThan(300)
    // The address field brings up the email keyboard; nothing is zoomed on focus (16 px).
    const email = form.getByRole('textbox', { name: /^Your email/ })
    await expect(email).toHaveAttribute('inputmode', 'email')
    await expect(email).toHaveAttribute('type', 'email')
    const size = await email.evaluate((element) => getComputedStyle(element).fontSize)
    expect(Number.parseFloat(size)).toBeGreaterThanOrEqual(16)
    expect(await seriousViolations(page)).toEqual([])
  })
})
