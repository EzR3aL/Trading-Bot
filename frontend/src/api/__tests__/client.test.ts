import { describe, it, expect, vi, beforeEach } from 'vitest'
import axios from 'axios'

// We need to test the module's configuration, so we mock axios.create
// and verify the interceptors are set up correctly.
vi.mock('axios', () => {
  const requestInterceptors: Array<(config: Record<string, unknown>) => Record<string, unknown>> = []
  const responseInterceptors: Array<{
    onFulfilled: (response: unknown) => unknown
    onRejected: (error: unknown) => unknown
  }> = []

  const mockInstance = {
    post: vi.fn(),
    get: vi.fn(),
    interceptors: {
      request: {
        use: vi.fn((fn: (config: Record<string, unknown>) => Record<string, unknown>) => {
          requestInterceptors.push(fn)
        }),
      },
      response: {
        use: vi.fn((onFulfilled: (r: unknown) => unknown, onRejected: (e: unknown) => unknown) => {
          responseInterceptors.push({ onFulfilled, onRejected })
        }),
      },
    },
    _requestInterceptors: requestInterceptors,
    _responseInterceptors: responseInterceptors,
  }

  return {
    default: {
      create: vi.fn(() => mockInstance),
      post: vi.fn(),
    },
  }
})

describe('API Client Configuration', () => {
  beforeEach(() => {
    vi.resetModules()
    localStorage.clear()
  })

  it('should create axios instance with correct baseURL', async () => {
    await import('../client')

    expect(axios.create).toHaveBeenCalledWith({
      baseURL: '/api',
      headers: { 'Content-Type': 'application/json' },
    })
  })

  it('should register request and response interceptors', async () => {
    await import('../client')

    const instance = vi.mocked(axios.create).mock.results[0].value
    expect(instance.interceptors.request.use).toHaveBeenCalledTimes(1)
    expect(instance.interceptors.response.use).toHaveBeenCalledTimes(1)
  })

  describe('request interceptor', () => {
    it('should attach Authorization header when token exists', async () => {
      localStorage.setItem('access_token', 'test-jwt-token')
      await import('../client')

      const instance = vi.mocked(axios.create).mock.results[0].value
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const requestInterceptor = (instance as any)._requestInterceptors[0]

      const config = { headers: {} as Record<string, string> }
      const result = requestInterceptor(config)

      expect(result.headers.Authorization).toBe('Bearer test-jwt-token')
    })

    it('should not attach Authorization header when no token', async () => {
      await import('../client')

      const instance = vi.mocked(axios.create).mock.results[0].value
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const requestInterceptor = (instance as any)._requestInterceptors[0]

      const config = { headers: {} as Record<string, string> }
      const result = requestInterceptor(config)

      expect(result.headers.Authorization).toBeUndefined()
    })
  })

  describe('response interceptor', () => {
    it('should pass through successful responses', async () => {
      await import('../client')

      const instance = vi.mocked(axios.create).mock.results[0].value
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const responseInterceptor = (instance as any)._responseInterceptors[0]

      const mockResponse = { data: { message: 'ok' }, status: 200 }
      const result = responseInterceptor.onFulfilled(mockResponse)

      expect(result).toEqual(mockResponse)
    })

    it('should reject non-401 errors normally', async () => {
      await import('../client')

      const instance = vi.mocked(axios.create).mock.results[0].value
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const responseInterceptor = (instance as any)._responseInterceptors[0]

      const mockError = {
        config: {},
        response: { status: 500 },
      }

      await expect(responseInterceptor.onRejected(mockError)).rejects.toEqual(mockError)
    })
  })
})
