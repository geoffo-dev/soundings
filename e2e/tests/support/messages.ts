import { expect, type Page } from '@playwright/test'

import type { components } from '../../../frontend/src/api/generated/schema'
import {
  createTeamProject,
  type Api,
  type IdeaSubmission,
  type OutboxEmail,
  type Project,
} from './api'
import { links, Mailpit, newPeople, type Someone } from './email'
import { fragmentToken, Visitor } from './public'

/**
 * Helpers for the Phase 11 specs (talking to public submitters, docs/test-plans/phase-11.md).
 *
 * A `messagingTeam` is a private project of Alice's with its public form on and two **new
 * people** (`newPeople`): Nora, who owns every idea sent through it, and Theo, a member. The
 * team's notifications ("The submitter replied") and email go to them, never to a seeded
 * person whose inbox other specs count. Ideas come in through the public API as a
 * `Visitor` (the ALTCHA solved in Node), with a run-unique address read back from Mailpit.
 */

type Schemas = components['schemas']
export type SubmissionMessage = Schemas['SubmissionMessage']
export type SubmissionMessagePage = Schemas['SubmissionMessagePage']
export type TrackedSubmission = Schemas['TrackedSubmission']

export interface MessagingTeam {
  project: Project
  owner: Someone
  member: Someone
}

export async function messagingTeam(
  alice: Api,
  name: string,
  options: { moderated?: boolean } = {},
): Promise<MessagingTeam> {
  const { nora, theo } = await newPeople(alice, ['nora', 'theo'])
  const project = await createTeamProject(alice, name, {})
  await alice.addMemberUser(project.slug, nora.user)
  await alice.addMemberUser(project.slug, theo.user)
  await alice.updatePublicForm(project.slug, {
    enabled: true,
    moderation_required: options.moderated ?? false,
    intro_md: 'Tell us how to make shopping with us better. We read every idea.',
  })
  return { project, owner: nora, member: theo }
}

export interface PublicIdea {
  key: string
  title: string
  token: string
  email: string | null
}

/**
 * A visitor sends `title` (with `email`, or none); once it reaches the team, the team's
 * owner owns it. `confirm`: the visitor clicks the confirmation email's link (through the
 * API, as the page's Confirm button does), which emails the tracking link.
 */
export async function sendPublicIdea(
  alice: Api,
  team: MessagingTeam,
  visitor: Visitor,
  fields: { title: string; email?: string | null; confirm?: boolean; since?: Date },
): Promise<PublicIdea> {
  const since = fields.since ?? new Date()
  const receipt = await visitor.submitted(team.project.slug, {
    title: fields.title,
    summary: `${fields.title}: what we'd do, as the visitor wrote it.`,
    name: 'Sam Public',
    email: fields.email ?? null,
    wants_updates: false,
  })
  const page = await alice.listIdeas(team.project.slug)
  const listed = page.items.find((item) => item.title === fields.title)
  let key = listed?.key
  if (!key) {
    const queue = await alice.moderationQueue(team.project.slug)
    key = queue.items.find((item) => item.title === fields.title)?.key
  } else {
    await alice.setOwnerUser(key, team.owner.user)
  }
  if (!key) throw new Error(`"${fields.title}" reached neither the list nor the queue`)
  if (fields.confirm && fields.email) {
    await visitor.verify(await confirmationToken(fields.email, team.project.name, since))
  }
  return { key, title: fields.title, token: receipt.tracking_token, email: fields.email ?? null }
}

/** The token of the confirmation email's link to `email` (sent at or after `since`). */
export async function confirmationToken(
  email: string,
  projectName: string,
  since: Date,
): Promise<string> {
  const message = await new Mailpit().waitForMessage(email, {
    since,
    subject: `Confirm your idea for ${projectName}`,
  })
  const link = links(message).find((href) => href.includes('/verify#'))
  if (!link) throw new Error('no confirmation link in the email')
  return fragmentToken(link)
}

export function sendTeamMessage(api: Api, key: string, body: string): Promise<SubmissionMessage> {
  return api.send<SubmissionMessage>('POST', `/ideas/${key}/submission/messages`, { body }, 201)
}

/** The conversation as the team reads it, newest first (the API's order). */
export async function teamMessages(api: Api, key: string): Promise<SubmissionMessage[]> {
  return (await api.get<SubmissionMessagePage>(`/ideas/${key}/submission/messages?limit=100`)).items
}

/** The outbox types that name an idea of the public form: the submitter's and the team's. */
const IDEA_EMAIL_TYPES = [
  'submission_received',
  'submission_link',
  'submission_message',
  'submission_status_changed',
  'submitter_replied',
] as const

/**
 * Waits until no email about `key` (to its submitter, or "The submitter replied" to the team)
 * is still queued or sending, so "no email arrived" means none was sent. Unlike
 * `outboxSettled`, other specs' held or retried email doesn't keep it waiting.
 */
export async function ideaEmailsSettled(admin: Api, key: string, timeoutMs = 30_000) {
  const query = new URLSearchParams({ limit: '100' })
  for (const type of IDEA_EMAIL_TYPES) query.append('type', type)
  await expect
    .poll(
      async () => {
        const page = await admin.get<{ items: OutboxEmail[] }>(`/admin/email/outbox?${query}`)
        return page.items.filter(
          (row) => row.idea?.key === key && (row.status === 'queued' || row.status === 'sending'),
        ).length
      },
      {
        timeout: timeoutMs,
        message: `the emails about ${key} should be sent (is the worker running?)`,
      },
    )
    .toBe(0)
}

export function submission(api: Api, key: string): Promise<IdeaSubmission> {
  return api.submission(key)
}

// --- Locators ---------------------------------------------------------------------------
/** The submission panel's Messages part (only for the owner and admins). */
export const messagesPart = (page: Page) => page.getByRole('group', { name: 'Messages' })
/** The conversation sheet ("Messages with <name>", or "… the submitter" without a name). */
export const messagesSheet = (page: Page, who?: string) =>
  page.getByRole('dialog', { name: who ? `Messages with ${who}` : 'Messages with the submitter' })
export const conversation = (scope: Page | ReturnType<Page['getByRole']>) =>
  scope.getByRole('list', { name: 'Messages, oldest first' }).getByRole('listitem')
/** The tracking page's Messages section (once the team has written). */
export const trackedMessages = (page: Page) =>
  page.getByRole('region', { name: 'Messages', exact: true })

/** Opens the idea page at its submission panel's Messages (the notification's link). */
export async function openMessages(page: Page, key: string, who?: string) {
  await page.goto(`/ideas/${key}?submission=1`)
  await expect(messagesSheet(page, who)).toBeVisible({ timeout: 15_000 })
}
