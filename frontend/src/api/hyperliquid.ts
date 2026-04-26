/**
 * Dedicated axios instance for the external Hyperliquid DEX public API.
 *
 * This is intentionally separate from `api/client.ts` because:
 *   - Calls go to api.hyperliquid.xyz, not our backend.
 *   - No auth interceptor / token refresh should be applied.
 *   - Retry logic is limited to network/timeout errors only (not 4xx/5xx).
 */
import axios, { AxiosError } from 'axios'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

export const HL_EXCHANGE_URL = 'https://api.hyperliquid.xyz/exchange'

/** Maximum number of safe retries on transient network / timeout errors. */
const MAX_NETWORK_RETRIES = 1

/** Timeout for a single request attempt (ms). */
const REQUEST_TIMEOUT_MS = 15_000

// ---------------------------------------------------------------------------
// Axios instance — no auth interceptors
// ---------------------------------------------------------------------------

const hlClient = axios.create({
  baseURL: 'https://api.hyperliquid.xyz',
  headers: { 'Content-Type': 'application/json' },
  timeout: REQUEST_TIMEOUT_MS,
})

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** EIP-712 signature components extracted from a wallet-signed hex string. */
export interface Eip712Signature {
  r: string
  s: string
  v: number
}

/**
 * Payload sent to the `/exchange` endpoint to approve a builder fee.
 * See Hyperliquid docs: ApproveBuilderFee action.
 */
export interface ApproveBuilderFeePayload {
  action: {
    type: 'approveBuilderFee'
    hyperliquidChain: 'Mainnet' | 'Testnet'
    maxFeeRate: string
    builder: string
    nonce: number
    signatureChainId: string
  }
  nonce: number
  signature: Eip712Signature
  vaultAddress: null
}

/** Successful response body from the Hyperliquid `/exchange` endpoint. */
export interface HyperliquidExchangeResponse {
  status: 'ok' | 'err'
  response?: string
}

/**
 * Typed error thrown when Hyperliquid returns a non-2xx HTTP status or
 * a `{ status: "err" }` response body.
 */
export class HyperliquidApiError extends Error {
  constructor(
    message: string,
    /** Raw response body, if available. */
    public readonly body: unknown = null,
  ) {
    super(message)
    this.name = 'HyperliquidApiError'
  }
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

/**
 * Returns true for errors that are safe to retry: network failures or
 * request timeouts. Explicitly does NOT retry on 4xx/5xx HTTP errors.
 */
function isRetryableError(err: unknown): boolean {
  if (err instanceof AxiosError) {
    // No response at all = network error / timeout
    if (!err.response) return true
    // Do NOT retry on HTTP error responses (4xx / 5xx)
    return false
  }
  return false
}

/**
 * Executes `fn`, retrying once on transient network / timeout errors.
 * Throws immediately on HTTP-level errors (4xx/5xx).
 */
async function withOneRetry<T>(fn: () => Promise<T>): Promise<T> {
  let lastError: unknown
  for (let attempt = 0; attempt <= MAX_NETWORK_RETRIES; attempt++) {
    try {
      return await fn()
    } catch (err) {
      lastError = err
      if (!isRetryableError(err)) throw err
      // Only reached for network/timeout errors — retry once
    }
  }
  throw lastError
}

// ---------------------------------------------------------------------------
// Public API functions
// ---------------------------------------------------------------------------

/**
 * Submits a signed `approveBuilderFee` action to the Hyperliquid exchange
 * endpoint.
 *
 * - Retries once on network / timeout errors.
 * - Throws `HyperliquidApiError` on non-2xx HTTP responses or
 *   `{ status: "err" }` response bodies.
 *
 * @returns The parsed response body on success.
 */
export async function approveBuilderFee(
  payload: ApproveBuilderFeePayload,
): Promise<HyperliquidExchangeResponse> {
  return withOneRetry(async () => {
    const res = await hlClient.post<HyperliquidExchangeResponse>('/exchange', payload)
    const body = res.data

    if (body?.status === 'err') {
      throw new HyperliquidApiError(
        `Hyperliquid: ${body.response ?? 'Unknown error'}`,
        body,
      )
    }

    return body
  })
}

export default hlClient
