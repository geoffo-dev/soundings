/**
 * Mailpit helper for the email end-to-end tests (Phase 3) and the shell.
 *
 * The local stack (start-stack.sh) runs Mailpit as the app's SMTP server: inbox and API
 * on http://localhost:$E2E_MAILPIT_PORT (8125), container `<E2E_PREFIX>mailpit`. Against
 * a given app (E2E_BASE_URL) set E2E_MAILPIT_URL (and E2E_MAILPIT_CONTAINER when the
 * test may stop and start it, e.g. `make demo`'s soundings-demo-mailpit).
 *
 * In a spec:
 *
 *   import { Mailpit, canControlMailpit, stopMailpit, startMailpit } from '../scripts/mailpit.ts'
 *   const mailpit = new Mailpit()
 *   const since = new Date()
 *   // ... invite bob as an evaluator ...
 *   const mail = await mailpit.waitForMessage('bob@example.com', { since, subject: /Please evaluate/ })
 *   mail.Subject, mail.HTML, mail.Text, links(mail), await mailpit.headers(mail.ID)
 *
 *   test.skip(!canControlMailpit(), 'needs a Mailpit container to stop')
 *   await stopMailpit()            // "the SMTP server is down": sends fail and are retried
 *   try { ... } finally { await startMailpit() }   // always bring it back
 *
 * The inbox is shared by every spec of the run (and emptied when the stack starts):
 * always filter by recipient and `since`, never count all messages. Messages survive a
 * stop/start. The worker retries 30 s after a failed attempt, then 1, 2, 4... minutes.
 *
 * From a shell (Node 22.18+ runs TypeScript as is; 22.12-22.17 need
 * --experimental-strip-types):
 *
 *   node e2e/scripts/mailpit.ts list [query]    # e.g. list 'to:bob@example.com'
 *   node e2e/scripts/mailpit.ts show <id>       # subject, headers, text part
 *   node e2e/scripts/mailpit.ts clear | stop | start | wait [seconds]
 */
import { execFileSync } from 'node:child_process'
import { pathToFileURL } from 'node:url'

/** Mailpit's base URL: E2E_MAILPIT_URL, else http://localhost:$E2E_MAILPIT_PORT (8125). */
export function mailpitUrl(): string {
  const url =
    process.env.E2E_MAILPIT_URL ?? `http://localhost:${process.env.E2E_MAILPIT_PORT ?? 8125}`
  return url.replace(/\/$/, '')
}

/**
 * The Docker container to stop and start: E2E_MAILPIT_CONTAINER, else the local stack's
 * `<E2E_PREFIX>mailpit` (none against an E2E_BASE_URL app without the variable).
 */
export function mailpitContainer(): string | null {
  if (process.env.E2E_MAILPIT_CONTAINER) return process.env.E2E_MAILPIT_CONTAINER
  if (process.env.E2E_BASE_URL) return null
  return `${process.env.E2E_PREFIX ?? 'p1-qa-'}mailpit`
}

export interface MailAddress {
  Name: string
  Address: string
}

/** A message in a list or search result. */
export interface MessageSummary {
  ID: string
  MessageID: string
  From: MailAddress
  To: MailAddress[]
  Cc: MailAddress[] | null
  Subject: string
  /** When Mailpit received it (ISO 8601). */
  Created: string
  Snippet: string
  Size: number
}

/** A whole message: both parts as sent. */
export interface Message {
  ID: string
  MessageID: string
  From: MailAddress
  To: MailAddress[]
  ReplyTo: MailAddress[] | null
  Subject: string
  Date: string
  HTML: string
  Text: string
}

export interface MessageFilter {
  /** Only messages Mailpit received at or after this time (default: all). */
  since?: Date
  /** Only messages whose subject contains this text or matches this pattern. */
  subject?: string | RegExp
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

export class Mailpit {
  readonly baseUrl: string

  constructor(baseUrl = mailpitUrl()) {
    this.baseUrl = baseUrl
  }

  async #get<T>(path: string): Promise<T> {
    const response = await fetch(`${this.baseUrl}${path}`)
    if (!response.ok) throw new Error(`Mailpit GET ${path}: ${response.status}`)
    return (await response.json()) as T
  }

  /** Whether Mailpit answers (false while it is stopped). */
  async isUp(): Promise<boolean> {
    try {
      return (await fetch(`${this.baseUrl}/readyz`)).ok
    } catch {
      return false
    }
  }

  async waitUntilUp(timeoutMs = 30_000): Promise<void> {
    const deadline = Date.now() + timeoutMs
    while (!(await this.isUp())) {
      if (Date.now() > deadline) throw new Error(`Mailpit at ${this.baseUrl} is not up`)
      await sleep(500)
    }
  }

  /** Messages, newest first: all (up to 500), or those matching a Mailpit search query. */
  async messages(query?: string): Promise<MessageSummary[]> {
    const path = query
      ? `/api/v1/search?limit=500&query=${encodeURIComponent(query)}`
      : '/api/v1/messages?limit=500'
    return (await this.#get<{ messages: MessageSummary[] | null }>(path)).messages ?? []
  }

  /** Messages to exactly this address (case-insensitive), newest first. */
  async messagesTo(address: string, filter: MessageFilter = {}): Promise<MessageSummary[]> {
    const wanted = address.toLowerCase()
    const since = filter.since ? Math.floor(filter.since.getTime() / 1000) * 1000 : 0
    return (await this.messages(`to:"${address}"`)).filter(
      (message) =>
        message.To.some((to) => to.Address.toLowerCase() === wanted) &&
        Date.parse(message.Created) >= since &&
        matches(message.Subject, filter.subject),
    )
  }

  /** The newest message to `address` matching the filter, waiting for it to arrive. */
  async waitForMessage(
    address: string,
    filter: MessageFilter & { timeoutMs?: number } = {},
  ): Promise<Message> {
    const deadline = Date.now() + (filter.timeoutMs ?? 30_000)
    for (;;) {
      const [newest] = await this.messagesTo(address, filter).catch(() => [])
      if (newest) return this.message(newest.ID)
      if (Date.now() > deadline) {
        throw new Error(
          `no email to ${address} matching ${String(filter.subject ?? 'any subject')}`,
        )
      }
      await sleep(1000)
    }
  }

  async message(id: string): Promise<Message> {
    return this.#get<Message>(`/api/v1/message/${encodeURIComponent(id)}`)
  }

  /** The message's headers, e.g. `(await mailpit.headers(id))['List-Unsubscribe']`. */
  async headers(id: string): Promise<Record<string, string[]>> {
    return this.#get<Record<string, string[]>>(`/api/v1/message/${encodeURIComponent(id)}/headers`)
  }

  /** The raw message source (MIME), e.g. to check the parts and encodings. */
  async raw(id: string): Promise<string> {
    const response = await fetch(`${this.baseUrl}/api/v1/message/${encodeURIComponent(id)}/raw`)
    if (!response.ok) throw new Error(`Mailpit raw ${id}: ${response.status}`)
    return response.text()
  }

  /** Deletes every message (the whole run shares the inbox: prefer filtering by `since`). */
  async deleteAll(): Promise<void> {
    const response = await fetch(`${this.baseUrl}/api/v1/messages`, { method: 'DELETE' })
    if (!response.ok) throw new Error(`Mailpit DELETE /api/v1/messages: ${response.status}`)
  }
}

function matches(subject: string, wanted: string | RegExp | undefined): boolean {
  if (wanted === undefined) return true
  return typeof wanted === 'string' ? subject.includes(wanted) : wanted.test(subject)
}

/** The href of every link in the message's HTML part, in order (entities decoded). */
export function links(message: Pick<Message, 'HTML'>): string[] {
  return [...message.HTML.matchAll(/href\s*=\s*"([^"]*)"/gi)].map((match) =>
    (match[1] ?? '').replaceAll('&amp;', '&'),
  )
}

/** Whether this run may stop and start Mailpit (a Docker container it can reach). */
export function canControlMailpit(): boolean {
  const container = mailpitContainer()
  if (!container) return false
  try {
    execFileSync('docker', ['inspect', container], { stdio: 'ignore' })
    return true
  } catch {
    return false
  }
}

function docker(action: 'stop' | 'start'): void {
  const container = mailpitContainer()
  if (!container) throw new Error('no Mailpit container to control (set E2E_MAILPIT_CONTAINER)')
  execFileSync('docker', [action, container], { stdio: 'ignore' })
}

/** "The SMTP server is down": stops the container (connections are refused). */
export async function stopMailpit(): Promise<void> {
  docker('stop')
}

/** Starts the container again and waits until it answers (messages are kept). */
export async function startMailpit(mailpit = new Mailpit()): Promise<void> {
  docker('start')
  await mailpit.waitUntilUp()
}

const USAGE = `usage: node e2e/scripts/mailpit.ts <command> [args]   (Mailpit: E2E_MAILPIT_URL)
  list [query]       newest first: id, received, to, subject (query: Mailpit search)
  show <id>          subject, headers and the text part
  clear              delete every message
  stop | start       stop / start the container (E2E_MAILPIT_CONTAINER or <E2E_PREFIX>mailpit)
  wait [seconds]     until Mailpit answers (30 s)`

async function main(argv: string[]): Promise<void> {
  const [command, ...args] = argv
  const mailpit = new Mailpit()
  switch (command) {
    case 'list':
      for (const message of await mailpit.messages(args.join(' ') || undefined)) {
        const to = message.To.map((address) => address.Address).join(', ')
        console.log(`${message.ID}  ${message.Created}  ${to}  ${message.Subject}`)
      }
      return
    case 'show': {
      if (!args[0]) throw new Error(USAGE)
      const message = await mailpit.message(args[0])
      console.log(JSON.stringify(await mailpit.headers(args[0]), null, 2))
      console.log(`\n${message.Subject}\n\n${message.Text}`)
      return
    }
    case 'clear':
      return mailpit.deleteAll()
    case 'stop':
      return stopMailpit()
    case 'start':
      return startMailpit(mailpit)
    case 'wait':
      return mailpit.waitUntilUp(Number(args[0] ?? 30) * 1000)
    default:
      throw new Error(USAGE)
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main(process.argv.slice(2)).catch((error: unknown) => {
    console.error(error instanceof Error ? error.message : error)
    process.exit(1)
  })
}
