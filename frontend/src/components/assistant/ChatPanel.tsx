import { useState, useRef, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { X, History, Plus, Send, Square, Trash2 } from 'lucide-react'
import { useAssistantStore } from '../../stores/assistantStore'
import ChatMessage from './ChatMessage'

export default function ChatPanel() {
  const { t } = useTranslation()
  const {
    isOpen,
    close,
    messages,
    conversations,
    showHistory,
    isStreaming,
    isLoading,
    sendMessage,
    loadConversations,
    selectConversation,
    newConversation,
    deleteConversation,
    toggleHistory,
    stopStreaming,
  } = useAssistantStore()

  const [input, setInput] = useState('')
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (isOpen) {
      loadConversations()
      setTimeout(() => inputRef.current?.focus(), 100)
    }
  }, [isOpen, loadConversations])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const handleSend = () => {
    const trimmed = input.trim()
    if (!trimmed || isLoading) return
    setInput('')
    sendMessage(trimmed)
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  if (!isOpen) return null

  return (
    <div className="fixed bottom-24 right-6 z-50 w-[400px] h-[560px] bg-gray-900 border border-gray-800 rounded-xl shadow-2xl flex flex-col overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-800 bg-gray-900/95">
        <h3 className="text-sm font-semibold text-white">{t('assistant.title')}</h3>
        <div className="flex items-center gap-1">
          <button
            onClick={newConversation}
            className="p-1.5 text-gray-400 hover:text-white rounded transition-colors"
            title={t('assistant.newChat')}
          >
            <Plus size={16} />
          </button>
          <button
            onClick={toggleHistory}
            className={`p-1.5 rounded transition-colors ${
              showHistory ? 'text-primary-400 bg-primary-600/20' : 'text-gray-400 hover:text-white'
            }`}
            title={t('assistant.history')}
          >
            <History size={16} />
          </button>
          <button
            onClick={close}
            className="p-1.5 text-gray-400 hover:text-white rounded transition-colors"
          >
            <X size={16} />
          </button>
        </div>
      </div>

      {/* Content */}
      {showHistory ? (
        /* History view */
        <div className="flex-1 overflow-y-auto p-3 space-y-2">
          {conversations.length === 0 ? (
            <p className="text-xs text-gray-500 text-center py-8">{t('assistant.noHistory')}</p>
          ) : (
            conversations.map((conv) => (
              <div
                key={conv.id}
                className="flex items-start justify-between p-2.5 rounded-lg bg-gray-800/50 hover:bg-gray-800 cursor-pointer transition-colors group"
                onClick={() => selectConversation(conv.id)}
              >
                <div className="min-w-0 flex-1">
                  <div className="text-sm text-white truncate">
                    {conv.title || 'Untitled'}
                  </div>
                  {conv.last_message_preview && (
                    <div className="text-xs text-gray-500 truncate mt-0.5">
                      {conv.last_message_preview}
                    </div>
                  )}
                  <div className="text-xs text-gray-600 mt-1">
                    {conv.message_count} messages
                  </div>
                </div>
                <button
                  onClick={(e) => {
                    e.stopPropagation()
                    deleteConversation(conv.id)
                  }}
                  className="p-1 text-gray-600 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-all"
                >
                  <Trash2 size={12} />
                </button>
              </div>
            ))
          )}
        </div>
      ) : (
        /* Chat view */
        <div className="flex-1 overflow-y-auto p-3 space-y-4">
          {messages.length === 0 && (
            <div className="text-center py-12">
              <p className="text-sm text-gray-500">{t('assistant.placeholder')}</p>
            </div>
          )}
          {messages.map((msg, i) => (
            <ChatMessage key={i} message={msg} />
          ))}
          <div ref={messagesEndRef} />
        </div>
      )}

      {/* Input */}
      <div className="border-t border-gray-800 p-3">
        <div className="flex items-center gap-2">
          <input
            ref={inputRef}
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={t('assistant.placeholder')}
            disabled={isLoading}
            className="flex-1 bg-gray-800 text-sm text-white rounded-lg px-3 py-2 border border-gray-700 focus:border-primary-500 focus:outline-none placeholder-gray-500 disabled:opacity-50"
          />
          {isStreaming ? (
            <button
              onClick={stopStreaming}
              className="p-2 bg-red-900/50 text-red-400 rounded-lg hover:bg-red-900 transition-colors"
            >
              <Square size={16} />
            </button>
          ) : (
            <button
              onClick={handleSend}
              disabled={!input.trim() || isLoading}
              className="p-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
            >
              <Send size={16} />
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
