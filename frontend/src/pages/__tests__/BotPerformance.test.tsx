import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import BotPerformance from '../BotPerformance'

// Mock recharts to avoid SVG rendering issues in jsdom
vi.mock('recharts', () => ({
  ResponsiveContainer: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  ComposedChart: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  AreaChart: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  Bar: () => <div />,
  Line: () => <div />,
  Area: () => <div />,
  Cell: () => <div />,
  XAxis: () => <div />,
  YAxis: () => <div />,
  CartesianGrid: () => <div />,
  Tooltip: () => <div />,
  ReferenceLine: () => <div />,
}))

// Mock html-to-image
vi.mock('html-to-image', () => ({
  toBlob: vi.fn(),
}))

// Mock React Query hooks
vi.mock('../../api/queries', () => ({
  useBotComparePerformance: vi.fn(),
  useBotStatistics: vi.fn(),
  useAffiliateLinks: vi.fn(),
}))

// Mock i18n – return the key as text
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: string) => fallback ?? key,
    i18n: { language: 'en' },
  }),
}))

import { useBotComparePerformance, useBotStatistics, useAffiliateLinks } from '../../api/queries'

const mockCompare = useBotComparePerformance as ReturnType<typeof vi.fn>
const mockStats = useBotStatistics as ReturnType<typeof vi.fn>
const mockAffiliate = useAffiliateLinks as ReturnType<typeof vi.fn>

function createQueryClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } })
}

function renderWithProviders(ui: React.ReactElement) {
  return render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  )
}

// Default return values
function setDefaultMocks(overrides?: {
  compare?: Partial<ReturnType<typeof useBotComparePerformance>>
  stats?: Partial<ReturnType<typeof useBotStatistics>>
  affiliate?: Partial<ReturnType<typeof useAffiliateLinks>>
}) {
  mockCompare.mockReturnValue({
    data: undefined,
    isLoading: false,
    error: null,
    ...overrides?.compare,
  })
  mockStats.mockReturnValue({
    data: undefined,
    isLoading: false,
    error: null,
    ...overrides?.stats,
  })
  mockAffiliate.mockReturnValue({
    data: [],
    isLoading: false,
    error: null,
    ...overrides?.affiliate,
  })
}

describe('BotPerformance', () => {
  beforeEach(() => {
    setDefaultMocks()
  })

  it('renders the page title', () => {
    renderWithProviders(<BotPerformance />)
    expect(screen.getByText('performance.title')).toBeInTheDocument()
  })

  it('renders loading state when data is loading', () => {
    setDefaultMocks({ compare: { isLoading: true, data: undefined } })
    renderWithProviders(<BotPerformance />)
    // Loading skeleton should be present – no "noData" text
    expect(screen.queryByText('performance.noData')).not.toBeInTheDocument()
  })

  it('shows empty state when no bots are returned', () => {
    setDefaultMocks({ compare: { data: [], isLoading: false } })
    renderWithProviders(<BotPerformance />)
    expect(screen.getByText('performance.noData')).toBeInTheDocument()
  })

  it('shows error state when compare query fails', () => {
    setDefaultMocks({ compare: { error: new Error('fetch failed'), data: undefined } })
    renderWithProviders(<BotPerformance />)
    expect(screen.getByRole('alert')).toBeInTheDocument()
    expect(screen.getByText('performance.loadError')).toBeInTheDocument()
  })

  it('renders bot cards when data is loaded', () => {
    const bots = [
      {
        bot_id: 1,
        name: 'BTC Edge',
        strategy_type: 'edge_indicator',
        exchange_type: 'bitget',
        mode: 'live',
        total_trades: 42,
        total_pnl: 123.45,
        total_fees: 5.0,
        total_funding: 1.0,
        win_rate: 65.0,
        wins: 27,
        last_direction: 'long',
        last_confidence: 0.85,
        series: [
          { date: '2026-04-01', cumulative_pnl: 0 },
          { date: '2026-04-02', cumulative_pnl: 50 },
        ],
      },
    ]
    setDefaultMocks({ compare: { data: bots, isLoading: false } })
    renderWithProviders(<BotPerformance />)

    expect(screen.getByText('BTC Edge')).toBeInTheDocument()
  })

  it('does not mount the hidden mobile share-capture div until a share is initiated', () => {
    // Stats data with closed trades present. Before any share action is
    // triggered, the hidden capture div (testid: mobile-share-capture) must
    // not be in the DOM — this is the core of UX-M2: avoid re-rendering
    // the hidden share subtree on every parent state change.
    const bots = [
      {
        bot_id: 1,
        name: 'BTC Edge',
        strategy_type: 'edge_indicator',
        exchange_type: 'bitget',
        mode: 'live',
        total_trades: 2,
        total_pnl: 10,
        total_fees: 0,
        total_funding: 0,
        win_rate: 50,
        wins: 1,
        last_direction: 'long',
        last_confidence: 0.8,
        series: [{ date: '2026-04-01', cumulative_pnl: 0 }],
      },
    ]
    const stats = {
      bot_id: 1,
      summary: {
        win_rate: 50,
        avg_trade: 5,
        best_trade: 20,
        worst_trade: -10,
        days: 30,
      },
      recent_trades: [
        {
          id: 101,
          symbol: 'BTCUSDT',
          side: 'long',
          entry_price: 50000,
          exit_price: 51000,
          entry_time: '2026-04-10T12:00:00Z',
          exit_time: '2026-04-10T13:00:00Z',
          pnl: 20,
          pnl_percent: 2.0,
          fees: 1,
          funding_paid: 0,
          status: 'closed',
          demo_mode: false,
          size: 0.01,
          leverage: 5,
          exit_reason: 'take_profit',
          reason: 'ema crossover',
        },
      ],
      daily_series: [],
    }
    setDefaultMocks({
      compare: { data: bots, isLoading: false },
      stats: { data: stats, isLoading: false },
    })
    renderWithProviders(<BotPerformance />)

    // Hidden capture div must NOT be mounted before any share interaction.
    expect(screen.queryByTestId('mobile-share-capture')).not.toBeInTheDocument()
  })

  // Regression guard for #332 — the "copied" flag-reset timer in the share
  // handler used to leak across unmount, firing setFlag(false) against a
  // stale component. After the fix, unmount + runAllTimers must be silent.
  it('unmounts cleanly with fake timers and without stale state updates (#332)', () => {
    vi.useFakeTimers()
    try {
      const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
      const { unmount } = renderWithProviders(<BotPerformance />)
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
