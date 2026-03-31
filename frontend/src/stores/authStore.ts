import { create } from 'zustand'
import api from '../api/client'
import { clearTokenExpiry, setTokenExpiry } from '../api/client'
import type { User } from '../types'

/** Default access token lifetime in seconds (must match backend ACCESS_TOKEN_EXPIRE_MINUTES). */
const DEFAULT_TOKEN_LIFETIME_S = 240 * 60

interface LoginResult {
  requires2fa: boolean
  tempToken?: string
}

interface AuthState {
  user: User | null
  isAuthenticated: boolean
  isLoading: boolean
  login: (username: string, password: string) => Promise<LoginResult>
  verify2fa: (tempToken: string, code: string) => Promise<void>
  exchangeAuthCode: (code: string) => Promise<void>
  logout: () => Promise<void>
  fetchUser: () => Promise<void>
}

/**
 * Extract token expiry (seconds from now) from a JWT access_token string.
 * Falls back to the default lifetime if parsing fails.
 */
function extractExpirySeconds(accessToken: string): number {
  try {
    const payload = JSON.parse(atob(accessToken.split('.')[1]))
    if (payload.exp) {
      const remaining = payload.exp - Math.floor(Date.now() / 1000)
      return remaining > 0 ? remaining : DEFAULT_TOKEN_LIFETIME_S
    }
  } catch {
    // Fall through
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
      const { access_token, requires_2fa, temp_token } = res.data

      if (requires_2fa) {
        set({ isLoading: false })
        return { requires2fa: true, tempToken: temp_token }
      }

      // Access token is now stored as httpOnly cookie by the backend.
      // Track expiry for proactive refresh scheduling.
      setTokenExpiry(extractExpirySeconds(access_token))

      // Fetch user profile
      const userRes = await api.get('/auth/me')
      set({ user: userRes.data, isAuthenticated: true, isLoading: false })
      return { requires2fa: false }
    } catch (error) {
      set({ isLoading: false })
      throw error
    }
  },

  verify2fa: async (tempToken: string, code: string) => {
    set({ isLoading: true })
    try {
      const res = await api.post('/auth/2fa/verify-login', {
        temp_token: tempToken,
        code,
      })
      const { access_token } = res.data

      setTokenExpiry(extractExpirySeconds(access_token))

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
      const { access_token, user } = res.data

      setTokenExpiry(extractExpirySeconds(access_token))

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
