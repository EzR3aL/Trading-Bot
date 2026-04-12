import { useState } from 'react'
import { useTranslation } from 'react-i18next'

interface DiscordEmbed {
  title?: string
  description?: string
  color?: number
  footer?: { text?: string }
  image?: { url?: string }
}

interface BroadcastPreviewProps {
  discord: DiscordEmbed
  telegram: string
  whatsapp: string
}

type PreviewTab = 'discord' | 'telegram' | 'whatsapp'

function renderWhatsappBold(text: string) {
  const parts = text.split(/(\*[^*]+\*)/)
  return parts.map((part, i) => {
    if (part.startsWith('*') && part.endsWith('*')) {
      return <strong key={i}>{part.slice(1, -1)}</strong>
    }
    return <span key={i}>{part}</span>
  })
}

function getDiscordColorHex(color?: number): string {
  if (!color) return '#5865f2'
  return `#${color.toString(16).padStart(6, '0')}`
}

export default function BroadcastPreview({ discord, telegram, whatsapp }: BroadcastPreviewProps) {
  const { t } = useTranslation()
  const [activeTab, setActiveTab] = useState<PreviewTab>('discord')

  const tabs: { key: PreviewTab; label: string }[] = [
    { key: 'discord', label: t('broadcast.tabDiscord') },
    { key: 'telegram', label: t('broadcast.tabTelegram') },
    { key: 'whatsapp', label: t('broadcast.tabWhatsApp') },
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
      )}

      {/* Telegram preview */}
      {activeTab === 'telegram' && (
        <div className="rounded-lg p-3 max-w-md" style={{ backgroundColor: '#1e2c3a' }}>
          <div
            className="text-sm text-gray-200 break-words [&_b]:font-semibold [&_i]:italic [&_a]:text-blue-400 [&_a]:underline [&_code]:bg-white/10 [&_code]:px-1 [&_code]:rounded"
            dangerouslySetInnerHTML={{ __html: telegram }}
          />
        </div>
      )}

      {/* WhatsApp preview */}
      {activeTab === 'whatsapp' && (
        <div
          className="rounded-lg p-3 max-w-md"
          style={{ backgroundColor: '#005c4b' }}
        >
          <div className="text-sm text-white whitespace-pre-wrap break-words">
            {renderWhatsappBold(whatsapp)}
          </div>
        </div>
      )}
    </div>
  )
}
