import { isNotFound, useAdminGroupName, useAdminUserName, useIdeaKey } from '@/api/admin'
import { useAiAgents } from '@/api/ai-agents'
import type { AuditEntry } from '@/api/types'

import { describeAuditEntry, type AuditPart } from './audit-phrases'

/**
 * One audit entry as a sentence. Names the API resolved are emphasised; ids
 * from `details` (a group member, a new owner, synced groups) are looked up as
 * the row comes into view (cached), reading "a deleted user" when gone.
 */
export function AuditSentence({ entry, id }: { entry: AuditEntry; id?: string }) {
  const parts = describeAuditEntry(entry)
  return (
    <p id={id} className="text-sm text-secondary">
      {parts.map((part, index) => (
        <Part key={index} part={part} />
      ))}
    </p>
  )
}

function Part({ part }: { part: AuditPart }) {
  switch (part.type) {
    case 'text':
      return part.text
    case 'name':
      return <span className="font-medium text-primary">{part.text}</span>
    case 'code':
      // Read character by character (l and I differ): monospace, not bold.
      return <code className="font-mono text-xs text-primary">{part.text}</code>
    case 'user':
      return <UserName id={part.id} />
    case 'group':
      return <GroupName id={part.id} />
    case 'idea':
      return <IdeaKey id={part.id} fallback={part.fallback} />
    case 'agent':
      return <AgentName id={part.id} />
  }
}

/** "AI agent Idea evaluator" from the registered agents (platform admins); else "an AI agent". */
function AgentName({ id }: { id: string }) {
  const query = useAiAgents()
  const agent = query.data?.items.find((item) => item.id === id)
  if (!agent) return 'an AI agent'
  return (
    <>
      AI agent <span className="font-medium text-primary">{agent.display_name}</span>
    </>
  )
}

function Resolved({
  name,
  pending,
  gone,
  kind,
}: {
  name: string | undefined
  pending: boolean
  gone: boolean
  kind: 'user' | 'group'
}) {
  if (name) return <span className="font-medium text-primary">{name}</span>
  if (pending) {
    return (
      <>
        <span
          aria-hidden="true"
          className="inline-block h-3 w-20 animate-pulse rounded-md bg-subtle-hover align-middle"
        />
        <span className="sr-only">a {kind}</span>
      </>
    )
  }
  return <span className="italic">{gone ? `a deleted ${kind}` : `a ${kind}`}</span>
}

function UserName({ id }: { id: string }) {
  const query = useAdminUserName(id)
  return (
    <Resolved
      name={query.data}
      pending={query.isPending}
      gone={query.isError && isNotFound(query.error)}
      kind="user"
    />
  )
}

function GroupName({ id }: { id: string }) {
  const query = useAdminGroupName(id)
  return (
    <Resolved
      name={query.data}
      pending={query.isPending}
      gone={query.isError && isNotFound(query.error)}
      kind="group"
    />
  )
}

function IdeaKey({ id, fallback }: { id: string; fallback: string }) {
  const query = useIdeaKey(id)
  return query.data ? <span className="font-medium text-primary">{query.data}</span> : fallback
}
