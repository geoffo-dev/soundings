import { ConfirmDialog } from '@/features/admin/confirm-dialog'

/**
 * "Revoke …?" (contract-phase5 §3.10): asks first because the key stops working
 * at once and can't come back (no Undo: whoever holds it would need a new key).
 */
export function RevokeKeyDialog({
  apiKey,
  ownerName,
  pending,
  onCancel,
  onConfirm,
}: {
  apiKey: { name: string; prefix: string } | null
  /** Someone else's key (Admin settings → API keys). */
  ownerName?: string
  pending: boolean
  onCancel: () => void
  onConfirm: () => void
}) {
  return (
    <ConfirmDialog
      open={apiKey !== null}
      onOpenChange={(open) => {
        if (!open) onCancel()
      }}
      title={
        apiKey
          ? ownerName
            ? `Revoke ${ownerName}’s key “${apiKey.name}”?`
            : `Revoke “${apiKey.name}”?`
          : ''
      }
      description={
        ownerName
          ? 'Anything using it stops working immediately. There is no undo: they would need to create a new key.'
          : 'Anything using it stops working immediately. There is no undo: to connect again, create a new key.'
      }
      confirmLabel="Revoke key"
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
