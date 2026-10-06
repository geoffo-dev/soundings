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
import { toast } from '@/components/ui/toaster'
import { copyText } from '@/features/admin/copy-button'
import { focusRow } from '@/lib/return-to-row'

import { KeyExamples } from './connect-mcp'
import { accessSummary } from './key-rules'

const SECRET_ID = 'new-key-secret'
const COPY_AFTER_ALL_ID = 'new-key-copy-after-all'
const DONE_ID = 'new-key-done'

/**
 * The new key, shown once (contract-phase5 §3.1): the full key with Copy, what
 * anyone holding it can do ("Treat it like a password: …"), "you won't see it
 * again", and ready-to-paste examples with the key filled in. "I've copied it"
 * closes it. Closing (that, Esc or ×) before anything with the key was copied
 * asks once: a second close goes. The secret lives only in the create
 * mutation's result; once the dialog has closed, `onDone` resets the mutation,
 * so it leaves the cache, and focus goes to the new key's row. A click outside
 * doesn't close it.
 */
export function SecretDialog({
  created,
  onDone,
}: {
  created: CreatedApiKey | undefined
  onDone: () => void
}) {
  // What is on screen: kept through the closing animation, then dropped with the secret.
  const [shown, setShown] = useState<CreatedApiKey | undefined>(undefined)
  const [open, setOpen] = useState(false)
  // The result already shown and closed (until `onDone` has reset it, it must not reopen).
  const [closed, setClosed] = useState<CreatedApiKey | undefined>(undefined)
  // Copied by any means (the button, an example with the key, a selection): no question.
  const [copied, setCopied] = useState(false)
  const [warned, setWarned] = useState(false)
  if (created && created !== shown && created !== closed) {
    setShown(created)
    setOpen(true)
    setCopied(false)
    setWarned(false)
  }

  const close = () => {
    if (!copied && !warned) {
      setWarned(true)
      // The question takes focus (its "Copy key" button): Enter copies, Esc closes after all.
      requestAnimationFrame(() => document.getElementById(COPY_AFTER_ALL_ID)?.focus())
      return
    }
    setOpen(false)
  }
  const noteCopy = (value: string) => {
    if (!shown || !value.includes(shown.secret)) return
    setCopied(true)
    if (warned) {
      // Copied after the question: back to "I've copied it", which takes focus.
      setWarned(false)
      requestAnimationFrame(() => document.getElementById(DONE_ID)?.focus())
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (next) setOpen(true)
        else close()
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
          const keyId = shown?.key.id
          setClosed(shown)
          setShown(undefined)
          onDone()
          if (keyId && focusRow(keyId)) event.preventDefault()
        }}
        // Selecting the key and copying it by hand counts too.
        onCopy={() => {
          const selected = window.getSelection()?.toString() ?? ''
          if (selected) noteCopy(selected)
        }}
      >
        {shown && (
          <>
            <DialogHeader>
              <DialogTitle className="flex items-center gap-2">
                <KeyRound aria-hidden="true" className="size-4 text-muted" />
                Copy your new key
              </DialogTitle>
              <DialogDescription>
                “{shown.key.name}” is ready. Copy it into the app or script that will use it.
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
                    <code className="font-mono text-sm break-all text-primary">{shown.secret}</code>
                  </p>
                  <CopySecretButton secret={shown.secret} onCopied={() => noteCopy(shown.secret)} />
                </div>
                <Callout tone="warning" title="Treat it like a password">
                  Anyone who has it can act as you: {accessSummary(shown.key)}. Store it somewhere
                  safe: you won’t see it again. Soundings keeps only a fingerprint of it; if you
                  lose it, revoke it and create a new one.
                </Callout>
              </div>
              <section aria-labelledby="new-key-use" className="flex flex-col gap-2">
                <h3 id="new-key-use" className="text-sm font-medium text-primary">
                  Use it
                </h3>
                <KeyExamples secret={shown.secret} scopes={shown.key.scopes} onCopied={noteCopy} />
              </section>
            </DialogBody>
            {warned ? (
              <DialogFooter className="pt-2">
                <p role="alert" className="text-sm font-medium text-warning sm:mr-auto">
                  You haven’t copied the key. Once this closes, it can’t be shown again.
                </p>
                <Button variant="ghost" onClick={() => setOpen(false)}>
                  Close without copying
                </Button>
                <CopySecretButton
                  id={COPY_AFTER_ALL_ID}
                  variant="primary"
                  secret={shown.secret}
                  onCopied={() => noteCopy(shown.secret)}
                />
              </DialogFooter>
            ) : (
              <DialogFooter className="pt-2">
                <Button id={DONE_ID} variant="primary" onClick={close}>
                  I’ve copied it
                </Button>
              </DialogFooter>
            )}
          </>
        )}
      </DialogContent>
    </Dialog>
  )
}

/** "Copy key", then "Copied" for a moment (announced). */
function CopySecretButton({
  id,
  secret,
  onCopied,
  variant = 'secondary',
}: {
  id?: string
  secret: string
  onCopied: () => void
  variant?: 'secondary' | 'primary'
}) {
  const [copied, setCopied] = useState(false)
  const timer = useRef<number | undefined>(undefined)
  useEffect(() => () => window.clearTimeout(timer.current), [])
  return (
    <Button
      id={id}
      variant={variant}
      // Beside the key: its own size; in the footer: like the footer's other buttons.
      className={variant === 'secondary' ? 'shrink-0 self-start sm:self-auto' : undefined}
      onClick={() => {
        void copyText(secret).then((ok) => {
          if (!ok) {
            toast.error('Couldn’t copy', { description: 'Select the key and copy it instead.' })
            return
          }
          setCopied(true)
          onCopied()
          window.clearTimeout(timer.current)
          timer.current = window.setTimeout(() => setCopied(false), 2000)
        })
      }}
    >
      {copied ? (
        <Check className={variant === 'secondary' ? 'text-success' : undefined} />
      ) : (
        <Copy />
      )}
      <span aria-live="polite">{copied ? 'Copied' : 'Copy key'}</span>
    </Button>
  )
}
