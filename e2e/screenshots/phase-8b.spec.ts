import { mkdirSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import type { Locator, Page } from '@playwright/test'

import { Api, daysFromNow, type Person } from '../tests/support/api'
import { disposePeople, Mailpit, newPeople, signInAs, type Someone } from '../tests/support/email'
import { expect, settled, signIn, test } from '../tests/support/fixtures'
import { answerItem, assignResearcher, CHECKLIST, researchTeam } from '../tests/support/research'

/**
 * Review screenshots of the Phase 8b screens (the research assigned to a person) from the
 * real app with the demo data. Not a regression test.
 *
 * `npm run screenshots:phase8b` → docs/screenshots/phase-8b/ (`SCREENSHOT_DIR` overrides):
 * <screen>-<1440-light|1440-dark|390-light>.png, and emails/ ("Asked to research" as
 * Mailpit received it). The demo story: bob researches TOOLS-12 (the private Internal
 * Tools, where he has no role) as its guest, due in three days, asked by dave; alice's
 * GREEN-5 research is overdue. The assign dialog as dave (TOOLS-12's project admin, with
 * bob, an outsider, chosen); "Start research" as amara on GREEN-6 (Farah chosen, due in a
 * week; nothing is saved); TOOLS-12's Research panel as sven (its owner); TOOLS-12 as bob;
 * My work's "Research to do" as alice. The email comes from a private project of its own
 * ("Facilities"), whose admin asks a new person (Nora Quinn) to research an idea; the
 * project is archived afterwards. Otherwise read-only.
 *
 * The review follow-ups, in projects of their own (archived afterwards; nothing is saved
 * from the dialogs): `research-read-only-past-research` (D1: Nora, outside the private
 * "Workplace", reads the answers of an idea that has moved on), `remove-researcher-past-
 * research` (L2: past Research the owner gets Remove, with its confirmation) and
 * `make-private-confirm` (D2: making the internal "Office moves" private, where Nora
 * researches an idea, asks first).
 */

const here = dirname(fileURLToPath(import.meta.url))
const outDir = resolve(process.env.SCREENSHOT_DIR ?? join(here, '../../docs/screenshots/phase-8b'))
const emailDir = join(outDir, 'emails')
mkdirSync(emailDir, { recursive: true })

const baseURL = () => test.info().project.use.baseURL ?? ''
const researcherLine = (page: Page) => page.getByTestId('researcher-line')

test.describe.configure({ mode: 'serial' })

/** Scrolls `target` to the top of its scrolling container (below any sticky bar). */
async function scrollTo(target: Locator) {
  await expect(target).toBeVisible()
  await target.evaluate((node) => node.scrollIntoView({ block: 'start' }))
}

interface Shot {
  name: string
  as: Person
  fullPage?: boolean
  open: (page: Page, phone: boolean) => Promise<void>
}

const SHOTS: Shot[] = [
  {
    name: 'assign-picker-outsider',
    as: 'dave',
    open: async (page) => {
      await page.goto('/ideas/TOOLS-12')
      await researcherLine(page)
        .getByRole('button', { name: 'Change researcher or due date' })
        .click()
      const dialog = page.getByRole('dialog', { name: 'Who does the research' })
      await expect(dialog).toContainText('Chosen: Bob Brown · Not in this project')
      await expect(dialog.getByRole('status')).toBeVisible()
    },
  },
  {
    name: 'start-research-dialog',
    as: 'amara',
    open: async (page) => {
      await page.goto('/ideas/GREEN-6')
      await page.getByRole('button', { name: 'Start research' }).first().click()
      const dialog = page.getByRole('dialog', { name: 'Start research' })
      await dialog.getByRole('combobox', { name: 'Researcher' }).fill('farah')
      await dialog.getByRole('option', { name: /Farah Haddad/ }).click()
      await expect(dialog).toContainText('Chosen: Farah Haddad')
      await dialog.getByRole('button', { name: 'In a week' }).click()
    },
  },
  {
    name: 'research-panel-researcher-due',
    as: 'sven',
    open: async (page) => {
      await page.goto('/ideas/TOOLS-12')
      await expect(researcherLine(page)).toContainText('Bob Brown')
      await scrollTo(page.getByRole('region', { name: 'Research' }))
    },
  },
  {
    name: 'guest-researcher-idea',
    as: 'bob',
    open: async (page) => {
      await page.goto('/ideas/TOOLS-12')
      await expect(
        page.getByText('You can see this idea because you’re researching it.'),
      ).toBeVisible()
      // The guest's own line says "You" (no "not in this project" about yourself).
      await expect(researcherLine(page)).toContainText('You')
    },
  },
  {
    name: 'my-work-research-to-do-overdue',
    as: 'alice',
    open: async (page) => {
      await page.goto('/')
      const section = page.getByRole('region', { name: /Research to do/ })
      await expect(section.getByRole('listitem').first()).toContainText(/Overdue/)
      await scrollTo(section)
    },
  },
]

// --- The review follow-ups (D1, L2, D2) ----------------------------------------------------
interface FollowUps {
  nora: Someone
  readOnlyKey: string
  removeKey: string
  officeSlug: string
}
let followUps: Promise<FollowUps> | undefined
const cleanups: (() => Promise<void>)[] = []

/** Once per run: Nora Quinn, a new person, researching ideas in two projects of the spec's own. */
async function buildFollowUps(): Promise<FollowUps> {
  const alice = await Api.as(baseURL(), 'alice')
  const people = await newPeople(alice, ['nora'])
  const { nora } = people
  cleanups.push(async () => {
    await disposePeople(people)
    await alice.archiveCreated()
    await alice.dispose()
  })
  // D1 and L2: the private "Workplace", where Nora has no role; two ideas she researched
  // have moved on to Evaluating.
  const workplace = await researchTeam(alice, 'Workplace', 'before_evaluation', {})
  await alice.send('PATCH', `/projects/${workplace.slug}`, { name: 'Workplace' })
  const keys: string[] = []
  for (const [title, summary] of [
    [
      'Quiet room on the fourth floor',
      'Turn the small meeting room by the lifts into a quiet room.',
    ],
    ['Standing desks by the windows', 'Six standing desks along the south windows.'],
  ] as const) {
    const idea = await alice.createIdea(workplace.slug, { title, summary })
    await alice.setOwner(idea.key, 'alice')
    await alice.changeStatus(idea.key, 'research')
    await assignResearcher(alice, idea.key, nora.user, daysFromNow(3))
    await answerItem(
      nora.api,
      idea.key,
      CHECKLIST.elsewhere,
      'Facilities, 7 Oct: nothing planned for the fourth floor.',
    )
    await answerItem(
      nora.api,
      idea.key,
      CHECKLIST.consulted,
      'Facilities and HR, 8 Oct: both in favour; HR asks for simple booking rules.',
    )
    await alice.changeStatus(idea.key, 'evaluating')
    keys.push(idea.key)
  }
  // D2: the internal "Office moves", where Nora researches an idea from outside.
  const office = await researchTeam(alice, 'Office moves', 'before_evaluation', {})
  await alice.send('PATCH', `/projects/${office.slug}`, {
    name: 'Office moves',
    visibility: 'internal',
  })
  const bikes = await alice.createIdea(office.slug, {
    title: 'Pool bikes for site visits',
    summary: 'Two bikes at reception for trips between the offices.',
  })
  await alice.setOwner(bikes.key, 'alice')
  await assignResearcher(alice, bikes.key, nora.user, daysFromNow(5))
  const [readOnlyKey, removeKey] = keys
  if (!readOnlyKey || !removeKey) throw new Error('the Workplace ideas were not created')
  return { nora, readOnlyKey, removeKey, officeSlug: office.slug }
}

function arrangeFollowUps(): Promise<FollowUps> {
  const arranged = followUps ?? buildFollowUps()
  followUps = arranged
  return arranged
}

test.afterAll(async () => {
  for (const cleanup of cleanups.splice(0)) await cleanup()
})

const FOLLOW_UPS: {
  name: string
  open: (page: Page, arranged: FollowUps) => Promise<void>
}[] = [
  {
    name: 'research-read-only-past-research',
    open: async (page, { nora, readOnlyKey }) => {
      await signInAs(page, nora)
      await page.goto(`/ideas/${readOnlyKey}`)
      const panel = page.getByRole('region', { name: 'Research' })
      // Past Research the panel starts folded for her.
      await panel.getByRole('button', { name: 'Research', exact: true }).click()
      await expect(
        panel.getByText(
          'The idea has moved past Research, so only its owner or an admin can change these answers now.',
        ),
      ).toBeVisible()
      await scrollTo(panel)
    },
  },
  {
    name: 'remove-researcher-past-research',
    open: async (page, { removeKey }) => {
      await signIn(page, 'alice')
      await page.goto(`/ideas/${removeKey}`)
      const panel = page.getByRole('region', { name: 'Research' })
      await panel.getByRole('button', { name: 'Research', exact: true }).click()
      await researcherLine(page).getByRole('button', { name: 'Remove the researcher' }).click()
      await expect(
        page.getByRole('alertdialog', { name: /^Remove Nora Quinn as researcher\?$/ }),
      ).toBeVisible()
    },
  },
  {
    name: 'make-private-confirm',
    open: async (page, { officeSlug }) => {
      await signIn(page, 'alice')
      await page.goto(`/p/${officeSlug}/settings`)
      await page.getByRole('radio', { name: /Private/ }).check()
      await page.getByRole('button', { name: /Save changes/ }).click()
      await expect(
        page.getByRole('alertdialog', { name: 'Make this project private?' }),
      ).toContainText('will lose access')
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

test('email: “Asked to research” as a guest researcher received it', async ({ browser }) => {
  test.setTimeout(120_000)
  const alice = await Api.as(baseURL(), 'alice')
  const people = await newPeople(alice, ['nora'])
  try {
    test.skip(!(await alice.notificationSummary()).email_available, 'needs SMTP')
    test.skip(!(await new Mailpit().isUp()), 'needs the stack’s Mailpit')
    const project = await researchTeam(alice, 'Facilities', 'before_evaluation', {})
    const idea = await alice.createIdea(project.slug, {
      title: 'Badge reader for the bike shed',
      summary: 'Open the bike shed with the staff badge instead of a shared key.',
    })
    await alice.setOwner(idea.key, 'alice')
    await alice.changeStatus(idea.key, 'research')
    const since = new Date()
    await assignResearcher(alice, idea.key, people.nora.user, daysFromNow(5))
    const message = await new Mailpit().waitForMessage(people.nora.email, {
      since,
      subject: `[${idea.key}] Please research`,
      timeoutMs: 30_000,
    })
    for (const variant of [
      { suffix: 'desktop-light', viewport: { width: 1000, height: 900 }, colorScheme: 'light' },
      { suffix: 'desktop-dark', viewport: { width: 1000, height: 900 }, colorScheme: 'dark' },
      { suffix: '390-light', viewport: { width: 390, height: 844 }, colorScheme: 'light' },
    ] as const) {
      const context = await browser.newContext({
        viewport: variant.viewport,
        colorScheme: variant.colorScheme,
        isMobile: variant.suffix.startsWith('390'),
      })
      const page = await context.newPage()
      await page.setContent(message.HTML, { waitUntil: 'load' })
      await page.screenshot({
        path: join(emailDir, `asked-to-research-${variant.suffix}.png`),
        fullPage: true,
      })
      await context.close()
    }
  } finally {
    await disposePeople(people)
    await alice.archiveCreated()
    await alice.dispose()
  }
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
      test(`${shot.name}-${variant.suffix}`, async ({ page }) => {
        test.setTimeout(60_000)
        await signIn(page, shot.as)
        await shot.open(page, variant.phone)
        await shoot(page, join(outDir, `${shot.name}-${variant.suffix}.png`), shot.fullPage)
      })
    }
  })
}

// After every seeded-story shot: the follow-ups' projects ("Office moves" is internal, so
// in everyone's sidebar) must not appear in them.
for (const variant of VARIANTS) {
  test.describe(`${variant.suffix} follow-ups`, () => {
    test.use({
      viewport: variant.viewport,
      colorScheme: variant.colorScheme,
      isMobile: variant.phone,
      hasTouch: variant.phone,
    })

    for (const shot of FOLLOW_UPS) {
      test(`${shot.name}-${variant.suffix}`, async ({ page }) => {
        test.setTimeout(90_000)
        await shot.open(page, await arrangeFollowUps())
        await shoot(page, join(outDir, `${shot.name}-${variant.suffix}.png`))
      })
    }
  })
}
