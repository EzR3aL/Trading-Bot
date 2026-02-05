import { useTranslation } from 'react-i18next'
import Markdown from 'react-markdown'
import { Bot, User, Loader2, Wrench } from 'lucide-react'
import type { ChatMessage as ChatMessageType } from '../../types'
import BotConfigPreview from './BotConfigPreview'

export default function ChatMessage({ message }: { message: ChatMessageType }) {
  const { t } = useTranslation()
  const isUser = message.role === 'user'

  return (
    <div className={`flex gap-2.5 ${isUser ? 'flex-row-reverse' : ''}`}>
      {/* Avatar */}
      <div
        className={`flex-shrink-0 w-7 h-7 rounded-full flex items-center justify-center ${
          isUser ? 'bg-primary-600/30' : 'bg-gray-700'
        }`}
      >
        {isUser ? <User size={14} className="text-primary-400" /> : <Bot size={14} className="text-gray-300" />}
      </div>

      {/* Bubble */}
      <div className={`max-w-[85%] space-y-2`}>
        <div
          className={`rounded-xl px-3.5 py-2.5 text-sm leading-relaxed ${
            isUser
              ? 'bg-primary-600/20 text-primary-100 rounded-tr-sm'
              : 'bg-gray-800 text-gray-200 rounded-tl-sm'
          }`}
        >
          {message.isStreaming && !message.content ? (
            <div className="flex items-center gap-2 text-gray-400">
              <Loader2 size={14} className="animate-spin" />
              {t('assistant.typing')}
            </div>
          ) : (
            <div className="prose prose-invert prose-sm max-w-none [&>p]:mb-2 [&>p:last-child]:mb-0 [&>ul]:mb-2 [&>ol]:mb-2">
              <Markdown>{message.content}</Markdown>
            </div>
          )}
        </div>

        {/* Tool calls */}
        {message.toolCalls && message.toolCalls.length > 0 && (
          <div className="space-y-1">
            {message.toolCalls.map((tc, i) => (
              <div key={i} className="flex items-center gap-1.5 text-xs text-gray-500">
                <Wrench size={10} />
                <span>{tc.name.replace(/_/g, ' ')}</span>
                {tc.result && <span className="text-green-500">&#10003;</span>}
              </div>
            ))}
          </div>
        )}

        {/* Bot config preview */}
        {message.botConfigPreview && (
          <BotConfigPreview config={message.botConfigPreview} />
        )}
      </div>
    </div>
  )
}
