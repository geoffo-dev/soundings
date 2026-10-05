import { Check, Copy, KeyRound } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import type { CreatedApiKey } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Callout } from '@/components/ui/callout'
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { focusRow } from '@/lib/return-to-row'

import { copyText } from '@/features/admin/copy-button'
import { toast } from '@/components/ui/toaster'

import { KeyExamples } from './connect-mcp'

const SECRET_ID = 'new-key-secret'

/**
 * The new key, shown once (contract-phase5 §3.1): the full key with Copy, "Store
 * it somewhere safe: you won't see it again", and ready-to-paste examples with
 * the key filled in. The secret lives only in the create mutation's result;
 * Done calls `onDone`, which resets the mutation, so it leaves the cache. Focus
 * then goes to the new key's row. A click outside doesn't close it (losing the
 * key by accident means creating another); Esc and Done do.
 */
export function SecretDialog({
  created,
  onDone,
}: {
  created: CreatedApiKey | undefined
  onDone: () => void
}) {
  const keyId = created?.key.id
  return (
    <Dialog
      open={Boolean(created)}
      onOpenChange={(open) => {
        if (!open) onDone()
      }}
    >
      <DialogContent
        size="xl"
        mobile="fullscreen"
        onInteractOutside={(event) => event.preventDefault()}
        onOpenAutoFocus={(event) => {
          event.preventDefault()
          document.getElementById(SECRET_ID)?.querySelector('button')?.focus()
        }}
        onCloseAutoFocus={(event) => {
          if (keyId && focusRow(keyId)) event.preventDefault()
        }}
      >
        {created && (
          <>
            <DialogHeader>
              <DialogTitle className="flex items-center gap-2">
                <KeyRound aria-hidden="true" className="size-4 text-muted" />
                Copy your new key
              </DialogTitle>
              <DialogDescription>
                “{created.key.name}” is ready. Copy it into the app or script that will use it.
              </DialogDescription>
            </DialogHeader>
            <DialogBody className="flex flex-col gap-5">
              <div className="flex flex-col gap-2">
                <div
                  id={SECRET_ID}
                  className="flex flex-col gap-2 rounded-md border bg-subtle p-2 pl-3 sm:flex-row sm:items-center"
                >
                  <p className="min-w-0 flex-1">
                    <span className="sr-only">Your new API key: </span>
                    <code className="font-mono text-sm break-all text-primary">
                      {created.secret}
                    </code>
                  </p>
                  <CopySecretButton secret={created.secret} />
                </div>
                <Callout tone="warning" title="Store it somewhere safe: you won’t see it again">
                  Soundings keeps only a fingerprint of it. If you lose it, revoke it and create a
                  new one.
                </Callout>
              </div>
              <section aria-labelledby="new-key-use" className="flex flex-col gap-2">
                <h3 id="new-key-use" className="text-sm font-medium text-primary">
                  Use it
                </h3>
                <KeyExamples secret={created.secret} scopes={created.key.scopes} />
              </section>
            </DialogBody>
            <DialogFooter className="pt-2">
              <Button variant="primary" onClick={onDone}>
                Done
              </Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  )
}

/** "Copy key", then "Copied" for a moment (announced). */
function CopySecretButton({ secret }: { secret: string }) {
  const [copied, setCopied] = useState(false)
  const timer = useRef<number | undefined>(undefined)
  useEffect(() => () => window.clearTimeout(timer.current), [])
  return (
    <Button
      variant="secondary"
      className="shrink-0 self-start sm:self-auto"
      onClick={() => {
        void copyText(secret).then((ok) => {
          if (!ok) {
            toast.error('Couldn’t copy', { description: 'Select the key and copy it instead.' })
            return
          }
          setCopied(true)
          window.clearTimeout(timer.current)
          timer.current = window.setTimeout(() => setCopied(false), 2000)
        })
      }}
    >
      {copied ? <Check className="text-success" /> : <Copy />}
      <span aria-live="polite">{copied ? 'Copied' : 'Copy key'}</span>
    </Button>
  )
}
