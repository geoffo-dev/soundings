import { Check, ExternalLink } from 'lucide-react'
import { useMemo } from 'react'
import ReactMarkdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'

import { exactMention, MENTION_HREF } from '@/lib/mentions'
import { cn } from '@/lib/utils'

const isExternal = (href: string | undefined) => !!href && /^https?:/i.test(href)

const URL_SCHEME = /^([A-Za-z][A-Za-z0-9+.-]*):/
const LINK_SCHEMES = new Set(['http', 'https', 'mailto'])

/**
 * The links Markdown may keep: absolute `http`, `https` and `mailto` URLs only,
 * the same allow-list as the exported PDF (backend `safe_href`), so the preview
 * never shows a link the document drops. Relative and protocol-relative
 * (`//host`) URLs, fragments and every other scheme (`javascript:`, `data:`,
 * `tel:`, `irc:`, `xmpp:`…) lose their link and stay as text.
 */
export function safeMarkdownUrl(url: string): string | null {
  const scheme = URL_SCHEME.exec(url)?.[1]?.toLowerCase()
  return scheme && LINK_SCHEMES.has(scheme) ? url : null
}

const linkClass =
  'font-medium text-accent underline decoration-accent/30 underline-offset-2 hover:decoration-accent'

/**
 * Element styles for rendered Markdown. Raw HTML is never rendered (skipHtml)
 * and only safe URLs survive (`safeMarkdownUrl`): a link without one is plain
 * text. Images are shown as links so nothing is fetched from elsewhere.
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
    <h5 className="mt-4 mb-1 text-base font-semibold text-secondary first:mt-0" {...props}>
      {children}
    </h5>
  ),
  h5: ({ node: _node, children, ...props }) => (
    <h6 className="mt-4 mb-1 text-sm font-semibold text-secondary first:mt-0" {...props}>
      {children}
    </h6>
  ),
  h6: ({ node: _node, children, ...props }) => (
    <h6 className="mt-4 mb-1 text-sm font-semibold text-secondary first:mt-0" {...props}>
      {children}
    </h6>
  ),
  p: ({ node: _node, ...props }) => <p className="my-3 first:mt-0 last:mb-0" {...props} />,
  a: ({ node: _node, href, children, ...props }) =>
    href ? (
      <a
        href={href}
        className={linkClass}
        {...(isExternal(href) ? { target: '_blank', rel: 'noopener noreferrer nofollow' } : {})}
        {...props}
      >
        {children}
      </a>
    ) : (
      // A link whose URL was dropped: its text only.
      <span>{children}</span>
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
    typeof src !== 'string' || !src ? (
      alt ? (
        <span>{alt}</span>
      ) : null
    ) : (
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

/**
 * Headings inside one section of a longer document whose section titles are
 * already h2 (the proposal editor): one level down but never above h3 (`#` and
 * `##` are h3, `###` h4, `####` h5, deeper h6), as the exported PDF and Markdown
 * have them (backend `app/proposals/markdown.py`). Every level stays visibly a
 * heading (semibold, with its own size and spacing step), never body text with a
 * different weight.
 */
const nestedHeadingClass = {
  h3: 'mt-6 mb-2 text-lg font-semibold first:mt-0',
  h4: 'mt-5 mb-1.5 text-base font-semibold first:mt-0',
  h5: 'mt-4 mb-1 text-base font-semibold text-secondary first:mt-0',
  h6: 'mt-4 mb-1 text-sm font-semibold text-secondary first:mt-0',
}
const nestedHeadings: Components = {
  h1: ({ node: _node, children, ...props }) => (
    <h3 className={nestedHeadingClass.h3} {...props}>
      {children}
    </h3>
  ),
  h2: ({ node: _node, children, ...props }) => (
    <h3 className={nestedHeadingClass.h3} {...props}>
      {children}
    </h3>
  ),
  h3: ({ node: _node, children, ...props }) => (
    <h4 className={nestedHeadingClass.h4} {...props}>
      {children}
    </h4>
  ),
  h4: ({ node: _node, children, ...props }) => (
    <h5 className={nestedHeadingClass.h5} {...props}>
      {children}
    </h5>
  ),
  h5: ({ node: _node, children, ...props }) => (
    <h6 className={nestedHeadingClass.h6} {...props}>
      {children}
    </h6>
  ),
  h6: ({ node: _node, children, ...props }) => (
    <h6 className={nestedHeadingClass.h6} {...props}>
      {children}
    </h6>
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
  position?: { start: { offset?: number }; end: { offset?: number } }
}

function plainText(node: MdNode): string {
  return node.value ?? (node.children ?? []).map(plainText).join('')
}

/**
 * The person a `user:` link names, if its source is exactly one token as the
 * server reads it (`@[Label](user:<id>)`, lib/mentions); else null. Other
 * spellings Markdown also accepts (a title, `<user:…>`, brackets in the label)
 * are never rewritten or notified by the server, so they must not look like a
 * mention: their label could be anything.
 */
function canonicalMention(link: MdNode, source: string): { label: string; userId: string } | null {
  const start = link.position?.start.offset
  const end = link.position?.end.offset
  if (start === undefined || end === undefined || start < 1) return null
  const token = exactMention(source.slice(start - 1, end))
  return token && { label: token.label, userId: token.userId }
}

function replaceMentions(node: MdNode, source: string): void {
  const children = node.children
  if (!children) return
  const next: MdNode[] = []
  for (const child of children) {
    if (child.type === 'link' && child.url && MENTION_HREF.test(child.url)) {
      const before = next.at(-1)
      const mention = before?.type === 'text' ? canonicalMention(child, source) : null
      if (before && mention && before.value?.endsWith('@')) {
        before.value = before.value.slice(0, -1)
        next.push({
          type: 'text',
          value: `@${mention.label}`,
          data: { hName: 'span', hProperties: { dataMention: mention.userId } },
        })
      } else {
        // Not a mention: its text, never a link (`user:` isn't a URL to follow).
        next.push({ type: 'text', value: plainText(child) })
      }
      continue
    }
    replaceMentions(child, source)
    next.push(child)
  }
  node.children = next
}

/**
 * `@[Name](user:<id>)` becomes a name chip (a span, never a link: `user:` isn't
 * a URL anyone should follow). Anything else stays as written.
 */
function remarkMentions() {
  // The source text is react-markdown's `children`, a string (the file's value).
  return (tree: MdNode, file: { value: unknown }) =>
    replaceMentions(tree, typeof file.value === 'string' ? file.value : '')
}

/** Tight, so punctuation stays with the name ("@Ada Lovelace:"). */
const mentionChip = 'rounded-sm px-0.5 font-medium whitespace-nowrap [overflow-wrap:normal]'

export interface MarkdownProps {
  children: string
  className?: string
  /** Mentions of this user (you) are highlighted. */
  mentionSelfId?: string
  /** Section text under an h2 section title (proposals): headings start at h3. */
  nested?: boolean
}

export function Markdown({ children, className, mentionSelfId, nested = false }: MarkdownProps) {
  const withMentions = useMemo<Components>(
    () => ({
      ...components,
      ...(nested ? nestedHeadings : {}),
      span: ({ node: _node, children: content, ...props }) => {
        const userId = (props as Record<string, unknown>)['data-mention']
        if (typeof userId !== 'string') return <span {...props}>{content}</span>
        const self = userId === mentionSelfId?.toLowerCase()
        return (
          <span
            data-mention={userId}
            data-mention-self={self || undefined}
            // You: a tint, not the accent text colour links use.
            className={cn(mentionChip, self ? 'bg-accent-subtle' : 'bg-subtle', 'text-primary')}
          >
            {content}
          </span>
        )
      },
    }),
    [mentionSelfId, nested],
  )
  return (
    <div
      data-slot="markdown"
      className={cn('text-base [overflow-wrap:anywhere] text-primary', className)}
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMentions]}
        skipHtml
        urlTransform={safeMarkdownUrl}
        components={withMentions}
      >
        {children}
      </ReactMarkdown>
    </div>
  )
}
