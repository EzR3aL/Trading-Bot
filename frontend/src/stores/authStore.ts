import { create } from 'zustand'
import api from '../api/client'
import { clearTokenExpiry, setTokenExpiry } from '../api/client'
import type { User } from '../types'

/** Default access token lifetime in seconds (must match backend ACCESS_TOKEN_EXPIRE_MINUTES). */
const DEFAULT_TOKEN_LIFETIME_S = 240 * 60  // 4 hours

interface AuthState {
  user: User | null
  isAuthenticated: boolean
  isLoading: boolean
  login: (username: string, password: string) => Promise<void>
  exchangeAuthCode: (code: string) => Promise<void>
  logout: () => Promise<void>
  fetchUser: () => Promise<void>
}

/**
 * Resolve access-token lifetime in seconds.
 *
 * The backend no longer returns the access token in the response body (SEC-012);
 * it is delivered only via the httpOnly cookie. We rely on `expires_in` from the
 * response body, falling back to legacy JWT decoding for the dual-validate window,
 * then to the default lifetime.
 */
function resolveExpirySeconds(data: { expires_in?: number; access_token?: string | null }): number {
  if (typeof data.expires_in === 'number' && data.expires_in > 0) {
    return data.expires_in
  }
  if (data.access_token) {
    try {
      const payload = JSON.parse(atob(data.access_token.split('.')[1]))
      if (payload.exp) {
        const remaining = payload.exp - Math.floor(Date.now() / 1000)
        if (remaining > 0) return remaining
      }
    } catch {
      // Fall through
    }
  }
  return DEFAULT_TOKEN_LIFETIME_S
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  // Start unauthenticated; call fetchUser() on app mount to check cookie-based session
  isAuthenticated: false,
  isLoading: false,

  login: async (username: string, password: string) => {
    set({ isLoading: true })
    try {
      const res = await api.post('/auth/login', { username, password })

      // Access token lives only in the httpOnly cookie (SEC-012). Track expiry
      // from `expires_in` for proactive refresh scheduling.
      setTokenExpiry(resolveExpirySeconds(res.data))

      // Fetch user profile
      const userRes = await api.get('/auth/me')
      set({ user: userRes.data, isAuthenticated: true, isLoading: false })
    } catch (error) {
      set({ isLoading: false })
      throw error
    }
  },

  exchangeAuthCode: async (code: string) => {
    set({ isLoading: true })
    try {
      const res = await api.post('/auth/bridge/exchange', { code })
      const { user } = res.data

      setTokenExpiry(resolveExpirySeconds(res.data))

      set({ user, isAuthenticated: true, isLoading: false })
    } catch (error) {
      set({ isLoading: false })
      throw error
    }
  },

  logout: async () => {
    try {
      await api.post('/auth/logout')
    } catch {
      // Best-effort — clear local state regardless
    }
    clearTokenExpiry()
    set({ user: null, isAuthenticated: false })
  },

  fetchUser: async () => {
    try {
      const res = await api.get('/auth/me')
      set({ user: res.data, isAuthenticated: true })
    } catch {
      set({ user: null, isAuthenticated: false })
    }
  },
}))
