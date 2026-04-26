import { describe, it, expect, vi, beforeEach } from 'vitest'
import axios, { AxiosError } from 'axios'

// ---------------------------------------------------------------------------
// Mock axios so no real HTTP calls are made
// ---------------------------------------------------------------------------
vi.mock('axios', async (importOriginal) => {
  const actual = await importOriginal<typeof import('axios')>()

  const mockPost = vi.fn()
  const mockInstance = {
    post: mockPost,
    interceptors: {
      request: { use: vi.fn() },
      response: { use: vi.fn() },
    },
  }

  return {
    ...actual,
    default: {
      ...actual.default,
      create: vi.fn(() => mockInstance),
    },
    // re-export AxiosError so instanceof checks work
    AxiosError: actual.AxiosError,
  }
})

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function getMockPost() {
  const instance = vi.mocked(axios.create).mock.results[0].value as {
    post: ReturnType<typeof vi.fn>
  }
  return instance.post
}

function makeNetworkError(): AxiosError {
  const err = new AxiosError('Network Error')
  // No .response = transient / network error
  err.response = undefined
  return err
}

function makeHttpError(status: number, body: unknown): AxiosError {
  const err = new AxiosError(`Request failed with status code ${status}`)
  err.response = { status, data: body, headers: {}, config: {} as never, statusText: '' }
  return err
}

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const PAYLOAD = {
  action: {
    type: 'approveBuilderFee' as const,
    hyperliquidChain: 'Mainnet' as const,
    maxFeeRate: '0.001%',
    builder: '0xdeadbeef',
    nonce: 1_700_000_000_000,
    signatureChainId: '0x1',
  },
  nonce: 1_700_000_000_000,
  signature: { r: '0xabc', s: '0xdef', v: 27 },
  vaultAddress: null as null,
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('hyperliquid API module', () => {
  beforeEach(() => {
    vi.resetModules()
  })

  it('creates axios instance pointing at api.hyperliquid.xyz', async () => {
    await import('../hyperliquid')

    expect(axios.create).toHaveBeenCalledWith(
      expect.objectContaining({
        baseURL: 'https://api.hyperliquid.xyz',
        headers: { 'Content-Type': 'application/json' },
      }),
    )
  })

  it('calls POST /exchange with the provided payload', async () => {
    const { approveBuilderFee } = await import('../hyperliquid')
    const post = getMockPost()
    post.mockResolvedValueOnce({ data: { status: 'ok' } })

    await approveBuilderFee(PAYLOAD)

    expect(post).toHaveBeenCalledWith('/exchange', PAYLOAD)
  })

  it('returns the response body on success', async () => {
    const { approveBuilderFee } = await import('../hyperliquid')
    const post = getMockPost()
    post.mockResolvedValueOnce({ data: { status: 'ok' } })

    const result = await approveBuilderFee(PAYLOAD)

    expect(result).toEqual({ status: 'ok' })
  })

  it('throws HyperliquidApiError when response body has status "err"', async () => {
    const { approveBuilderFee, HyperliquidApiError } = await import('../hyperliquid')
    const post = getMockPost()
    post.mockResolvedValueOnce({ data: { status: 'err', response: 'Invalid nonce' } })

    await expect(approveBuilderFee(PAYLOAD)).rejects.toBeInstanceOf(HyperliquidApiError)
  })

  it('error message from status "err" body is included', async () => {
    const { approveBuilderFee } = await import('../hyperliquid')
    const post = getMockPost()
    post.mockResolvedValueOnce({ data: { status: 'err', response: 'Invalid nonce' } })

    await expect(approveBuilderFee(PAYLOAD)).rejects.toThrow('Invalid nonce')
  })

  it('retries once on network error then succeeds', async () => {
    const { approveBuilderFee } = await import('../hyperliquid')
    const post = getMockPost()
    post
      .mockRejectedValueOnce(makeNetworkError())
      .mockResolvedValueOnce({ data: { status: 'ok' } })

    const result = await approveBuilderFee(PAYLOAD)
    expect(result.status).toBe('ok')
    expect(post).toHaveBeenCalledTimes(2)
  })

  it('does NOT retry on HTTP 4xx errors', async () => {
    const { approveBuilderFee } = await import('../hyperliquid')
    const post = getMockPost()
    post.mockRejectedValueOnce(makeHttpError(400, { error: 'Bad Request' }))

    await expect(approveBuilderFee(PAYLOAD)).rejects.toBeInstanceOf(AxiosError)
    expect(post).toHaveBeenCalledTimes(1)
  })

  it('does NOT retry on HTTP 5xx errors', async () => {
    const { approveBuilderFee } = await import('../hyperliquid')
    const post = getMockPost()
    post.mockRejectedValueOnce(makeHttpError(500, { error: 'Server Error' }))

    await expect(approveBuilderFee(PAYLOAD)).rejects.toBeInstanceOf(AxiosError)
    expect(post).toHaveBeenCalledTimes(1)
  })

  it('throws after exhausting retries on persistent network error', async () => {
    const { approveBuilderFee } = await import('../hyperliquid')
    const post = getMockPost()
    // Two network errors (initial + 1 retry)
    post
      .mockRejectedValueOnce(makeNetworkError())
      .mockRejectedValueOnce(makeNetworkError())

    await expect(approveBuilderFee(PAYLOAD)).rejects.toBeInstanceOf(AxiosError)
    expect(post).toHaveBeenCalledTimes(2)
  })

  it('exports HL_EXCHANGE_URL constant matching the DEX endpoint', async () => {
    const { HL_EXCHANGE_URL } = await import('../hyperliquid')
    expect(HL_EXCHANGE_URL).toBe('https://api.hyperliquid.xyz/exchange')
  })
})
