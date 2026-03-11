import { create } from 'zustand'
import api from '../api/client'
import type { User } from '../types'

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
  logout: () => void
  fetchUser: () => Promise<void>
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  isAuthenticated: !!localStorage.getItem('access_token'),
  isLoading: false,

  login: async (username: string, password: string) => {
    set({ isLoading: true })
    try {
      const res = await api.post('/auth/login', { username, password })
      const { access_token, refresh_token, requires_2fa, temp_token } = res.data

      if (requires_2fa) {
        set({ isLoading: false })
        return { requires2fa: true, tempToken: temp_token }
      }

      localStorage.setItem('access_token', access_token)
      localStorage.setItem('refresh_token', refresh_token)

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
      const { access_token, refresh_token } = res.data
      localStorage.setItem('access_token', access_token)
      localStorage.setItem('refresh_token', refresh_token)

      // Fetch user profile
      const userRes = await api.get('/auth/me')
      set({ user: userRes.data, isAuthenticated: true, isLoading: false })
    } catch (error) {
      set({ isLoading: false })
      throw error
    }
  },

  logout: () => {
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
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
