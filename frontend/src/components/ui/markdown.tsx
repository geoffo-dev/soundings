import { Check, ExternalLink } from 'lucide-react'
import { useMemo } from 'react'
import ReactMarkdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'

import { MENTION_HREF } from '@/lib/mentions'
import { cn } from '@/lib/utils'

const isExternal = (href: string | undefined) => !!href && /^https?:\/\//i.test(href)

/**
 * Element styles for rendered Markdown. Raw HTML is never rendered (skipHtml)
 * and unsafe URLs (javascript:, data:) are stripped by react-markdown's default
 * urlTransform. Images are shown as links so nothing is fetched from elsewhere.
 */
const components: Components = {
  // Headings shift down one level: the page already owns the h1.
  h1: ({ node: _node, children, ...props }) => (
    <h2 className="mt-6 mb-2 text-xl font-semibold first:mt-0" {...props}>
      {children}
    </h2>
  ),
  h2: ({ node: _node, children, ...props }) => (
    <h3 className="mt-6 mb-2 text-lg font-semibold first:mt-0" {...props}>
      {children}
    </h3>
  ),
  h3: ({ node: _node, children, ...props }) => (
    <h4 className="mt-5 mb-1.5 text-base font-semibold first:mt-0" {...props}>
      {children}
    </h4>
  ),
  h4: ({ node: _node, children, ...props }) => (
    <h5 className="mt-4 mb-1 text-base font-medium first:mt-0" {...props}>
      {children}
    </h5>
  ),
  p: ({ node: _node, ...props }) => <p className="my-3 first:mt-0 last:mb-0" {...props} />,
  a: ({ node: _node, href, children, ...props }) => (
    <a
      href={href}
      className="font-medium text-accent underline decoration-accent/30 underline-offset-2 hover:decoration-accent"
      {...(isExternal(href) ? { target: '_blank', rel: 'noopener noreferrer nofollow' } : {})}
      {...props}
    >
      {children}
    </a>
  ),
  ul: ({ node: _node, className, ...props }) => (
    <ul
      className={cn(
        'my-3 list-disc pl-5 marker:text-muted [&_ul]:my-1',
        className?.includes('contains-task-list') && 'list-none pl-1',
      )}
      {...props}
    />
  ),
  ol: ({ node: _node, ...props }) => (
    <ol className="my-3 list-decimal pl-5 marker:text-muted [&_ol]:my-1" {...props} />
  ),
  li: ({ node: _node, ...props }) => <li className="my-1 pl-1" {...props} />,
  blockquote: ({ node: _node, ...props }) => (
    <blockquote className="my-4 border-l-2 border-strong pl-4 text-secondary" {...props} />
  ),
  hr: () => <hr className="my-6 border-subtle" />,
  strong: ({ node: _node, ...props }) => (
    <strong className="font-semibold text-primary" {...props} />
  ),
  code: ({ node: _node, className, ...props }) => (
    <code
      className={cn(
        'rounded-sm bg-subtle px-1 py-0.5 font-mono text-[0.9em]',
        className?.startsWith('language-') && 'bg-transparent p-0',
        className,
      )}
      {...props}
    />
  ),
  pre: ({ node: _node, ...props }) => (
    <pre
      className="my-4 overflow-x-auto rounded-lg border bg-background p-3 text-sm leading-relaxed"
      {...props}
    />
  ),
  table: ({ node: _node, ...props }) => (
    <div className="my-4 overflow-x-auto rounded-lg border">
      <table className="w-full border-collapse text-sm" {...props} />
    </div>
  ),
  th: ({ node: _node, ...props }) => (
    <th
      className="border-b bg-background px-3 py-2 text-left font-medium text-secondary"
      {...props}
    />
  ),
  td: ({ node: _node, ...props }) => <td className="border-b border-subtle px-3 py-2" {...props} />,
  // GFM task lists: a labelled, read-only tick instead of an unlabelled disabled checkbox.
  input: ({ checked, type }) =>
    type === 'checkbox' ? (
      <span
        role="img"
        aria-label={checked ? 'Done' : 'Not done'}
        className={cn(
          'mr-2 inline-flex size-4 translate-y-0.5 items-center justify-center rounded-sm border',
          checked ? 'border-accent bg-accent text-accent-foreground' : 'border-control',
        )}
      >
        {checked && <Check aria-hidden="true" strokeWidth={3} className="size-3" />}
      </span>
    ) : null,
  img: ({ src, alt }) =>
    typeof src !== 'string' ? null : (
      <a
        href={src}
        target="_blank"
        rel="noopener noreferrer nofollow"
        className="inline-flex items-center gap-1 text-accent underline underline-offset-2"
      >
        {alt ?? 'Image'}
        <ExternalLink aria-hidden="true" className="size-3" />
      </a>
    ),
}

/* ------------------------------------------------------------------ */
/* @mentions (contract-phase3 §3.8)                                    */
/* ------------------------------------------------------------------ */

/** The few Markdown (mdast) node fields the mention plugin reads. */
interface MdNode {
  type: string
  value?: string
  url?: string
  children?: MdNode[]
  data?: Record<string, unknown>
}

function plainText(node: MdNode): string {
  return node.value ?? (node.children ?? []).map(plainText).join('')
}

function replaceMentions(node: MdNode): void {
  const children = node.children
  if (!children) return
  children.forEach((child, index) => {
    const match = child.type === 'link' && child.url ? MENTION_HREF.exec(child.url) : null
    const before = children[index - 1]
    if (match && before?.type === 'text' && before.value?.endsWith('@')) {
      before.value = before.value.slice(0, -1)
      children[index] = {
        type: 'text',
        value: `@${plainText(child)}`,
        data: { hName: 'span', hProperties: { dataMention: (match[1] ?? '').toLowerCase() } },
      }
      return
    }
    replaceMentions(child)
  })
}

/**
 * `@[Name](user:<id>)` becomes a name chip (a span, never a link: `user:` isn't
 * a URL anyone should follow). Anything else stays as written.
 */
function remarkMentions() {
  return (tree: MdNode) => replaceMentions(tree)
}

const mentionChip = 'rounded-sm px-1 py-px font-medium whitespace-nowrap [overflow-wrap:normal]'

export interface MarkdownProps {
  children: string
  className?: string
  /** Mentions of this user (you) are highlighted. */
  mentionSelfId?: string
}

export function Markdown({ children, className, mentionSelfId }: MarkdownProps) {
  const withMentions = useMemo<Components>(
    () => ({
      ...components,
      span: ({ node: _node, children: content, ...props }) => {
        const userId = (props as Record<string, unknown>)['data-mention']
        if (typeof userId !== 'string') return <span {...props}>{content}</span>
        const self = userId === mentionSelfId?.toLowerCase()
        return (
          <span
            data-mention={userId}
            className={cn(
              mentionChip,
              self ? 'bg-accent-subtle text-accent' : 'bg-subtle text-primary',
            )}
          >
            {content}
          </span>
        )
      },
    }),
    [mentionSelfId],
  )
  return (
    <div
      data-slot="markdown"
      className={cn('text-base [overflow-wrap:anywhere] text-primary', className)}
    >
      <ReactMarkdown remarkPlugins={[remarkGfm, remarkMentions]} skipHtml components={withMentions}>
        {children}
      </ReactMarkdown>
    </div>
  )
}
