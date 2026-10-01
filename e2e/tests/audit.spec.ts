import type { Page } from '@playwright/test'

import { createTeamProject, defaultRubricScores, uniqueSuffix, userOf } from './support/api'
import { expect, settled, signIn, test } from './support/fixtures'
import { requireSso, ssoSignIn, ssoSignInAs } from './support/sso'

/**
 * Admin settings → Audit log (contract-phase2 §3.11) against the real stack: SPEC's list
 * (sign-ins, assignments, evaluations, status changes, admin changes) appears as plain
 * sentences with names resolved, each entry carries the acting session's method, and only
 * platform admins can read it. Test plan: AD-*.
 */

const entries = (page: Page) => page.getByRole('region', { name: 'Audit entries' })

async function openAudit(page: Page, query = '') {
  await page.goto(`/settings/audit${query}`)
  await expect(page.getByRole('heading', { level: 2, name: 'Audit log' })).toBeVisible()
  await settled(page)
}

test('AD-01: sign-ins appear, with the method', async ({ page, api }) => {
  await api('bob') // a dev-login sign-in
  const bob = await userOf((await api('alice')).baseURL, 'bob')
  await signIn(page, 'alice')
  await openAudit(page, `?actor=${bob.id}`)
  await expect(page.getByRole('button', { name: /^Who\s+Bob Brown/ })).toBeVisible()
  await expect(
    entries(page).getByText('Bob Brown signed in with the development login').first(),
  ).toBeVisible()
})

test('AD-02: admin changes appear as sentences, with names resolved', async ({ page, api }) => {
  const alice = await api('alice')
  const run = uniqueSuffix()
  const group = await alice.createGroup({ name: `Audit ${run}`, idp_values: [`/e2e/${run}`] })
  await alice.send('PATCH', `/admin/groups/${group.id}`, { name: `Audited ${run}` })
  const kenji = await userOf(alice.baseURL, 'kenji')
  await alice.addGroupMember(group.id, kenji.id)
  await alice.replaceMapping(group.id, 'additive', [`/e2e/${run}`])
  const project = await createTeamProject(alice, 'Audit grants', {})
  await alice.grantGroup(project.slug, group.id, 'viewer')

  await signIn(page, 'alice')
  await openAudit(page, `?target=group:${group.id}`)
  await expect(page.getByText(`About · Audited ${run}`)).toBeVisible()
  const list = entries(page)
  await expect(
    list.getByText(`Alice Anders created group Audited ${run}, mapped to e2e/${run}`),
  ).toBeVisible()
  await expect(list.getByText(`Alice Anders renamed group Audited ${run}`)).toBeVisible()
  // The member's id in `details` is resolved to a name as the row comes into view.
  await expect(
    list.getByText(`Alice Anders added Kenji Watanabe to group Audited ${run}`),
  ).toBeVisible()
  await expect(
    list.getByText(`Alice Anders changed the mapping of group Audited ${run}: now additive`),
  ).toBeVisible()
  await expect(
    list.getByText(`Alice Anders gave group Audited ${run} the viewer role in ${project.name}`),
  ).toBeVisible()

  // Raw fields on demand, including the session's method.
  const details = list.getByRole('button', { name: 'Details' }).first()
  await details.click()
  await expect(details).toHaveAttribute('aria-expanded', 'true')
  await expect(list.locator('dl').first()).toContainText('dev_login')

  const raw = await alice.audit({ target_type: 'group', target_id: group.id })
  expect(raw.map((entry) => entry.action).sort()).toEqual([
    'group.create',
    'group.mapping_replace',
    'group.member_add',
    'group.update',
    'project.group_grant_add',
  ])
  for (const entry of raw) expect(entry.details.auth_method).toBe('dev_login')
})

test('AD-03: assignments, evaluations and status changes appear for a project', async ({
  page,
  api,
}) => {
  const alice = await api('alice')
  const project = await createTeamProject(alice, 'Audit trail', { bob: 'member', carol: 'member' })
  const idea = await alice.createIdea(project.slug, {
    title: 'Self-service returns',
    summary: 'Print a label at home.',
  })
  await alice.setOwner(idea.key, 'bob')
  await alice.changeStatus(idea.key, 'evaluating')
  await alice.invite(idea.key, ['carol'])
  await (
    await api('carol')
  ).evaluate(idea.key, defaultRubricScores(4, 3, 2, 4, 2), {
    recommendation: 'go',
  })

  await signIn(page, 'alice')
  await openAudit(page, `?project=${project.id}`)
  const list = entries(page)
  await expect(list.getByText(`Alice Anders made Bob Brown the owner of ${idea.key}`)).toBeVisible()
  await expect(
    list.getByText(new RegExp(`^Alice Anders moved ${idea.key} from \\S+ to Evaluating$`)),
  ).toBeVisible()
  await expect(
    list.getByText(`Alice Anders asked Carol Chen to evaluate ${idea.key}`),
  ).toBeVisible()
  await expect(list.getByText(`Carol Chen submitted an evaluation of ${idea.key}`)).toBeVisible()
  // Emails, scores and comments never reach the log.
  const raw = JSON.stringify(await alice.audit({ project_id: project.id }))
  expect(raw).not.toContain('@example.com')
})

test('AD-04: only platform admins can read the audit log', async ({ page, api }) => {
  const bob = await api('bob')
  expect((await bob.raw('GET', '/admin/audit')).status()).toBe(403)
  await signIn(page, 'bob')
  await page.goto('/settings/audit')
  await expect(page.getByRole('heading', { name: 'We couldn’t find that page' })).toBeVisible()
})

test.describe('with SSO', { tag: '@sso' }, () => {
  test('AD-05: SSO sign-ins and denied sign-ins appear', async ({ page, browser }) => {
    await requireSso()
    const context = await browser.newContext()
    const sso = await context.newPage()
    await ssoSignInAs(sso, 'dave')
    await context.clearCookies()
    await ssoSignIn(sso, 'mallory') // unverified email: refused
    await expect(sso).toHaveURL(/error=no_account/)
    await context.close()

    await signIn(page, 'alice')
    const dave = await userOf(test.info().project.use.baseURL ?? '', 'dave')
    await openAudit(page, `?target=user:${dave.id}`)
    await expect(
      entries(page)
        .getByText(/^Dave Davies signed in with SSO/)
        .first(),
    ).toBeVisible()

    await openAudit(page, '?action=denied')
    await expect(
      entries(page).getByText('An SSO sign-in was denied: the email isn’t verified').first(),
    ).toBeVisible()
    await expect(entries(page).getByText(/signed in with SSO/)).toHaveCount(0)
  })
})
