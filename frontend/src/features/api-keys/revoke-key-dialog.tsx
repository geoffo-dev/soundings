import { ConfirmDialog } from '@/features/admin/confirm-dialog'

/**
 * "Revoke …?" (contract-phase5 §3.10): asks first because the key stops working
 * at once and can't come back (no Undo: whoever holds it would need a new key).
 * An expired key already stopped: "Remove …?" only takes it off the list (and
 * frees its place under the 25-key limit).
 */
export function RevokeKeyDialog({
  apiKey,
  ownerName,
  ownerIsAgent = false,
  pending,
  onCancel,
  onConfirm,
}: {
  apiKey: { name: string; prefix: string; state: string } | null
  /** Someone else's key (Admin settings → API keys). */
  ownerName?: string
  /** That someone is an AI agent (a service account): only an admin can make it a new key. */
  ownerIsAgent?: boolean
  pending: boolean
  onCancel: () => void
  onConfirm: () => void
}) {
  const expired = apiKey?.state === 'expired'
  const verb = expired ? 'Remove' : 'Revoke'
  const whose = ownerName ? `${ownerName}’s key “${apiKey?.name ?? ''}”` : `“${apiKey?.name ?? ''}”`
  const recover = ownerIsAgent
    ? 'an admin would need to create a new key for this agent.'
    : ownerName
      ? 'they would need to create a new key.'
      : 'to connect again, create a new key.'
  return (
    <ConfirmDialog
      open={apiKey !== null}
      onOpenChange={(open) => {
        if (!open) onCancel()
      }}
      title={apiKey ? `${verb} ${whose}?` : ''}
      description={
        expired
          ? 'It already stopped working when it expired. Removing it takes it off the list for good.'
          : `Anything using it stops working immediately. There is no undo: ${recover}`
      }
      confirmLabel={`${verb} key`}
      tone="danger"
      pending={pending}
      onConfirm={onConfirm}
    >
      {apiKey && (
        <p>
          Key <code className="font-mono text-primary">{apiKey.prefix}…</code>
        </p>
      )}
    </ConfirmDialog>
  )
}
