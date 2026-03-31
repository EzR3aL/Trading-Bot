import { describe, it, expect, vi, beforeEach } from 'vitest'
import axios from 'axios'

// We need to test the module's configuration, so we mock axios.create
// and verify the interceptors are set up correctly.
vi.mock('axios', () => {
  const responseInterceptors: Array<{
    onFulfilled: (response: unknown) => unknown
    onRejected: (error: unknown) => unknown
  }> = []

  const mockInstance = {
    post: vi.fn(),
    get: vi.fn(),
    interceptors: {
      request: {
        use: vi.fn(),
      },
      response: {
        use: vi.fn((onFulfilled: (r: unknown) => unknown, onRejected: (e: unknown) => unknown) => {
          responseInterceptors.push({ onFulfilled, onRejected })
        }),
      },
    },
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
  })

  it('should create axios instance with correct baseURL and withCredentials', async () => {
    await import('../client')

    expect(axios.create).toHaveBeenCalledWith(expect.objectContaining({
      baseURL: '/api',
      headers: { 'Content-Type': 'application/json' },
      withCredentials: true,
    }))
  })

  it('should register response interceptor (no request interceptor needed for cookie auth)', async () => {
    await import('../client')

    const instance = vi.mocked(axios.create).mock.results[0].value
    // No request interceptor — cookies are sent automatically via withCredentials
    expect(instance.interceptors.response.use).toHaveBeenCalledTimes(1)
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
