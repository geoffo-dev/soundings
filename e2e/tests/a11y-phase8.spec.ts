import type { Page } from '@playwright/test'

import { Api, createTeamProject, type Person } from './support/api'
import {
  bestPracticeViolations,
  expect,
  heading,
  seriousViolations,
  settled,
  signIn,
  test,
} from './support/fixtures'
import { proposalTemplate, researchTeam, setProposalTemplate } from './support/research'

/**
 * axe (WCAG 2.2 AA rules, serious and critical) on the Phase 8 screens against the real
 * app, light and dark: Project settings → Research (the step locked while an idea is in
 * Research, the checklist) and → Proposal (with a removed section), the Internal Tools
 * board with its Research column and progress badges, the research gate dialog, the idea
 * page's Research panel (answerable, and complete with Similar ideas), the proposal
 * editor with a custom template and the research appendix. axe's best-practice rules on
 * the screens without overlays, and the same screens at 390 px without sideways
 * scrolling. Test plan: A11Y8-*, MO8-*.
 */

const baseURL = () => test.info().project.use.baseURL ?? ''

interface Prepared {
  researchSlug: string
  templateSlug: string
}
let prepared: Promise<Prepared> | undefined

/** Once per worker: a project in Research and one whose template lost a section. */
function prepare(): Promise<Prepared> {
  prepared ??= (async () => {
    const alice = await Api.as(baseURL(), 'alice')
    try {
      const research = await researchTeam(alice, 'A11y research', 'before_evaluation', {
        bob: 'member',
      })
      const idea = await alice.createIdea(research.slug, {
        title: 'Gift wrapping at the till',
        summary: 'Wrap presents at the till in December.',
      })
      await alice.setOwner(idea.key, 'bob')
      await alice.changeStatus(idea.key, 'research')

      const templated = await createTeamProject(alice, 'A11y template', { bob: 'member' })
      const withText = await alice.createIdea(templated.slug, {
        title: 'Gift wrap kiosks',
        summary: 'Self-service gift wrapping by the tills.',
      })
      await alice.setOwner(withText.key, 'bob')
      await alice.changeStatus(withText.key, 'shortlisted')
      await alice.startProposal(withText.key)
      await alice.writeSections(withText.key, { cost: 'Two kiosks at £4,000 each.' })
      const template = await proposalTemplate(alice, templated.slug)
      await setProposalTemplate(alice, templated.slug, [
        ...template.sections
          .filter((section) => section.key !== 'cost')
          .map(({ key, title, hint }) => ({ key, title, hint })),
        { title: 'Pilot plan', hint: 'Where we try it first.' },
      ])
      return { researchSlug: research.slug, templateSlug: templated.slug }
    } finally {
      await alice.dispose()
    }
  })()
  return prepared
}

interface Screen {
  name: string
  as: Person
  /** Has an overlay open (best-practice rules don't apply: portalled outside landmarks). */
  overlay?: boolean
  open: (page: Page, data: Prepared) => Promise<void>
}

const SCREENS: Screen[] = [
  {
    name: 'project settings: research step and checklist',
    as: 'alice',
    open: async (page, data) => {
      await page.goto(`/p/${data.researchSlug}/settings?tab=research`)
      await expect(page.getByRole('heading', { name: 'Research step' })).toBeVisible()
      await expect(page.getByRole('list', { name: 'Checklist items' })).toBeVisible()
    },
  },
  {
    name: 'project settings: proposal template with a removed section',
    as: 'alice',
    open: async (page, data) => {
      await page.goto(`/p/${data.templateSlug}/settings?tab=proposal-template`)
      await expect(page.getByRole('heading', { name: 'Removed sections' })).toBeVisible()
    },
  },
  {
    name: 'board with the Research column',
    as: 'dave',
    open: async (page) => {
      await page.goto('/p/internal-tools?view=board')
      await expect(heading(page, 'Internal Tools')).toBeVisible()
      await expect(page.getByRole('region', { name: /^Research\b/ })).toBeVisible()
    },
  },
  {
    name: 'the research gate dialog',
    as: 'sven',
    overlay: true,
    open: async (page) => {
      await page.goto('/p/internal-tools?view=board')
      await expect(heading(page, 'Internal Tools')).toBeVisible()
      await settled(page)
      const announcer = page.locator('[id^="DndLiveRegion"]')
      await page.getByRole('link', { name: /\(TOOLS-12\)$/ }).focus()
      await page.keyboard.press('Space')
      await expect(announcer).toContainText('Picked up TOOLS-12')
      await page.keyboard.press('ArrowRight')
      await expect(announcer).toContainText('TOOLS-12 is over')
      await page.keyboard.press('Space')
      await expect(page.getByRole('dialog', { name: 'Finish the research first' })).toBeVisible()
    },
  },
  {
    name: 'idea page: the Research panel, answerable',
    as: 'sven',
    open: async (page) => {
      await page.goto('/ideas/TOOLS-12')
      await expect(
        page.getByRole('region', { name: 'Research' }).getByRole('textbox').first(),
      ).toBeVisible()
    },
  },
  {
    name: 'idea page: the Research panel, complete, with Similar ideas',
    as: 'carol',
    open: async (page) => {
      await page.goto('/ideas/TOOLS-11')
      const panel = page.getByRole('region', { name: 'Research' })
      await expect(panel.getByRole('link', { name: /CUST-14/ })).toBeVisible()
    },
  },
  {
    name: 'proposal editor: a custom template and the research appendix',
    as: 'kenji',
    open: async (page) => {
      await page.goto('/ideas/TOOLS-3?tab=proposal')
      await expect(page.getByRole('region', { name: 'Research and consultation' })).toBeVisible()
    },
  },
]

for (const colorScheme of ['light', 'dark'] as const) {
  test.describe(`${colorScheme} theme`, () => {
    test.use({ colorScheme })

    for (const screen of SCREENS) {
      test(`A11Y8: ${screen.name} has no serious or critical violations`, async ({ page }) => {
        const data = await prepare()
        await signIn(page, screen.as)
        await screen.open(page, data)
        await settled(page)
        await expect(page.locator('html')).toHaveClass(
          colorScheme === 'dark' ? /\bdark\b/ : /^(?!.*\bdark\b)/,
        )
        await page.waitForTimeout(300) // enter animations: axe sees final colours
        expect(await seriousViolations(page)).toEqual([])
        if (!screen.overlay && colorScheme === 'light') {
          expect(await bestPracticeViolations(page)).toEqual([])
        }
      })
    }
  })
}

test.describe('on a phone (390 px)', () => {
  test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true })

  test('MO8-01: the Phase 8 screens fit without sideways scrolling', async ({ page }) => {
    test.setTimeout(180_000)
    const data = await prepare()
    const overflow = () =>
      page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      )
    for (const screen of SCREENS) {
      // The gate dialog is opened by a keyboard drag, which phones don't have.
      if (screen.overlay) continue
      await signIn(page, screen.as)
      await screen.open(page, data)
      await settled(page)
      expect(await overflow(), screen.name).toBeLessThanOrEqual(0)
    }
  })
})
