import { describe, it, expect, vi, beforeEach } from 'vitest'
import { useAuthStore } from '../authStore'
import type { User } from '../../types'

// Mock the api client module
vi.mock('../../api/client', () => {
  return {
    default: {
      post: vi.fn(),
      get: vi.fn(),
      interceptors: {
        request: { use: vi.fn() },
        response: { use: vi.fn() },
      },
    },
    setTokenExpiry: vi.fn(),
    clearTokenExpiry: vi.fn(),
  }
})

// eslint-disable-next-line @typescript-eslint/no-require-imports
import api from '../../api/client'

const mockUser: User = {
  id: 1,
  username: 'testuser',
  email: 'test@example.com',
  role: 'user',
  language: 'en',
  is_active: true,
}

describe('authStore', () => {
  beforeEach(() => {
    // Reset store state before each test
    useAuthStore.setState({
      user: null,
      isAuthenticated: false,
      isLoading: false,
    })
    vi.clearAllMocks()
  })

  it('should have correct initial state', () => {
    const state = useAuthStore.getState()
    expect(state.user).toBeNull()
    expect(state.isAuthenticated).toBe(false)
    expect(state.isLoading).toBe(false)
  })

  describe('login', () => {
    it('should login successfully and set authenticated state', async () => {
      const mockPost = vi.mocked(api.post)
      const mockGet = vi.mocked(api.get)

      mockPost.mockResolvedValueOnce({
        data: {
          access_token: 'eyJhbGciOiJIUzI1NiJ9.eyJleHAiOjk5OTk5OTk5OTl9.stub',
        },
      })
      mockGet.mockResolvedValueOnce({ data: mockUser })

      await useAuthStore.getState().login('testuser', 'password123')

      expect(mockPost).toHaveBeenCalledWith('/auth/login', {
        username: 'testuser',
        password: 'password123',
      })
      expect(mockGet).toHaveBeenCalledWith('/auth/me')

      // Token is now in httpOnly cookie, not localStorage
      const state = useAuthStore.getState()
      expect(state.user).toEqual(mockUser)
      expect(state.isAuthenticated).toBe(true)
      expect(state.isLoading).toBe(false)
    })

    it('should set isLoading during login', async () => {
      const mockPost = vi.mocked(api.post)
      const mockGet = vi.mocked(api.get)

      let resolvePost: (value: unknown) => void
      mockPost.mockReturnValue(
        new Promise((resolve) => {
          resolvePost = resolve
        })
      )
      mockGet.mockResolvedValueOnce({ data: mockUser })

      const loginPromise = useAuthStore.getState().login('testuser', 'pass')
      expect(useAuthStore.getState().isLoading).toBe(true)

      resolvePost!({
        data: {
          access_token: 'token',
        },
      })
      await loginPromise

      expect(useAuthStore.getState().isLoading).toBe(false)
    })

    it('should reset isLoading and throw on login failure', async () => {
      const mockPost = vi.mocked(api.post)
      mockPost.mockRejectedValueOnce(new Error('Invalid credentials'))

      await expect(
        useAuthStore.getState().login('bad', 'bad')
      ).rejects.toThrow('Invalid credentials')

      const state = useAuthStore.getState()
      expect(state.isLoading).toBe(false)
      expect(state.isAuthenticated).toBe(false)
      expect(state.user).toBeNull()
    })
  })

  describe('logout', () => {
    it('should call logout API, clear token expiry, and reset state', async () => {
      const mockPost = vi.mocked(api.post)
      mockPost.mockResolvedValueOnce({ data: { message: 'Logged out' } })

      useAuthStore.setState({
        user: mockUser,
        isAuthenticated: true,
      })

      await useAuthStore.getState().logout()

      expect(mockPost).toHaveBeenCalledWith('/auth/logout')
      // Cookie is cleared server-side; client clears token expiry
      const { clearTokenExpiry } = await import('../../api/client')
      expect(clearTokenExpiry).toHaveBeenCalled()

      const state = useAuthStore.getState()
      expect(state.user).toBeNull()
      expect(state.isAuthenticated).toBe(false)
    })

    it('should clear state even if logout API fails', async () => {
      const mockPost = vi.mocked(api.post)
      mockPost.mockRejectedValueOnce(new Error('Network error'))

      useAuthStore.setState({
        user: mockUser,
        isAuthenticated: true,
      })

      await useAuthStore.getState().logout()

      const state = useAuthStore.getState()
      expect(state.user).toBeNull()
      expect(state.isAuthenticated).toBe(false)
    })
  })

  describe('fetchUser', () => {
    it('should fetch and set user data', async () => {
      const mockGet = vi.mocked(api.get)
      mockGet.mockResolvedValueOnce({ data: mockUser })

      await useAuthStore.getState().fetchUser()

      const state = useAuthStore.getState()
      expect(state.user).toEqual(mockUser)
      expect(state.isAuthenticated).toBe(true)
      expect(mockGet).toHaveBeenCalledWith('/auth/me')
    })

    it('should reset state on fetch failure', async () => {
      useAuthStore.setState({
        user: mockUser,
        isAuthenticated: true,
      })

      const mockGet = vi.mocked(api.get)
      mockGet.mockRejectedValueOnce(new Error('Unauthorized'))

      await useAuthStore.getState().fetchUser()

      const state = useAuthStore.getState()
      expect(state.user).toBeNull()
      expect(state.isAuthenticated).toBe(false)
    })
  })
})
