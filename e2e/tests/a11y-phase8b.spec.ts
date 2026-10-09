import type { Page } from '@playwright/test'

import { type Person } from './support/api'
import {
  bestPracticeViolations,
  expect,
  seriousViolations,
  settled,
  signIn,
  test,
} from './support/fixtures'

/**
 * axe (WCAG 2.2 AA rules, serious and critical) on the Phase 8b screens against the real
 * app with the demo data, light and dark: the guest researcher's idea page (bob on
 * TOOLS-12), My work with "Research to do" and an overdue item (alice), the Research panel
 * with an outside researcher and its due date (sven, TOOLS-12's owner), the board's
 * Research column with the researcher's avatar (dave), the assign dialog with an outsider
 * chosen (dave, TOOLS-12's project admin) and the "Start research" dialog (amara on
 * GREEN-6). axe's best-practice rules on the screens without overlays; the same screens
 * at 390 px without sideways scrolling; the assign dialog with the keyboard only (focus
 * back on its opener). Read-only: nothing is saved. Test plan: A11Y8B-*, MO8B-*, K8B-*.
 */

const researcherLine = (page: Page) => page.getByTestId('researcher-line')

interface Screen {
  name: string
  as: Person
  /** Has an overlay open (best-practice rules don't apply: portalled outside landmarks). */
  overlay?: boolean
  open: (page: Page) => Promise<void>
}

const SCREENS: Screen[] = [
  {
    name: 'the guest researcher’s idea page',
    as: 'bob',
    open: async (page) => {
      await page.goto('/ideas/TOOLS-12')
      await expect(
        page.getByText('You can see this idea because you’re researching it.'),
      ).toBeVisible()
      await expect(researcherLine(page)).toContainText(/Research:.*You/)
    },
  },
  {
    name: 'My work with research to do (one overdue)',
    as: 'alice',
    open: async (page) => {
      await page.goto('/')
      const section = page.getByRole('region', { name: /Research to do/ })
      await expect(section.getByRole('listitem').first()).toContainText(/Overdue/)
    },
  },
  {
    name: 'the Research panel with an outside researcher and a due date',
    as: 'sven',
    open: async (page) => {
      await page.goto('/ideas/TOOLS-12')
      await expect(researcherLine(page)).toContainText('Bob Brown')
      await expect(researcherLine(page)).toContainText('due')
    },
  },
  {
    name: 'the board’s Research column with the researcher’s avatar',
    as: 'dave',
    open: async (page) => {
      await page.goto('/p/internal-tools?view=board')
      await expect(
        page
          .getByRole('region', { name: /^Research\b/ })
          .getByRole('img', { name: 'Researched by Bob Brown' }),
      ).toBeVisible()
    },
  },
  {
    name: 'the assign dialog with an outsider chosen',
    as: 'dave',
    overlay: true,
    open: async (page) => {
      await page.goto('/ideas/TOOLS-12')
      await researcherLine(page)
        .getByRole('button', { name: 'Change researcher or due date' })
        .click()
      const dialog = page.getByRole('dialog', { name: 'Who does the research' })
      await expect(dialog).toContainText('Chosen: Bob Brown · Not in this project')
    },
  },
  {
    name: 'the “Start research” dialog',
    as: 'amara',
    overlay: true,
    open: async (page) => {
      await page.goto('/ideas/GREEN-6')
      await page.getByRole('button', { name: 'Start research' }).first().click()
      await expect(page.getByRole('dialog', { name: 'Start research' })).toBeVisible()
    },
  },
]

for (const colorScheme of ['light', 'dark'] as const) {
  test.describe(`${colorScheme} theme`, () => {
    test.use({ colorScheme })

    for (const screen of SCREENS) {
      test(`A11Y8B: ${screen.name} has no serious or critical violations`, async ({ page }) => {
        await signIn(page, screen.as)
        await screen.open(page)
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

  test('MO8B-01: the Phase 8b screens fit without sideways scrolling; dialogs keep their actions in reach', async ({
    page,
  }) => {
    test.setTimeout(180_000)
    const overflow = () =>
      page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      )
    for (const screen of SCREENS) {
      await signIn(page, screen.as)
      if (screen.overlay) {
        // Phones reach the researcher line through the Details sheet's twin on the page.
        await screen.open(page)
        const dialog = page.getByRole('dialog').last()
        await expect(
          dialog.getByRole('button', { name: /^(Save|Start research)/ }).last(),
        ).toBeInViewport()
      } else {
        await screen.open(page)
      }
      await settled(page)
      expect(await overflow(), screen.name).toBeLessThanOrEqual(0)
    }
  })

  test('MO8B-02: the guest’s Details sheet holds no evaluation or score', async ({ page }) => {
    await signIn(page, 'bob')
    await page.goto('/ideas/TOOLS-12')
    await page.getByRole('button', { name: /Details/ }).click()
    const sheet = page.getByRole('dialog', { name: 'Details' })
    await expect(sheet.getByRole('term').filter({ hasText: /^Research$/ })).toBeVisible()
    await expect(sheet.getByText('Evaluators')).toHaveCount(0)
    await expect(sheet.getByText('Score', { exact: true })).toHaveCount(0)
  })
})

test('K8B-01: the assign dialog with the keyboard only; Escape puts focus back on its opener', async ({
  page,
}) => {
  await signIn(page, 'dave')
  await page.goto('/ideas/TOOLS-12')
  const change = researcherLine(page).getByRole('button', {
    name: 'Change researcher or due date',
  })
  await change.focus()
  await page.keyboard.press('Enter')
  const dialog = page.getByRole('dialog', { name: 'Who does the research' })
  const search = dialog.getByRole('combobox', { name: 'Researcher' })
  await expect(search).toBeFocused()
  await page.keyboard.type('kenji')
  const kenji = dialog.getByRole('option', { name: /Kenji Watanabe/ })
  await expect(kenji).toHaveAttribute('aria-selected', 'true')
  await page.keyboard.press('Enter')
  await expect(dialog).toContainText('Chosen: Kenji Watanabe')
  // A member: no guest line, only who would lose the idea (UX review S2).
  await expect(dialog.getByRole('status')).toHaveText('Bob Brown will no longer see TOOLS-12.')
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
  await expect(change).toBeFocused()
  // Nothing was saved.
  await expect(researcherLine(page)).toContainText('Bob Brown')
})
