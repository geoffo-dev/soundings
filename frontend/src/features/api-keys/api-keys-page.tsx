import { CloudOff, KeyRound, Plus } from 'lucide-react'
import { useMemo, useState } from 'react'

import { useCreateApiKey, useMyApiKeys, useRevokeApiKey } from '@/api/api-keys'
import type { ApiKey, ApiKeyList } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Callout } from '@/components/ui/callout'
import { EmptyState } from '@/components/ui/empty-state'
import { Skeleton, SkeletonGroup } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { toast } from '@/components/ui/toaster'
import { WithTooltip } from '@/components/ui/tooltip'
import { AdminPageHeader, SettingsFrame } from '@/features/admin/settings-frame'
import { formatDateTime, formatShortDate } from '@/lib/dates'
import { focusWhenRendered } from '@/lib/focus'
import { ROW_ID_ATTRIBUTE } from '@/lib/return-to-row'
import { cn } from '@/lib/utils'

import { ConnectMcpSection } from './connect-mcp'
import { CreateKeyDialog } from './create-key-dialog'
import { KeyAccess, KeyExpiry, KeyLastUsed, KeyProjects, KeyStateBadge } from './key-parts'
import { RevokeKeyDialog } from './revoke-key-dialog'
import { SecretDialog } from './secret-dialog'

const CREATE_BUTTON_ID = 'create-api-key'

/**
 * Settings → API keys (contract-phase5 §3.10): your keys (name, prefix,
 * scopes, projects, expiry, last use), "Create key" with the one-time secret,
 * revoke (confirmed: no undo), and how to connect an MCP client. Session only:
 * a key can't manage keys.
 */
export function ApiKeysPage() {
  const query = useMyApiKeys()
  const create = useCreateApiKey()
  const [creating, setCreating] = useState(false)
  const list = query.data
  const empty = list?.items.length === 0
  // c20: the break-glass account can't have keys (the only other reason is the limit).
  const breakGlass = Boolean(list && !list.can_create && list.items.length < list.max_keys)

  const createButton = (
    <Button
      id={CREATE_BUTTON_ID}
      variant="primary"
      disabled={!list?.can_create}
      aria-describedby={list && !list.can_create ? 'api-keys-limit' : undefined}
      onClick={() => setCreating(true)}
    >
      <Plus />
      Create key
    </Button>
  )

  return (
    <SettingsFrame>
      <AdminPageHeader
        title="API keys"
        description="Let a script or an AI assistant work in Soundings as you. A key does only what you allow when you create it, never more than you can, until it expires or you revoke it."
        actions={list && !empty ? createButton : undefined}
      />
      {list && !list.can_create && !(breakGlass && empty) && (
        <Callout id="api-keys-limit" role="status" title={limitReason(list)} />
      )}
      {list ? (
        empty ? (
          breakGlass ? (
            <EmptyState
              size="compact"
              className="rounded-lg border"
              icon={<KeyRound />}
              title="No API keys for the break-glass account"
              description="A key would outlive the emergency. Sign in with your own account to create keys."
            />
          ) : (
            <EmptyState
              size="compact"
              className="rounded-lg border"
              icon={<KeyRound />}
              title="No API keys yet"
              description="Create one to let a script or an AI assistant work in Soundings as you."
              action={createButton}
            />
          )
        ) : (
          <KeysTable keys={list.items} />
        )
      ) : query.isError ? (
        <EmptyState
          role="alert"
          size="compact"
          className="rounded-lg border"
          icon={<CloudOff />}
          title="Couldn’t load your API keys"
          description="Check your connection and try again."
          action={
            <Button variant="secondary" onClick={() => void query.refetch()}>
              Try again
            </Button>
          }
        />
      ) : (
        <SkeletonGroup label="Loading your API keys" className="overflow-hidden rounded-lg border">
          {[0, 1, 2].map((i) => (
            <div
              key={i}
              className="flex h-15 items-center gap-4 border-b border-subtle px-4 last:border-0"
            >
              <div className="flex flex-1 flex-col gap-1.5">
                <Skeleton className="h-3.5 w-36" />
                <Skeleton className="h-3 w-48" />
              </div>
              <Skeleton className="hidden h-5 w-28 sm:block" />
              <Skeleton className="hidden h-3 w-20 sm:block" />
            </div>
          ))}
        </SkeletonGroup>
      )}
      <p className="text-sm text-muted">
        Keys pause when you haven’t signed in to Soundings for 30 days; signing in reactivates them.
        Signing out doesn’t stop them: revoke a key to stop it.
      </p>
      <ConnectMcpSection />
      <CreateKeyDialog open={creating} onOpenChange={setCreating} create={create} />
      <SecretDialog
        created={create.data}
        onDone={() => {
          // The secret leaves the mutation cache with the dialog (contract-phase5 §3.1).
          create.reset()
        }}
      />
    </SettingsFrame>
  )
}

/** Why "Create key" is off: the 25-key limit, or (c20) the break-glass account. */
function limitReason(list: ApiKeyList): string {
  if (list.items.length >= list.max_keys) {
    return `You have ${String(list.max_keys)} keys. Revoke one you no longer use to create another.`
  }
  return 'The break-glass account can’t create API keys. Sign in with your own account to create one.'
}

function KeysTable({ keys: listed }: { keys: ApiKey[] }) {
  const revoke = useRevokeApiKey()
  const [revoking, setRevoking] = useState<ApiKey | null>(null)
  // Expired keys last: they no longer work, so the ones that do come first.
  const keys = useMemo(
    () => [...listed].sort((a, b) => Number(a.state === 'expired') - Number(b.state === 'expired')),
    [listed],
  )

  const confirm = () => {
    if (!revoking) return
    const index = keys.findIndex((key) => key.id === revoking.id)
    const next = keys[index + 1] ?? keys[index - 1]
    const { name, state } = revoking
    revoke.mutate(revoking.id, {
      onSuccess: () => {
        setRevoking(null)
        if (state === 'expired') toast.success(`“${name}” removed`)
        else toast.success(`“${name}” revoked`, { description: 'It stopped working immediately.' })
        // The row is gone: focus its neighbour, or "Create key" when it was the last.
        focusWhenRendered(
          () =>
            (next &&
              document.querySelector<HTMLElement>(
                `[${ROW_ID_ATTRIBUTE}="${CSS.escape(next.id)}"]`,
              )) ??
            document.getElementById(CREATE_BUTTON_ID),
          { force: true },
        )
      },
      onError: () => setRevoking(null),
    })
  }

  return (
    <div className="overflow-hidden rounded-lg border">
      <Table mobile="container-cards" aria-label="Your API keys" className="@3xl:table-fixed">
        <TableHeader>
          <TableRow>
            <TableHead>Key</TableHead>
            <TableHead className="w-48">Can</TableHead>
            <TableHead className="w-40">Projects</TableHead>
            <TableHead className="w-28">Expires</TableHead>
            <TableHead className="w-28">Last used</TableHead>
            <TableHead className="w-20">
              <span className="sr-only">Actions</span>
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {keys.map((key) => {
            const expired = key.state === 'expired'
            return (
              <TableRow key={key.id} className="@3xl:h-15">
                <TableCell primary className="min-w-0">
                  <div
                    tabIndex={-1}
                    {...{ [ROW_ID_ATTRIBUTE]: key.id }}
                    className="flex min-w-0 flex-col gap-0.5 rounded-sm outline-offset-2"
                  >
                    <span className="flex min-w-0 items-center gap-2">
                      <span
                        className={cn(
                          'truncate font-medium',
                          expired ? 'text-secondary' : 'text-primary',
                        )}
                      >
                        {key.name}
                      </span>
                      {key.state === 'dormant' && <KeyStateBadge state="dormant" />}
                    </span>
                    <span className="truncate text-xs text-muted">
                      <code className="font-mono">{key.prefix}…</code> · created{' '}
                      <WithTooltip content={formatDateTime(key.created_at)}>
                        <time dateTime={key.created_at}>{formatShortDate(key.created_at)}</time>
                      </WithTooltip>
                    </span>
                  </div>
                </TableCell>
                <TableCell label="Can">
                  <KeyAccess scopes={key.scopes} muted={expired} />
                </TableCell>
                <TableCell label="Projects" className="min-w-0">
                  <KeyProjects apiKey={key} />
                </TableCell>
                <TableCell label="Expires">
                  <KeyExpiry apiKey={key} />
                </TableCell>
                <TableCell label="Last used">
                  <KeyLastUsed at={key.last_used_at} />
                </TableCell>
                <TableCell className="@max-3xl:basis-full @max-3xl:items-start @3xl:text-right">
                  <Button
                    variant="ghost"
                    size="sm"
                    className="@max-3xl:-ml-2.5"
                    aria-label={`${expired ? 'Remove' : 'Revoke'} ${key.name}`}
                    onClick={() => setRevoking(key)}
                  >
                    {expired ? 'Remove' : 'Revoke'}
                  </Button>
                </TableCell>
              </TableRow>
            )
          })}
        </TableBody>
      </Table>
      <RevokeKeyDialog
        apiKey={revoking}
        pending={revoke.isPending}
        onCancel={() => setRevoking(null)}
        onConfirm={confirm}
      />
    </div>
  )
}
