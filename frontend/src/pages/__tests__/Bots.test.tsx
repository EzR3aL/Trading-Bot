import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import Bots from '../Bots'

// Stable t function to prevent useEffect re-firing
const mockT = (key: string) => {
  const translations: Record<string, string> = {
    'bots.title': 'Bots',
    'bots.newBot': 'New Bot',
    'bots.noBots': 'No bots yet',
    'bots.noBotsHint': 'Create your first bot to get started',
    'bots.noBotsAction': 'Create Bot',
    'bots.start': 'Started',
    'bots.stop': 'Stopped',
    'bots.failedStart': 'Failed to start',
    'bots.stopAll': 'Stop All',
    'common.error': 'An error occurred',
    'common.back': 'Back',
    'common.cancel': 'Cancel',
  }
  return translations[key] || key
}

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: mockT }),
}))

// Mock React Query hooks from queries module
const mockUseBots = vi.fn()
const mockMutate = vi.fn()
const mockMutation = () => ({
  mutate: mockMutate,
  mutateAsync: vi.fn(),
  isLoading: false,
  isPending: false,
})

vi.mock('../../api/queries', () => ({
  useBots: (...args: unknown[]) => mockUseBots(...args),
  useStartBot: () => mockMutation(),
  useStopBot: () => mockMutation(),
  useDeleteBot: () => mockMutation(),
  useDuplicateBot: () => mockMutation(),
  useStopAllBots: () => mockMutation(),
  useClosePosition: () => mockMutation(),
  queryKeys: {
    bots: { all: ['bots'] },
  },
}))

vi.mock('../../api/client', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
    interceptors: {
      request: { use: vi.fn() },
      response: { use: vi.fn() },
    },
  },
  setTokenExpiry: vi.fn(),
  clearTokenExpiry: vi.fn(),
}))

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return { ...actual, useNavigate: () => vi.fn() }
})

// Mock heavy components and hooks to keep tests fast
vi.mock('../../components/bots/BotBuilder', () => ({
  default: () => <div data-testid="bot-builder">BotBuilder</div>,
}))
vi.mock('../../components/ui/ExchangeLogo', () => ({
  ExchangeIcon: ({ exchange }: { exchange: string }) => <span>{exchange}</span>,
}))
vi.mock('../../components/ui/Skeleton', () => ({
  SkeletonBotCard: () => <div data-testid="skeleton-bot-card" />,
}))
vi.mock('../../components/ui/PnlCell', () => ({
  default: () => <span>pnl</span>,
}))
vi.mock('../../components/ui/ExitReasonBadge', () => ({
  default: () => <span />,
}))
vi.mock('../../components/ui/ConfirmModal', () => ({
  default: () => null,
}))
vi.mock('../../components/ui/GuidedTour', () => ({
  default: () => null,
  TourHelpButton: () => null,
}))
vi.mock('../../components/ui/MobileTradeCard', () => ({
  default: () => null,
}))
vi.mock('../../components/ui/SizeValue', () => ({
  default: ({ children }: any) => <span>{children}</span>,
}))
vi.mock('../../components/ui/PullToRefreshIndicator', () => ({
  default: () => null,
}))
vi.mock('html-to-image', () => ({
  toBlob: vi.fn(),
}))
vi.mock('../../hooks/useIsMobile', () => ({
  default: () => false,
}))
vi.mock('../../hooks/useHaptic', () => ({
  default: () => ({ light: vi.fn(), medium: vi.fn(), heavy: vi.fn(), error: vi.fn() }),
}))
vi.mock('../../hooks/useSwipeToClose', () => ({
  default: () => ({ ref: { current: null }, style: {} }),
}))
vi.mock('../../hooks/usePullToRefresh', () => ({
  default: () => ({ containerRef: { current: null }, refreshing: false, pullDistance: 0 }),
}))
vi.mock('../../stores/authStore', () => ({
  useAuthStore: (selector?: (s: any) => any) => {
    const state = { user: { role: 'user' } }
    return selector ? selector(state) : state
  },
}))

const mockBots = [
  {
    bot_config_id: 1,
    name: 'BTC Edge',
    strategy_type: 'edge_indicator',
    exchange_type: 'bitget',
    mode: 'demo',
    trading_pairs: ['BTCUSDT'],
    status: 'running',
    error_message: null,
    started_at: '2026-01-01T00:00:00Z',
    last_analysis: null,
    trades_today: 2,
    is_enabled: true,
    total_trades: 50,
    total_pnl: 123.45,
    total_fees: 5.0,
    total_funding: 1.0,
    open_trades: 1,
  },
  {
    bot_config_id: 2,
    name: 'ETH Edge',
    strategy_type: 'edge_indicator',
    exchange_type: 'bitget',
    mode: 'demo',
    trading_pairs: ['ETHUSDT'],
    status: 'stopped',
    error_message: null,
    started_at: null,
    last_analysis: null,
    trades_today: 0,
    is_enabled: false,
    total_trades: 10,
    total_pnl: -5.0,
    total_fees: 2.0,
    total_funding: 0.5,
    open_trades: 0,
  },
]

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  )
}

describe('Bots Page', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('should render bot list when API returns data', async () => {
    mockUseBots.mockReturnValue({
      data: { bots: mockBots },
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    })

    render(<Bots />, { wrapper: createWrapper() })

    await waitFor(() => {
      expect(screen.getByText('BTC Edge')).toBeInTheDocument()
      expect(screen.getByText('ETH Edge')).toBeInTheDocument()
    })
  })

  it('should show empty state when no bots', async () => {
    mockUseBots.mockReturnValue({
      data: { bots: [] },
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    })

    render(<Bots />, { wrapper: createWrapper() })

    await waitFor(() => {
      expect(screen.getByText('No bots yet')).toBeInTheDocument()
      expect(screen.getByText('Create your first bot to get started')).toBeInTheDocument()
    })
  })

  it('should show loading skeletons during fetch', () => {
    mockUseBots.mockReturnValue({
      data: null,
      isLoading: true,
      error: null,
      refetch: vi.fn(),
    })

    render(<Bots />, { wrapper: createWrapper() })

    const skeletons = screen.getAllByTestId('skeleton-bot-card')
    expect(skeletons.length).toBe(3)
  })

  it('should show error state when query fails', async () => {
    mockUseBots.mockReturnValue({
      data: null,
      isLoading: false,
      error: new Error('Network error'),
      refetch: vi.fn(),
    })

    render(<Bots />, { wrapper: createWrapper() })

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('An error occurred')
    })
  })

  it('should render the page title', async () => {
    mockUseBots.mockReturnValue({
      data: { bots: [] },
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    })

    render(<Bots />, { wrapper: createWrapper() })

    await waitFor(() => {
      expect(screen.getByText('Bots')).toBeInTheDocument()
    })
  })

  // Regression guard for #332 — the "copied" flag-reset timer in TradeDetailModal
  // (Bots.tsx) used to leak across unmount, firing setCopied(false) against a
  // stale component. After the fix, unmount + runAllTimers must be silent.
  it('unmounts cleanly with fake timers and without stale state updates (#332)', async () => {
    vi.useFakeTimers()
    try {
      mockUseBots.mockReturnValue({
        data: { bots: [] },
        isLoading: false,
        error: null,
        refetch: vi.fn(),
      })

      const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
      const { unmount } = render(<Bots />, { wrapper: createWrapper() })
      unmount()
      vi.runAllTimers()

      const stateAfterUnmountWarnings = errorSpy.mock.calls.filter((args) =>
        typeof args[0] === 'string' && args[0].includes("can't perform a React state update on an unmounted"),
      )
      expect(stateAfterUnmountWarnings).toHaveLength(0)
      errorSpy.mockRestore()
    } finally {
      vi.useRealTimers()
    }
  })
})
