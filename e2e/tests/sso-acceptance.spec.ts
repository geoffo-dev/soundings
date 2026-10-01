import type { Browser, Page } from '@playwright/test'

import {
  Api,
  authConfig,
  uniqueKey,
  uniqueSuffix,
  userOf,
  type Group,
  type Project,
  type ProjectAccessEntry,
  type ProjectRole,
} from './support/api'
import { expect, settled, signIn, test, toast } from './support/fixtures'
import {
  expectProjectAccess,
  KC,
  requireSso,
  signOutInUi,
  ssoSignInAs,
  withoutKeycloakGroup,
  type KeycloakUser,
} from './support/sso'

/**
 * Phase 2 acceptance (SPEC section 13; contract-phase2 §3.13) against the real stack and
 * a real Keycloak: *Keycloak users get the right project access from their groups;
 * removing a group removes access at next sign-in (managed mapping).* Test plan: SA-*.
 *
 * The platform admin (Alice, dev login) maps fresh groups to the dev realm's groups and
 * gives them roles in two fresh private projects whose only direct member is Priya
 * (not a Keycloak user), so every role below comes from a group:
 *
 * | Group (run-unique name) | Keycloak group        | Sync     | Role                 |
 * |-------------------------|-----------------------|----------|----------------------|
 * | Innovation admins       | /innovation/admins    | managed  | Innovation: admin    |
 * | Innovation members      | /innovation/members   | managed  | Innovation: member   |
 * | Tools members (UI)      | /tools/members        | managed  | Tools: member        |
 * | Viewers                 | /viewers              | additive | Innovation: viewer   |
 *
 * Then alice, bob, carol, dave and erin sign in through Keycloak in the browser. The
 * removal tests take one person out of a Keycloak group and always put them back.
 * Needs E2E_SSO=1 (fresh realm and seed: the local stack resets both on start).
 */

test.describe.configure({ mode: 'serial' })

interface Setup {
  run: string
  innovation: Project
  tools: Project
  groups: { admins: Group; members: Group; tools: Group; viewers: Group }
}

let setup: Setup | undefined
let admin: Api | undefined

function arranged(): Setup {
  if (!setup) throw new Error('SA-01 did not arrange the groups and projects')
  return setup
}

/** Who should have which role where, and through which group (by key of `groups`). */
const EXPECTED: Record<
  'alice' | 'bob' | 'carol' | 'dave' | 'erin',
  { innovation?: [ProjectRole, ...string[]]; tools?: [ProjectRole, ...string[]] }
> = {
  alice: { innovation: ['admin', 'admins'], tools: ['member', 'tools'] },
  bob: { innovation: ['member', 'members'] },
  carol: { innovation: ['member', 'members'], tools: ['member', 'tools'] },
  dave: { tools: ['member', 'tools'] },
  erin: { innovation: ['viewer', 'viewers'] },
}

/** A fresh browser (no Keycloak session) signed in as `user` through Keycloak. */
async function freshSignIn(browser: Browser, user: KeycloakUser): Promise<Page> {
  const context = await browser.newContext()
  const page = await context.newPage()
  await ssoSignInAs(page, user)
  return page
}

/** "Name: role via group, group" for comparing access lists. */
function describeAccess(entries: ProjectAccessEntry[]): string[] {
  return entries
    .map((entry) => {
      const sources = entry.sources.map((source) =>
        source.kind === 'direct' ? `direct ${source.role}` : `${source.group?.name} ${source.role}`,
      )
      return `${entry.user.display_name}: ${entry.role} (${sources.join(', ')})`
    })
    .sort()
}

function expectedAccess(project: 'innovation' | 'tools'): string[] {
  const { groups } = arranged()
  const rows = ['Priya Raman: admin (direct admin)']
  for (const [user, roles] of Object.entries(EXPECTED)) {
    const grant = roles[project]
    if (!grant) continue
    const [role, ...via] = grant
    const sources = via.map((key) => `${groups[key as keyof Setup['groups']].name} ${role}`)
    rows.push(`${KC[user as KeycloakUser].name}: ${role} (${sources.join(', ')})`)
  }
  return rows.sort()
}

async function latestSync(api: Api, user: KeycloakUser) {
  const target = await userOf(api.baseURL, user as 'bob')
  const [entry] = await api.audit({ action: 'user.groups_sync', target_id: target.id })
  return entry
}

test.describe('SSO acceptance', { tag: '@sso' }, () => {
  test.beforeAll(async ({ baseURL }) => {
    if (!(await authConfig(baseURL ?? '')).sso) return
    admin = await Api.as(baseURL ?? '', 'alice')
  })

  test.afterAll(async () => {
    if (!admin) return
    await admin.archiveCreated() // archives the projects, deletes the groups
    await admin.dispose()
  })

  test.beforeEach(async () => {
    await requireSso()
  })

  test('SA-01: the admin maps Keycloak groups to project roles (one through the UI)', async ({
    page,
  }) => {
    if (!admin) throw new Error('no admin client')
    const run = uniqueSuffix()
    const priya = await userOf(admin.baseURL, 'priya')
    const project = async (name: string) => {
      const key = uniqueKey('S')
      return admin!.createProject({
        name: `${name} ${run}`,
        slug: `sso-${key.toLowerCase()}`,
        key,
        visibility: 'private',
        admin: priya,
      })
    }
    const innovation = await project('SSO Innovation')
    const tools = await project('SSO Tools')

    // Through the UI: Settings → Groups → New group, mapped to Keycloak's full path.
    const toolsName = `Tools members ${run}`
    await signIn(page, 'alice')
    await page.goto('/settings/groups')
    await page.getByRole('button', { name: 'New group' }).click()
    const dialog = page.getByRole('dialog', { name: 'New group' })
    await dialog.getByRole('textbox', { name: 'Name' }).fill(toolsName)
    const values = dialog.getByRole('textbox', { name: 'Identity provider groups' })
    await values.fill('/tools/members')
    await values.press('Enter')
    await expect(dialog.getByRole('radio', { name: /Managed/ })).toBeChecked()
    await dialog.getByRole('button', { name: /^Create group/ }).click()
    await expect(toast(page, `${toolsName} created`)).toBeVisible()
    await expect(page.getByRole('heading', { level: 2, name: toolsName })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Remove tools/members' })).toBeVisible()
    const toolsGroup = await admin.groupByName(toolsName)
    admin.createdGroups.push(toolsGroup.id)

    // …and the project's Members tab: Group, Tools members, Member.
    await page.goto(`/p/${tools.slug}/settings?tab=members`)
    await settled(page)
    await page.getByRole('radio', { name: 'Group' }).click()
    await page.getByRole('combobox', { name: 'Add a group' }).click()
    await page.getByPlaceholder('Search groups by name…').fill(run)
    await page.getByRole('option', { name: new RegExp(toolsName) }).click()
    await page.getByRole('combobox', { name: 'Role', exact: true }).click()
    await page.getByRole('option', { name: 'Member' }).click()
    await page.getByRole('button', { name: 'Add', exact: true }).click()
    await expect(toast(page, `${toolsName} added as member`)).toBeVisible()

    // The other three through the API.
    const admins = await admin.createGroup({
      name: `Innovation admins ${run}`,
      idp_values: ['/innovation/admins'],
    })
    const members = await admin.createGroup({
      name: `Innovation members ${run}`,
      idp_values: ['/innovation/members'],
    })
    const viewers = await admin.createGroup({
      name: `Viewers ${run}`,
      sync_mode: 'additive',
      idp_values: ['/viewers'],
    })
    await admin.grantGroup(innovation.slug, admins.id, 'admin')
    await admin.grantGroup(innovation.slug, members.id, 'member')
    await admin.grantGroup(innovation.slug, viewers.id, 'viewer')

    setup = {
      run,
      innovation,
      tools,
      groups: { admins, members, tools: toolsGroup, viewers },
    }
    // Nobody is in the groups yet: only Priya (direct) has access.
    expect(describeAccess(await admin.projectAccess(innovation.slug))).toEqual([
      'Priya Raman: admin (direct admin)',
    ])
  })

  test('SA-02: alice, bob, carol, dave and erin sign in with Keycloak and get their access from their groups', async ({
    browser,
  }) => {
    const { innovation, tools, groups } = arranged()
    for (const user of ['alice', 'bob', 'carol', 'dave', 'erin'] as const) {
      await test.step(user, async () => {
        const page = await freshSignIn(browser, user)
        const expected = EXPECTED[user]
        if (user === 'alice') {
          // A platform admin sees every project; her role here is the group's.
          await page.goto(`/p/${innovation.slug}/settings?tab=members`)
          // Unfolded already when nobody has a direct role (it is then the only list of people).
          const showAccess = page.getByRole('button', { name: /^Everyone with access/ })
          await expect(showAccess).toBeVisible()
          if ((await showAccess.getAttribute('aria-expanded')) !== 'true') await showAccess.click()
          const access = page.getByRole('list', { name: 'Everyone with access' })
          await expect(
            access.getByRole('listitem').filter({ hasText: 'Alice Anders' }),
          ).toContainText(`via ${groups.admins.name}`)
        } else {
          await expectProjectAccess(page, innovation.slug, innovation.name, !!expected.innovation)
          await expectProjectAccess(page, tools.slug, tools.name, !!expected.tools)
        }
        if (expected.innovation?.[0] === 'viewer') {
          // A viewer can look but not submit: no "New idea" on the project page.
          await page.goto(`/p/${innovation.slug}`)
          await expect(page.getByRole('heading', { level: 1, name: innovation.name })).toBeVisible()
          await expect(
            page.getByRole('main').getByRole('button', { name: /New idea/ }),
          ).toHaveCount(0)
        }
        await page.context().close()
      })
    }

    // Everyone with access, and why: exactly the group-derived roles.
    expect(describeAccess(await admin!.projectAccess(innovation.slug))).toEqual(
      expectedAccess('innovation'),
    )
    expect(describeAccess(await admin!.projectAccess(tools.slug))).toEqual(expectedAccess('tools'))

    // Their first SSO sign-in linked the seeded accounts: alice, bob and carol by their
    // employee_no (E1001-E1003), dave and erin by their verified email.
    for (const [user, matchedBy] of [
      ['alice', 'external_id'],
      ['bob', 'external_id'],
      ['carol', 'external_id'],
      ['dave', 'email'],
      ['erin', 'email'],
    ] as const) {
      const target = await userOf(admin!.baseURL, user)
      const links = await admin!.audit({ action: 'user.identity_link', target_id: target.id })
      expect(
        links.map((entry) => entry.details.matched_by),
        user,
      ).toEqual([matchedBy])
    }
  })

  test('SA-03: the mapping test predicts what the next sign-in will do', async () => {
    const { groups, tools, innovation } = arranged()
    const dave = await userOf(admin!.baseURL, 'dave')
    const erin = await userOf(admin!.baseURL, 'erin')

    // Dave is a synced member of the managed tools group: claims without it remove him…
    const forDave = await admin!.testMapping({ groups: ['/viewers'] }, dave.id)
    const byId = (id: string) => forDave.groups.find((group) => group.group.id === id)
    expect(forDave.claim_found).toBe(true)
    expect(byId(groups.tools.id)).toMatchObject({ effect: 'remove', matched_values: [] })
    expect(byId(groups.viewers.id)).toMatchObject({ effect: 'add', matched_values: ['viewers'] })
    const roles = new Map(forDave.project_roles.map((role) => [role.project.id, role.role]))
    expect(roles.get(tools.id)).toBeUndefined()
    expect(roles.get(innovation.id)).toBe('viewer')

    // …while erin's additive membership stays even with no groups claim at all.
    const forErin = await admin!.testMapping({ sub: 'anyone' }, erin.id)
    expect(forErin.claim_found).toBe(false)
    expect(forErin.groups.find((group) => group.group.id === groups.viewers.id)).toMatchObject({
      effect: 'keep',
      matched_values: [],
    })
  })

  test('SA-04: removed from /innovation/members in Keycloak, bob loses the project at his next sign-in (managed)', async ({
    browser,
  }) => {
    const { innovation, groups } = arranged()
    const page = await freshSignIn(browser, 'bob')
    await expectProjectAccess(page, innovation.slug, innovation.name, true)

    await withoutKeycloakGroup('bob', '/innovation/members', async () => {
      // Sync runs at sign-in only: his running session keeps the access.
      await page.reload()
      await expect(page.getByRole('heading', { level: 1, name: innovation.name })).toBeVisible()

      await signOutInUi(page)
      await ssoSignInAs(page, 'bob')
      await expectProjectAccess(page, innovation.slug, innovation.name, false)

      const sync = await latestSync(admin!, 'bob')
      expect(sync?.details.removed_group_ids).toContain(groups.members.id)
      // In no Keycloak group, his token has no groups claim at all (fail closed).
      expect(sync?.details.claim_found).toBe(false)
      const members = await admin!.groupMembers(groups.members.id)
      expect(members.map((member) => member.user.display_name)).not.toContain('Bob Brown')
      expect(describeAccess(await admin!.projectAccess(innovation.slug))).not.toContainEqual(
        expect.stringMatching(/^Bob Brown/),
      )
    })

    // Back in the Keycloak group: the next sign-in gives the access back.
    await signOutInUi(page)
    await ssoSignInAs(page, 'bob')
    await expectProjectAccess(page, innovation.slug, innovation.name, true)
    await page.context().close()
  })

  test('SA-05: a manual membership survives sync when the Keycloak group goes', async ({
    browser,
  }) => {
    const { tools, groups } = arranged()
    const carol = await userOf(admin!.baseURL, 'carol')
    await admin!.addGroupMember(groups.tools.id, carol.id)

    const page = await freshSignIn(browser, 'carol')
    const membership = async () =>
      (await admin!.groupMembers(groups.tools.id)).find((member) => member.user.id === carol.id)
    expect(await membership()).toMatchObject({ manual: true, synced: true })

    await withoutKeycloakGroup('carol', '/tools/members', async () => {
      await signOutInUi(page)
      await ssoSignInAs(page, 'carol')
      // Still a member by hand, no longer synced: the project stays.
      expect(await membership()).toMatchObject({ manual: true, synced: false })
      await expectProjectAccess(page, tools.slug, tools.name, true)
      const sync = await latestSync(admin!, 'carol')
      expect(sync?.details.removed_group_ids).toContain(groups.tools.id)
    })
    await page.context().close()
  })

  test('SA-06: an additive mapping keeps the membership when the Keycloak group goes', async ({
    browser,
  }) => {
    const { innovation, groups } = arranged()
    const erin = await userOf(admin!.baseURL, 'erin')
    const page = await freshSignIn(browser, 'erin')
    await expectProjectAccess(page, innovation.slug, innovation.name, true)

    await withoutKeycloakGroup('erin', '/viewers', async () => {
      await signOutInUi(page)
      await ssoSignInAs(page, 'erin')
      await expectProjectAccess(page, innovation.slug, innovation.name, true)
      const membership = (await admin!.groupMembers(groups.viewers.id)).find(
        (member) => member.user.id === erin.id,
      )
      expect(membership).toMatchObject({ manual: false, synced: true })
    })
    await page.context().close()
  })
})
