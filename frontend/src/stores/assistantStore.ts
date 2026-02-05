import { create } from 'zustand'
import type { ChatMessage, ConversationSummary, BotConfigPreviewData } from '../types'
import {
  sendMessage as apiSendMessage,
  listConversations as apiListConversations,
  getConversation as apiGetConversation,
  deleteConversation as apiDeleteConversation,
  checkStatus as apiCheckStatus,
  type SSEEvent,
} from '../api/assistant'

interface AssistantState {
  isOpen: boolean
  isAvailable: boolean | null
  messages: ChatMessage[]
  conversations: ConversationSummary[]
  activeConversationId: number | null
  isLoading: boolean
  isStreaming: boolean
  showHistory: boolean
  abortController: AbortController | null

  toggle: () => void
  open: () => void
  close: () => void
  checkAvailability: () => Promise<void>
  sendMessage: (message: string) => Promise<void>
  loadConversations: () => Promise<void>
  selectConversation: (id: number) => Promise<void>
  newConversation: () => void
  deleteConversation: (id: number) => Promise<void>
  toggleHistory: () => void
  stopStreaming: () => void
}

export const useAssistantStore = create<AssistantState>((set, get) => ({
  isOpen: false,
  isAvailable: null,
  messages: [],
  conversations: [],
  activeConversationId: null,
  isLoading: false,
  isStreaming: false,
  showHistory: false,
  abortController: null,

  toggle: () => set((s) => ({ isOpen: !s.isOpen })),
  open: () => set({ isOpen: true }),
  close: () => set({ isOpen: false }),
  toggleHistory: () => set((s) => ({ showHistory: !s.showHistory })),

  checkAvailability: async () => {
    const available = await apiCheckStatus()
    set({ isAvailable: available })
  },

  sendMessage: async (message: string) => {
    const { activeConversationId, messages } = get()

    // Add user message immediately
    const userMsg: ChatMessage = { role: 'user', content: message }
    const assistantMsg: ChatMessage = { role: 'assistant', content: '', isStreaming: true }
    set({
      messages: [...messages, userMsg, assistantMsg],
      isLoading: true,
      isStreaming: true,
      showHistory: false,
    })

    const abortController = new AbortController()
    set({ abortController })

    let fullText = ''
    let newConversationId = activeConversationId
    let currentToolCalls: ChatMessage['toolCalls'] = []
    let botPreview: BotConfigPreviewData | null = null

    try {
      await apiSendMessage(
        message,
        activeConversationId,
        (event: SSEEvent) => {
          if (event.type === 'text') {
            fullText += event.content || ''
            set((s) => {
              const msgs = [...s.messages]
              const last = msgs[msgs.length - 1]
              if (last?.role === 'assistant') {
                msgs[msgs.length - 1] = { ...last, content: fullText }
              }
              return { messages: msgs }
            })
          } else if (event.type === 'tool_call') {
            currentToolCalls = [
              ...(currentToolCalls || []),
              { name: event.name || '', input: (event.input || {}) as Record<string, unknown> },
            ]
          } else if (event.type === 'tool_result') {
            if (currentToolCalls) {
              const lastTool = currentToolCalls[currentToolCalls.length - 1]
              if (lastTool) {
                lastTool.result = (event.data || {}) as Record<string, unknown>
              }
            }
          } else if (event.type === 'bot_config_preview') {
            botPreview = event.config as unknown as BotConfigPreviewData
          } else if (event.type === 'done') {
            newConversationId = event.conversation_id || newConversationId
          } else if (event.type === 'error') {
            fullText += `\n\n*Error: ${event.message}*`
          }
        },
        abortController.signal,
      )
    } catch (err: unknown) {
      if (err instanceof Error && err.name !== 'AbortError') {
        fullText += '\n\n*Connection error. Please try again.*'
      }
    }

    // Finalize assistant message
    set((s) => {
      const msgs = [...s.messages]
      const last = msgs[msgs.length - 1]
      if (last?.role === 'assistant') {
        msgs[msgs.length - 1] = {
          ...last,
          content: fullText,
          isStreaming: false,
          toolCalls: currentToolCalls?.length ? currentToolCalls : undefined,
          botConfigPreview: botPreview,
        }
      }
      return {
        messages: msgs,
        isLoading: false,
        isStreaming: false,
        abortController: null,
        activeConversationId: newConversationId,
      }
    })
  },

  loadConversations: async () => {
    try {
      const conversations = await apiListConversations()
      set({ conversations })
    } catch {
      // ignore
    }
  },

  selectConversation: async (id: number) => {
    try {
      const data = await apiGetConversation(id)
      const messages: ChatMessage[] = data.messages.map((m: { role: string; content: string; tool_calls?: unknown[]; created_at?: string }) => ({
        role: m.role as 'user' | 'assistant',
        content: m.content,
        toolCalls: m.tool_calls as ChatMessage['toolCalls'],
        createdAt: m.created_at,
      }))
      set({ messages, activeConversationId: id, showHistory: false })
    } catch {
      // ignore
    }
  },

  newConversation: () => {
    set({
      messages: [],
      activeConversationId: null,
      showHistory: false,
    })
  },

  deleteConversation: async (id: number) => {
    try {
      await apiDeleteConversation(id)
      const { conversations, activeConversationId } = get()
      set({
        conversations: conversations.filter((c) => c.id !== id),
        ...(activeConversationId === id ? { messages: [], activeConversationId: null } : {}),
      })
    } catch {
      // ignore
    }
  },

  stopStreaming: () => {
    const { abortController } = get()
    abortController?.abort()
    set({ isStreaming: false, abortController: null })
  },
}))
