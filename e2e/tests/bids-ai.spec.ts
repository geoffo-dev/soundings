import type { Locator, Page } from '@playwright/test'

import { FakeAgent } from '../scripts/fake-agent'
import {
  agentName,
  newPerson,
  registerAgent,
  retireAgents,
  signInAs,
  skipWithoutAi,
  waitRun,
  type RegisteredAgent,
} from './support/ai'
import {
  assessingCall,
  bid,
  comparison,
  MUST_HAVES,
  waitExtracted,
  type BidAiAssessmentList,
} from './support/bids'
import { expect, test, toast } from './support/fixtures'

/**
 * Phase 10's AI assessor (contract-phase10 §9, test plan BD-13), against Soundings' fake
 * kagent agent (E2E_AI=1; tagged @ai, skipped without it). The project, its call and the
 * agents are the spec's own; the idea's owner is a new person (each person may ask for 20
 * runs an hour, contract-phase6 §3.3), so the owner asks.
 */

test.describe.configure({ mode: 'serial' })

const bidsRegion = (page: Page) => page.getByRole('region', { name: 'Bids', exact: true })

async function openBid(page: Page, key: string, bidder: string): Promise<Locator> {
  await page.goto(`/ideas/${key}?tab=bids`)
  await bidsRegion(page).getByRole('button', { name: bidder, exact: true }).click({
    timeout: 15_000,
  })
  const sheet = page.getByRole('dialog', { name: bidder })
  await expect(sheet.getByRole('heading', { name: 'Documents' })).toBeVisible()
  return sheet
}

test('BD-13 @ai “Ask AI to assess” scores every question with quotes checked against the documents, left out of the totals until counted', async ({
  page,
  api,
}) => {
  await skipWithoutAi()
  const alice = await api('alice')
  const agents: RegisteredAgent[] = []
  try {
    const arranged = await assessingCall(
      alice,
      'Bid AI',
      { carol: 'member', priya: 'member' },
      { Technical: ['carol'], Commercial: ['priya'] },
    )
    const { key, call, northwind, project } = arranged
    const owner = await newPerson(alice, 'Olivia')
    await alice.addMemberUser(project.slug, owner.me)
    await alice.setOwnerUser(key, owner.me)
    const assessor = await registerAgent(alice, {
      projectIds: [project.id],
      purposes: ['assess_bid'],
      name: agentName(),
      displayName: 'Bid assessor',
    })
    agents.push(assessor)
    const inventor = await registerAgent(alice, {
      projectIds: [project.id],
      purposes: ['assess_bid'],
      name: agentName('invents'),
      displayName: 'Bid assessor (invents)',
    })
    agents.push(inventor)
    await waitExtracted(alice, key, northwind.id)
    const before = (await comparison(alice, key)).rows.find((r) => r.bid.id === northwind.id)

    await signInAs(page, owner.me)
    const sheet = await openBid(page, key, 'Northwind Data Ltd')
    const panel = sheet.getByRole('region', { name: /AI assessment/ })
    await panel.getByRole('button', { name: 'Ask AI to assess' }).click()
    await page.getByRole('menuitem', { name: 'Bid assessor', exact: true }).click()
    await expect(toast(page, 'Bid assessor is assessing Northwind Data Ltd’s bid')).toBeVisible()
    const runs = await owner.get<{ items: { id: string; kind: string; bid_id: string | null }[] }>(
      `/ideas/${key}/ai-runs`,
    )
    const runId = runs.items.find((r) => r.kind === 'assess_bid' && r.bid_id === northwind.id)?.id
    expect(runId).toBeTruthy()
    const done = await waitRun(owner, key, runId ?? '')
    expect(done.status).toBe('succeeded')

    // Its assessment: a score per question, each quote found in the documents, not counted.
    const card = sheet.getByRole('article', { name: 'Bid assessor’s assessment' })
    await expect(card).toBeVisible({ timeout: 15_000 })
    await expect(card.getByText('Found in the document').first()).toBeVisible()
    await expect(card.getByText('Not found in the document')).toHaveCount(0)
    const include = card.getByRole('switch', { name: 'Count in the totals' })
    await expect(include).not.toBeChecked()
    // Must-have findings are suggestions beside the result, never the result.
    const detail = await bid(alice, key, northwind.id)
    expect(detail.status).toBe('qualified')
    const insurance = detail.must_have_results.find(
      (r) => r.must_have.text === MUST_HAVES.insurance,
    )
    expect(insurance?.result).toBe('met')
    expect(insurance?.ai_findings.length).toBe(1)

    // Never the pricing document (the fake lists what it was given).
    const seen = await new FakeAgent().observations(runId ?? '')
    const pricing = detail.documents.find((d) => d.pricing)
    expect(pricing).toBeTruthy()
    expect(seen?.assess?.documents_listed).not.toContain(pricing?.id)
    expect(seen?.assess?.documents_read.length).toBeGreaterThan(0)
    expect(seen?.message_checks).toEqual({ has_url: false, has_api_key: false })

    // Left out of the total until the owner counts it, then in.
    const unchanged = (await comparison(alice, key)).rows.find((r) => r.bid.id === northwind.id)
    expect(unchanged?.total).toBe(before?.total ?? null)
    expect(unchanged?.ai_included).toBe(false)
    await include.click()
    await expect(toast(page, 'The AI’s scores now count')).toBeVisible()
    await expect(include).toBeChecked()
    const counted = (await comparison(alice, key)).rows.find((r) => r.bid.id === northwind.id)
    expect(counted?.ai_included).toBe(true)
    await include.click()
    await expect(toast(page, 'The AI’s scores are left out')).toBeVisible()

    // An invented quote is marked.
    await panel.getByRole('button', { name: 'Ask AI to assess' }).click()
    await page.getByRole('menuitem', { name: 'Bid assessor (invents)' }).click()
    await expect(toast(page, /Bid assessor \(invents\) is assessing/)).toBeVisible()
    await expect
      .poll(
        async () =>
          (
            await owner.get<BidAiAssessmentList>(
              `/ideas/${key}/bid-call/bids/${northwind.id}/ai-assessments`,
            )
          ).items.length,
        { timeout: 60_000 },
      )
      .toBe(2)
    const invented = sheet.getByRole('article', { name: 'Bid assessor (invents)’s assessment' })
    await expect(invented.getByText('Not found in the document').first()).toBeVisible({
      timeout: 15_000,
    })
    // An assessor never sees the AI's scores in the bid sheet before submitting.
    const carol = await api('carol')
    expect(
      (
        await carol.raw('GET', `/ideas/${key}/bid-call/bids/${northwind.id}/ai-assessments`)
      ).status(),
    ).toBe(403)
    void call
  } finally {
    await retireAgents(alice, agents)
  }
})
