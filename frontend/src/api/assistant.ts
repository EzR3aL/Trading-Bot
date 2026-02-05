/**
 * AI Trading Assistant API client.
 *
 * Uses fetch() for SSE streaming, axios for REST endpoints.
 */

import api from './client'
import type { ConversationSummary } from '../types'

export interface SSEEvent {
  type: 'text' | 'tool_call' | 'tool_result' | 'bot_config_preview' | 'done' | 'error'
  content?: string
  name?: string
  input?: Record<string, unknown>
  data?: Record<string, unknown>
  config?: Record<string, unknown>
  conversation_id?: number
  tokens?: { input: number; output: number }
  message?: string
}

export async function sendMessage(
  message: string,
  conversationId: number | null,
  onEvent: (event: SSEEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const token = localStorage.getItem('access_token')
  const response = await fetch('/api/assistant/chat', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ message, conversation_id: conversationId }),
    signal,
  })

  if (!response.ok) {
    const text = await response.text()
    throw new Error(text || `HTTP ${response.status}`)
  }

  const reader = response.body!.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() || ''

    for (const line of lines) {
      if (line.startsWith('data: ')) {
        try {
          const event: SSEEvent = JSON.parse(line.slice(6))
          onEvent(event)
        } catch {
          // skip malformed events
        }
      }
    }
  }
}

export async function checkStatus(): Promise<boolean> {
  try {
    const res = await api.get('/assistant/status')
    return res.data.available
  } catch {
    return false
  }
}

export async function listConversations(): Promise<ConversationSummary[]> {
  const res = await api.get('/assistant/conversations')
  return res.data
}

export async function getConversation(id: number) {
  const res = await api.get(`/assistant/conversations/${id}`)
  return res.data
}

export async function deleteConversation(id: number) {
  await api.delete(`/assistant/conversations/${id}`)
}

export async function createConversation() {
  const res = await api.post('/assistant/conversations')
  return res.data
}

export async function getUsage() {
  const res = await api.get('/assistant/usage')
  return res.data
}
