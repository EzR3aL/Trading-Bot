import { useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

interface DiscordEmbed {
  title?: string
  description?: string
  color?: number
  footer?: { text?: string }
  image?: { url?: string }
}

interface BroadcastPreviewProps {
  discord: DiscordEmbed | null | undefined
  telegram: string | null | undefined
}

type PreviewTab = 'discord' | 'telegram'

function getDiscordColorHex(color?: number): string {
  if (!color) return '#5865f2'
  return `#${color.toString(16).padStart(6, '0')}`
}

// --- SEC-C1: safe Telegram-HTML renderer -----------------------------------
// The backend already HTML-escapes the markdown body before re-introducing
// the supported inline tags (see src/services/broadcast_service.py). We add
// a second layer of defence here: instead of dangerouslySetInnerHTML, we
// parse the small whitelist of tags ourselves and emit React elements.
// Unknown tags fall back to their escaped text content.

const ALLOWED_URL_SCHEMES = ['http://', 'https://', 'tg://'] as const

function isSafeHref(url: string): boolean {
  const lowered = url.trim().toLowerCase()
  return ALLOWED_URL_SCHEMES.some((scheme) => lowered.startsWith(scheme))
}

// Inline tag whitelist and their React renderers.
// The Python side only emits <b>, <i>, <a href="...">, optionally <br>.
// We also accept <code>, <pre>, <s>, <u> since Telegram supports them.
const INLINE_TAGS = new Set(['b', 'strong', 'i', 'em', 'u', 's', 'code', 'pre', 'br', 'a'])

interface Token {
  type: 'text' | 'open' | 'close' | 'selfclose'
  value: string
  tag?: string
  attrs?: Record<string, string>
}

function decodeEntities(text: string): string {
  // Only decode the entities the backend produced (html.escape with quote=True).
  return text
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#x27;/g, "'")
    .replace(/&amp;/g, '&')
}

function tokenize(input: string): Token[] {
  const tokens: Token[] = []
  let i = 0
  while (i < input.length) {
    const lt = input.indexOf('<', i)
    if (lt < 0) {
      tokens.push({ type: 'text', value: input.slice(i) })
      break
    }
    if (lt > i) {
      tokens.push({ type: 'text', value: input.slice(i, lt) })
    }
    const gt = input.indexOf('>', lt)
    if (gt < 0) {
      // Malformed — treat the rest as text
      tokens.push({ type: 'text', value: input.slice(lt) })
      break
    }
    const raw = input.slice(lt + 1, gt)
    const isClose = raw.startsWith('/')
    const body = isClose ? raw.slice(1) : raw
    const [tagRaw, ...attrParts] = body.trim().split(/\s+/)
    const tag = tagRaw.toLowerCase()

    if (!INLINE_TAGS.has(tag)) {
      // Unknown tag — render as plain text (already escaped)
      tokens.push({ type: 'text', value: input.slice(lt, gt + 1) })
    } else if (isClose) {
      tokens.push({ type: 'close', value: raw, tag })
    } else {
      const attrs: Record<string, string> = {}
      const joined = attrParts.join(' ')
      // Very small attribute parser: name="value"
      const attrRe = /([a-zA-Z][a-zA-Z0-9_-]*)\s*=\s*"([^"]*)"/g
      let m: RegExpExecArray | null
      while ((m = attrRe.exec(joined))) {
        attrs[m[1].toLowerCase()] = m[2]
      }
      const selfClose = body.endsWith('/') || tag === 'br'
      tokens.push({
        type: selfClose ? 'selfclose' : 'open',
        value: raw,
        tag,
        attrs,
      })
    }
    i = gt + 1
  }
  return tokens
}

function renderTokens(tokens: Token[]): ReactNode {
  // Recursive descent: consume tokens into a tree of React nodes.
  const out: ReactNode[] = []
  let key = 0

  function readUntil(closingTag: string | null): ReactNode[] {
    const nodes: ReactNode[] = []
    while (tokens.length > 0) {
      const tok = tokens.shift()!
      if (tok.type === 'close') {
        if (tok.tag === closingTag) return nodes
        // Stray close — ignore
        continue
      }
      if (tok.type === 'text') {
        nodes.push(decodeEntities(tok.value))
        continue
      }
      if (tok.type === 'selfclose' && tok.tag === 'br') {
        nodes.push(<br key={`k${key++}`} />)
        continue
      }
      if (tok.type === 'open' && tok.tag) {
        const children = readUntil(tok.tag)
        nodes.push(wrapTag(tok.tag, tok.attrs ?? {}, children, key++))
      }
    }
    return nodes
  }

  function wrapTag(
    tag: string,
    attrs: Record<string, string>,
    children: ReactNode[],
    k: number,
  ): ReactNode {
    switch (tag) {
      case 'b':
      case 'strong':
        return <b key={`k${k}`}>{children}</b>
      case 'i':
      case 'em':
        return <i key={`k${k}`}>{children}</i>
      case 'u':
        return <u key={`k${k}`}>{children}</u>
      case 's':
        return <s key={`k${k}`}>{children}</s>
      case 'code':
        return <code key={`k${k}`}>{children}</code>
      case 'pre':
        return <pre key={`k${k}`}>{children}</pre>
      case 'a': {
        const href = attrs.href ?? ''
        if (!isSafeHref(href)) {
          // Drop the link, keep the visible text.
          return <span key={`k${k}`}>{children}</span>
        }
        return (
          <a key={`k${k}`} href={href} target="_blank" rel="noopener noreferrer">
            {children}
          </a>
        )
      }
      default:
        return <span key={`k${k}`}>{children}</span>
    }
  }

  while (tokens.length > 0) {
    const rendered = readUntil(null)
    out.push(...rendered)
  }
  return out
}

function SafeTelegramHtml({ html }: { html: string }) {
  // Preserve newlines as <br/>s so the preview matches Telegram's wrapping.
  // Backend emits '\n' between header and body.
  const withBreaks = html.replace(/\n/g, '<br/>')
  const tokens = tokenize(withBreaks)
  return <>{renderTokens(tokens)}</>
}

export default function BroadcastPreview({ discord, telegram }: BroadcastPreviewProps) {
  const { t } = useTranslation()
  const [activeTab, setActiveTab] = useState<PreviewTab>('discord')

  const tabs: { key: PreviewTab; label: string }[] = [
    { key: 'discord', label: t('broadcast.tabDiscord') },
    { key: 'telegram', label: t('broadcast.tabTelegram') },
  ]

  return (
    <div>
      {/* Tab bar */}
      <div className="flex gap-1 mb-3">
        {tabs.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-all duration-200 ${
              activeTab === tab.key
                ? 'bg-primary-500/20 text-primary-400 ring-1 ring-primary-500/30'
                : 'text-gray-500 hover:text-white hover:bg-white/5'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Discord preview */}
      {activeTab === 'discord' && (
        discord ? (
          <div className="rounded-lg overflow-hidden" style={{ backgroundColor: '#2f3136' }}>
            <div className="flex">
              <div
                className="w-1 flex-shrink-0 rounded-l"
                style={{ backgroundColor: getDiscordColorHex(discord.color) }}
              />
              <div className="p-3 flex-1 min-w-0">
                {discord.title && (
                  <div className="text-sm font-semibold text-white mb-1">{discord.title}</div>
                )}
                {discord.description && (
                  <div className="text-sm text-gray-300 whitespace-pre-wrap break-words">
                    {discord.description}
                  </div>
                )}
                {discord.image?.url && (
                  <img
                    src={discord.image.url}
                    alt=""
                    className="mt-2 max-w-full rounded max-h-48 object-contain"
                  />
                )}
                {discord.footer?.text && (
                  <div className="text-[11px] text-gray-500 mt-2 pt-2 border-t border-white/5">
                    {discord.footer.text}
                  </div>
                )}
              </div>
            </div>
          </div>
        ) : (
          <div className="text-sm text-gray-500 italic p-3">{t('broadcast.noPreview', 'Keine Vorschau verfügbar')}</div>
        )
      )}

      {/* Telegram preview */}
      {activeTab === 'telegram' && (
        telegram ? (
          <div className="rounded-lg p-3 max-w-md" style={{ backgroundColor: '#1e2c3a' }}>
            <div
              className="text-sm text-gray-200 break-words [&_b]:font-semibold [&_i]:italic [&_a]:text-blue-400 [&_a]:underline [&_code]:bg-white/10 [&_code]:px-1 [&_code]:rounded"
            >
              <SafeTelegramHtml html={telegram} />
            </div>
          </div>
        ) : (
          <div className="text-sm text-gray-500 italic p-3">{t('broadcast.noPreview', 'Keine Vorschau verfügbar')}</div>
        )
      )}
    </div>
  )
}
