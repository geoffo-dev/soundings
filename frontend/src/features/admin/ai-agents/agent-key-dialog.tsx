import { KeyRound } from 'lucide-react'
import { useState } from 'react'

import type { AiAgent, CreatedApiKey } from '@/api/types'
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
import { CodeSnippet, CopyLine } from '@/features/api-keys/code-snippet'

import { remoteMcpServerManifest } from './agent-rules'

export interface AgentKeyReveal {
  agent: AiAgent
  key: CreatedApiKey
  secret_manifest: string
  /** Rotation: the key it replaced (already revoked). */
  rotated?: boolean
}

const DONE_ID = 'agent-key-done'
const COPY_AFTER_ALL_ID = 'agent-key-copy-after-all'

/**
 * An agent's key, shown once (contract-phase6 §3.1, Phase 5's pattern): the
 * key and a ready-to-apply Kubernetes Secret with Copy, the agent's own
 * RemoteMCPServer (no key in it) and "you won't see it again". "I've copied it"
 * (or Esc, ×) asks once while nothing with the key was copied. The secret lives
 * only in the mutation's result: `onDone` resets it once the dialog has closed.
 */
export function AgentKeyDialog({
  reveal,
  mcpUrl,
  onDone,
}: {
  reveal: AgentKeyReveal | undefined
  mcpUrl: string
  onDone: () => void
}) {
  const [shown, setShown] = useState<AgentKeyReveal | undefined>(undefined)
  const [closed, setClosed] = useState<AgentKeyReveal | undefined>(undefined)
  const [open, setOpen] = useState(false)
  const [copied, setCopied] = useState(false)
  const [warned, setWarned] = useState(false)
  if (reveal && reveal !== shown && reveal !== closed) {
    setShown(reveal)
    setOpen(true)
    setCopied(false)
    setWarned(false)
  }

  const close = () => {
    if (!copied && !warned) {
      setWarned(true)
      requestAnimationFrame(() => document.getElementById(COPY_AFTER_ALL_ID)?.focus())
      return
    }
    setOpen(false)
  }
  const noteCopy = (value: string) => {
    if (!shown || !value.includes(shown.key.secret)) return
    setCopied(true)
    if (warned) {
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
        // Open on the dialog itself (its title is announced; Tab reaches the key's Copy):
        // Radix would focus that icon button, whose tooltip then covers the header.
        onOpenAutoFocus={(event) => {
          event.preventDefault()
          ;(event.currentTarget as HTMLElement | null)?.focus({ preventScroll: true })
        }}
        onCloseAutoFocus={() => {
          setClosed(shown)
          setShown(undefined)
          onDone()
        }}
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
                {shown.rotated ? 'Copy the agent’s new key' : 'Copy the agent’s key'}
              </DialogTitle>
              <DialogDescription>
                {shown.rotated
                  ? `${shown.agent.display_name}’s old key stopped working. Put the new one in its Secret: the agent fails until you do.`
                  : `${shown.agent.display_name} is registered. Give kagent its key as a Secret in ${shown.agent.namespace}.`}
              </DialogDescription>
            </DialogHeader>
            <DialogBody className="flex flex-col gap-5">
              <div className="flex flex-col gap-2">
                <p className="text-sm font-medium text-primary">The key</p>
                <CopyLine
                  value={shown.key.secret}
                  label="the agent’s key"
                  wrap
                  onCopied={noteCopy}
                />
                <Callout tone="warning" title="You won’t see it again">
                  Whoever has it can act as {shown.agent.display_name} while one of its runs is
                  open: read that run’s idea and save its result. Keep it only in the Secret.
                  Soundings stores a fingerprint; if it leaks, rotate the key.
                </Callout>
              </div>
              <section aria-labelledby="agent-key-secret" className="flex flex-col gap-2">
                <h3 id="agent-key-secret" className="text-sm font-medium text-primary">
                  1. Apply the Secret
                </h3>
                <p className="text-sm text-muted">
                  <code className="font-mono text-secondary">kubectl apply -f -</code> and paste it,
                  or save it as a file. It holds the whole Authorization header kagent sends.
                </p>
                <CodeSnippet
                  code={shown.secret_manifest}
                  label="the Secret manifest"
                  onCopied={noteCopy}
                />
              </section>
              <section aria-labelledby="agent-key-mcp" className="flex flex-col gap-2">
                <h3 id="agent-key-mcp" className="text-sm font-medium text-primary">
                  2. Point the agent at Soundings
                </h3>
                <p className="text-sm text-muted">
                  The agent’s own MCP server entry, reading the header from that Secret; add its
                  tools to the Agent. The URL is the one in Settings in effect.
                </p>
                <CodeSnippet
                  code={remoteMcpServerManifest(shown.agent, mcpUrl)}
                  label="the RemoteMCPServer manifest"
                />
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
                <CopySecretAfterAll secret={shown.key.secret} onCopied={noteCopy} />
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

function CopySecretAfterAll({
  secret,
  onCopied,
}: {
  secret: string
  onCopied: (value: string) => void
}) {
  return (
    <Button
      id={COPY_AFTER_ALL_ID}
      variant="primary"
      onClick={() => {
        void copyText(secret).then((ok) => {
          if (ok) onCopied(secret)
          else toast.error('Couldn’t copy', { description: 'Select the key and copy it instead.' })
        })
      }}
    >
      Copy key
    </Button>
  )
}
