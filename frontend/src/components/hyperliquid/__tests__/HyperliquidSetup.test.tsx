import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import HyperliquidSetup from '../HyperliquidSetup'

// --------------------------------------------------------------------------
// Mocks
// --------------------------------------------------------------------------

// i18n: passthrough with defaultValue/opts.seconds interpolation support.
const mockT = (key: string, defaultOrOpts?: unknown, maybeOpts?: unknown) => {
  let defaultValue: string | undefined
  let opts: Record<string, unknown> | undefined

  if (typeof defaultOrOpts === 'string') {
    defaultValue = defaultOrOpts
    opts = maybeOpts as Record<string, unknown> | undefined
  } else if (defaultOrOpts && typeof defaultOrOpts === 'object') {
    opts = defaultOrOpts as Record<string, unknown>
    if (typeof opts.defaultValue === 'string') defaultValue = opts.defaultValue
  }

  let out = defaultValue ?? key
  if (opts) {
    for (const [k, v] of Object.entries(opts)) {
      out = out.replace(new RegExp(`{{\\s*${k}\\s*}}`, 'g'), String(v))
    }
  }
  return out
}

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: mockT }),
}))

// wagmi / rainbowkit: simulate a connected wallet with a signTypedData stub.
const mockSignTypedData = vi.fn()
const TEST_ADDRESS = '0x1234567890abcdef1234567890abcdef12345678'

vi.mock('wagmi', () => ({
  WagmiProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  useAccount: () => ({ address: TEST_ADDRESS, isConnected: true }),
  useChainId: () => 42161,
  useWalletClient: () => ({
    data: {
      account: { address: TEST_ADDRESS },
      signTypedData: (...args: unknown[]) => mockSignTypedData(...args),
    },
  }),
}))

vi.mock('@rainbow-me/rainbowkit', () => ({
  RainbowKitProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  ConnectButton: Object.assign(() => <button>Connect</button>, {
    Custom: ({
      children,
    }: {
      children: (p: { openAccountModal: () => void }) => React.ReactNode
    }) => <>{children({ openAccountModal: () => {} })}</>,
  }),
  darkTheme: () => ({}),
}))

vi.mock('@rainbow-me/rainbowkit/styles.css', () => ({}))

vi.mock('../../../config/wallet', () => ({
  walletConfig: {},
}))

vi.mock('../../../api/hyperliquid', () => ({
  approveBuilderFee: (...args: unknown[]) => mockApproveBuilderFee(...args),
}))

// API client: mock get and post.
const mockGet = vi.fn()
const mockPost = vi.fn()

vi.mock('../../../api/client', () => ({
  default: {
    get: (...args: unknown[]) => mockGet(...args),
    post: (...args: unknown[]) => mockPost(...args),
  },
}))

// Hyperliquid DEX client: mock approveBuilderFee so no real HTTP calls are made.
const mockApproveBuilderFee = vi.fn()

// --------------------------------------------------------------------------
// Fixtures
// --------------------------------------------------------------------------

const BUILDER_CONFIG_PENDING = {
  builder_configured: true,
  builder_address: '0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
  builder_fee: 10,
  max_fee_rate: '0.001%',
  chain_id: 42161,
  has_hl_connection: true,
  builder_fee_approved: false,
  needs_approval: true,
  referral_code: '',
  referral_required: false,
  referral_verified: true,
  needs_referral: false,
}

// A valid-looking 65-byte hex signature so the r/s/v slicing doesn't explode.
const FAKE_SIG = '0x' + '11'.repeat(32) + '22'.repeat(32) + '1b'

// --------------------------------------------------------------------------
// Tests
// --------------------------------------------------------------------------

describe('HyperliquidSetup — bounded polling for on-chain confirmation', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockGet.mockResolvedValue({ data: BUILDER_CONFIG_PENDING })
    mockSignTypedData.mockResolvedValue(FAKE_SIG)
    // approveBuilderFee resolves successfully by default
    mockApproveBuilderFee.mockResolvedValue({ status: 'ok' })

    // Ensure visibilityState defaults to visible for each test.
    Object.defineProperty(document, 'visibilityState', {
      value: 'visible',
      configurable: true,
    })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('completes happy path once poll returns success', async () => {
    // First 2 confirm calls fail (approval not yet on-chain), third succeeds.
    let confirmCalls = 0
    mockPost.mockImplementation((url: string) => {
      if (url.includes('confirm-builder-approval')) {
        confirmCalls += 1
        if (confirmCalls < 3) {
          return Promise.reject({ response: { data: { detail: 'not yet' } }, isAxiosError: true })
        }
        return Promise.resolve({ data: { approved_max_fee: 10 } })
      }
      return Promise.resolve({ data: {} })
    })

    const user = userEvent.setup({ advanceTimers: (ms) => vi.advanceTimersByTime(ms) })
    vi.useFakeTimers({ shouldAdvanceTime: true })

    render(<HyperliquidSetup />)

    // Approve button appears once config is loaded
    const approveBtn = await screen.findByRole('button', { name: /builderFee\.approve/ })
    await user.click(approveBtn)

    // Advance real time to step through the poll loop (3x 1s poll intervals)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3500)
    })

    await waitFor(() => {
      expect(confirmCalls).toBe(3)
    })
  })

  it('shows elapsed-time status indicator while polling', async () => {
    // All confirm calls fail so we stay in the polling state.
    mockPost.mockImplementation((url: string) => {
      if (url.includes('confirm-builder-approval')) {
        return Promise.reject({ response: { data: { detail: 'not yet' } } })
      }
      return Promise.resolve({ data: {} })
    })

    const user = userEvent.setup({ advanceTimers: (ms) => vi.advanceTimersByTime(ms) })
    vi.useFakeTimers({ shouldAdvanceTime: true })

    render(<HyperliquidSetup />)

    const approveBtn = await screen.findByRole('button', { name: /builderFee\.approve/ })
    await user.click(approveBtn)

    // After a couple of poll intervals, the button should display the elapsed
    // seconds from the polling i18n key.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2500)
    })

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Checking on-chain status/i })).toBeInTheDocument()
    })
  })

  it('surfaces a clear error when the poll times out', async () => {
    // Every confirm call fails → loop hits MAX_POLL_MS and throws.
    mockPost.mockImplementation((url: string) => {
      if (url.includes('confirm-builder-approval')) {
        return Promise.reject({ response: { data: { detail: 'pending' } } })
      }
      return Promise.resolve({ data: {} })
    })

    const user = userEvent.setup({ advanceTimers: (ms) => vi.advanceTimersByTime(ms) })
    vi.useFakeTimers({ shouldAdvanceTime: true })

    render(<HyperliquidSetup />)

    const approveBtn = await screen.findByRole('button', { name: /builderFee\.approve/ })
    await user.click(approveBtn)

    // Fast-forward past MAX_POLL_MS (30s) plus a buffer.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(31_000)
    })

    // We expect either the backend detail ("pending") or the i18n fallback to
    // be rendered in the red error banner.
    await waitFor(() => {
      const matches = screen.queryAllByText(/pending|Approval did not land on-chain/i)
      expect(matches.length).toBeGreaterThan(0)
    })
  })

  it('skips the server call while the tab is hidden', async () => {
    Object.defineProperty(document, 'visibilityState', {
      value: 'hidden',
      configurable: true,
    })

    let confirmCalls = 0
    mockPost.mockImplementation((url: string) => {
      if (url.includes('confirm-builder-approval')) {
        confirmCalls += 1
        return Promise.reject({ response: { data: { detail: 'not yet' } } })
      }
      return Promise.resolve({ data: {} })
    })

    const user = userEvent.setup({ advanceTimers: (ms) => vi.advanceTimersByTime(ms) })
    vi.useFakeTimers({ shouldAdvanceTime: true })

    render(<HyperliquidSetup />)

    const approveBtn = await screen.findByRole('button', { name: /builderFee\.approve/ })
    await user.click(approveBtn)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000)
    })

    // Tab is hidden → confirm endpoint MUST NOT be hit.
    expect(confirmCalls).toBe(0)
  })
})
