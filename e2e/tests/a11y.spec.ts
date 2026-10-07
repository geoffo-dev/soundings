import type { Page } from '@playwright/test'

import type { Person } from './support/api'
import { expect, heading, seriousViolations, settled, signIn, test } from './support/fixtures'

/**
 * axe (WCAG 2.2 AA rules) on every Phase 1 screen and overlay, in the light and the
 * dark theme, against the real app and the seeded data. The bar: no serious or
 * critical violations. Read-only: nothing here saves anything. Test plan: A11Y-*.
 */

interface Screen {
  name: string
  as: Person | null
  open: (page: Page) => Promise<void>
}

const openedDialog = (page: Page, name: string | RegExp) =>
  expect(page.getByRole('dialog', { name })).toBeVisible()

const SCREENS: Screen[] = [
  {
    name: 'login',
    as: null,
    open: async (page) => {
      await page.goto('/login')
      await expect(page.getByRole('button', { name: /Alice Anders/ })).toBeVisible()
    },
  },
  {
    name: 'my work',
    as: 'alice',
    open: async (page) => {
      await page.goto('/')
      await expect(page.locator('#evaluations').getByRole('listitem').first()).toBeVisible()
    },
  },
  {
    name: 'project board',
    as: 'alice',
    open: async (page) => {
      await page.goto('/p/customer-innovation?view=board')
      await expect(page.getByRole('link', { name: /\(CUST-11\)$/ })).toBeVisible()
    },
  },
  {
    name: 'project list with a filter',
    as: 'alice',
    open: async (page) => {
      await page.goto('/p/customer-innovation?view=list&status=evaluating&sort=-score')
      await expect(
        page.getByRole('table', { name: 'Ideas' }).getByRole('link').first(),
      ).toBeVisible()
    },
  },
  {
    name: 'idea page (owner, with the aggregate)',
    as: 'alice',
    open: async (page) => {
      await page.goto('/ideas/CUST-12')
      await expect(
        page.getByRole('complementary', { name: 'Idea details' }).getByRole('meter').first(),
      ).toBeVisible()
    },
  },
  {
    name: 'idea page (pending evaluator)',
    as: 'alice',
    open: async (page) => {
      await page.goto('/ideas/CUST-11')
      await expect(page.getByText('Hidden until you submit')).toBeVisible()
    },
  },
  {
    name: 'evaluations tab',
    as: 'alice',
    open: async (page) => {
      await page.goto('/ideas/CUST-8?tab=evaluations')
      await expect(page.getByRole('tabpanel').getByRole('article').first()).toBeVisible()
    },
  },
  {
    name: 'evaluate sheet',
    as: 'alice',
    open: async (page) => {
      await page.goto('/ideas/CUST-11?evaluate=1')
      await openedDialog(page, 'Evaluate')
      await expect(page.getByRole('radiogroup', { name: 'Value', exact: true })).toBeVisible()
    },
  },
  {
    name: 'evaluate sheet, revealed',
    as: 'alice',
    open: async (page) => {
      await page.goto('/ideas/TOOLS-6?evaluate=1')
      await openedDialog(page, 'Your evaluation')
      await expect(page.getByRole('region', { name: 'Everyone’s scores' })).toBeVisible()
    },
  },
  {
    name: 'new idea dialog',
    as: 'alice',
    open: async (page) => {
      await page.goto('/p/customer-innovation')
      await expect(heading(page, 'Customer Innovation')).toBeVisible()
      await page.keyboard.press('n')
      await openedDialog(page, 'New idea')
    },
  },
  {
    name: 'command palette',
    as: 'alice',
    open: async (page) => {
      await page.goto('/')
      await expect(heading(page, 'My work')).toBeVisible()
      await page.keyboard.press('ControlOrMeta+k')
      await openedDialog(page, 'Command palette')
      await page.keyboard.type('checkout')
      await expect(page.getByRole('option', { name: /Accessibility audit/ })).toBeVisible()
    },
  },
  {
    name: 'shortcut sheet',
    as: 'alice',
    open: async (page) => {
      await page.goto('/ideas/CUST-12')
      await expect(heading(page, 'Accessibility audit of the checkout')).toBeVisible()
      await page.keyboard.press('?')
      await openedDialog(page, 'Keyboard shortcuts')
    },
  },
  ...(['general', 'members', 'rubric', 'public-form'] as const).map((tab): Screen => ({
    name: `project settings: ${tab}`,
    as: 'alice',
    open: async (page) => {
      await page.goto(`/p/customer-innovation/settings?tab=${tab}`)
      await expect(heading(page, 'Project settings')).toBeVisible()
      await settled(page)
    },
  })),
  {
    name: 'create project dialog',
    as: 'alice',
    open: async (page) => {
      await page.goto('/')
      await page
        .getByRole('navigation', { name: 'Main' })
        .getByRole('button', { name: 'New project' })
        .click()
      await openedDialog(page, 'New project')
    },
  },
  {
    name: 'not found',
    as: 'alice',
    open: async (page) => {
      await page.goto('/ideas/CUST-999')
      await expect(page.getByText('This idea doesn’t exist or you don’t have access')).toBeVisible()
    },
  },
]

for (const colorScheme of ['light', 'dark'] as const) {
  test.describe(`${colorScheme} theme`, () => {
    test.use({ colorScheme })

    for (const screen of SCREENS) {
      test(`A11Y: ${screen.name} has no serious or critical violations`, async ({ page }) => {
        if (screen.as) await signIn(page, screen.as)
        await screen.open(page)
        await expect(page.locator('html')).toHaveClass(
          colorScheme === 'dark' ? /\bdark\b/ : /^(?!.*\bdark\b)/,
        )
        await settled(page)
        // Let enter animations finish so axe sees final colours.
        await page.waitForTimeout(300)
        expect(await seriousViolations(page)).toEqual([])
      })
    }
  })
}
