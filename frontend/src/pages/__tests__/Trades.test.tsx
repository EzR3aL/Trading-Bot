import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import Trades from '../Trades'

const mockT = (key: string) => {
  const translations: Record<string, string> = {
    'trades.title': 'Trades',
    'trades.allStatuses': 'All Statuses',
    'trades.open': 'Open',
    'trades.closed': 'Closed',
    'trades.cancelled': 'Cancelled',
    'trades.status': 'Status',
    'trades.symbol': 'Symbol',
    'trades.exchange': 'Exchange',
    'trades.bot': 'Bot',
    'trades.allExchanges': 'All Exchanges',
    'trades.allBots': 'All Bots',
    'trades.dateFrom': 'From',
    'trades.dateTo': 'To',
    'trades.reset': 'Reset',
    'trades.noTradesTitle': 'No trades found',
    'trades.noTradesHint': 'Trades will appear here once your bots execute them',
    'common.error': 'An error occurred',
    'common.loadError': 'Failed to load data',
  }
  return translations[key] || key
}

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: mockT }),
}))

// Mock React Query hooks
const mockUseTrades = vi.fn()
const mockUseSyncTrades = vi.fn()

vi.mock('../../api/queries', () => ({
  useTrades: (...args: unknown[]) => mockUseTrades(...args),
  useSyncTrades: () => mockUseSyncTrades(),
  queryKeys: {
    trades: { all: ['trades'] },
  },
}))

vi.mock('../../api/client', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
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

vi.mock('../../components/ui/ExchangeLogo', () => ({
  ExchangeIcon: ({ exchange }: { exchange: string }) => <span>{exchange}</span>,
}))
vi.mock('../../components/ui/Skeleton', () => ({
  SkeletonTable: () => <div data-testid="skeleton-table">Loading...</div>,
}))
vi.mock('../../components/ui/PnlCell', () => ({
  default: ({ pnl }: { pnl: number }) => <span>{pnl}</span>,
}))
vi.mock('../../components/ui/ExitReasonBadge', () => ({
  default: () => <span />,
}))
vi.mock('../../components/ui/Pagination', () => ({
  default: ({ page, totalPages }: any) => (
    <div data-testid="pagination">
      <span>Page {page} of {totalPages}</span>
    </div>
  ),
}))
vi.mock('../../components/ui/DatePicker', () => ({
  default: () => <input data-testid="date-picker" />,
}))
vi.mock('../../components/ui/FilterDropdown', () => ({
  default: ({ value, onChange, ariaLabel, options }: any) => (
    <select aria-label={ariaLabel} value={value} onChange={(e: any) => onChange(e.target.value)}>
      {options.map((o: any) => <option key={o.value} value={o.value}>{o.label}</option>)}
    </select>
  ),
}))
vi.mock('../../components/ui/MobileTradeCard', () => ({
  default: ({ trade }: any) => <div data-testid={`trade-${trade.id}`}>{trade.symbol}</div>,
}))
vi.mock('../../components/ui/SizeValue', () => ({
  default: ({ children }: any) => <span>{children}</span>,
}))
vi.mock('../../components/ui/PullToRefreshIndicator', () => ({
  default: () => null,
}))
vi.mock('../../hooks/useIsMobile', () => ({
  default: () => false,
}))
vi.mock('../../hooks/usePullToRefresh', () => ({
  default: () => ({ containerRef: { current: null }, refreshing: false, pullDistance: 0 }),
}))

const makeTrade = (id: number, symbol: string) => ({
  id,
  symbol,
  side: 'long' as const,
  size: 0.1,
  entry_price: 50000,
  exit_price: 51000,
  take_profit: 52000,
  stop_loss: 49000,
  leverage: 10,
  confidence: 0.8,
  reason: 'Signal',
  status: 'closed' as const,
  pnl: 100,
  pnl_percent: 2.0,
  fees: 1.5,
  funding_paid: 0.5,
  builder_fee: 0,
  entry_time: '2026-04-01T10:00:00Z',
  exit_time: '2026-04-01T12:00:00Z',
  exit_reason: 'take_profit',
  exchange: 'bitget',
  demo_mode: false,
  bot_name: 'BTC Edge',
  bot_exchange: 'bitget',
})

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

describe('Trades Page', () => {
  beforeEach(() => {
    vi.clearAllMocks()

    // Default sync mutation
    mockUseSyncTrades.mockReturnValue({
      mutate: (_: unknown, opts?: { onSettled?: () => void }) => opts?.onSettled?.(),
    })
  })

  it('should show loading skeleton when data is loading', () => {
    mockUseTrades.mockReturnValue({ data: null, isLoading: true, error: null })

    render(<Trades />, { wrapper: createWrapper() })

    expect(screen.getByTestId('skeleton-table')).toBeInTheDocument()
  })

  it('should render trade list when data is loaded', async () => {
    const trades = [makeTrade(1, 'BTCUSDT'), makeTrade(2, 'ETHUSDT')]
    mockUseTrades.mockReturnValue({ data: { trades, total: 2 }, isLoading: false, error: null })

    render(<Trades />, { wrapper: createWrapper() })

    await waitFor(() => {
      expect(screen.getByText('BTCUSDT')).toBeInTheDocument()
      expect(screen.getByText('ETHUSDT')).toBeInTheDocument()
    })
  })

  it('should show empty state when no trades', async () => {
    mockUseTrades.mockReturnValue({ data: { trades: [], total: 0 }, isLoading: false, error: null })

    render(<Trades />, { wrapper: createWrapper() })

    await waitFor(() => {
      expect(screen.getByText('No trades found')).toBeInTheDocument()
    })
  })

  it('should show error state when query fails', async () => {
    mockUseTrades.mockReturnValue({ data: null, isLoading: false, error: new Error('fail') })

    render(<Trades />, { wrapper: createWrapper() })

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('An error occurred')
    })
  })

  it('should render pagination when trades exceed page size', async () => {
    const trades = Array.from({ length: 25 }, (_, i) => makeTrade(i + 1, 'BTCUSDT'))
    mockUseTrades.mockReturnValue({ data: { trades, total: 50 }, isLoading: false, error: null })

    render(<Trades />, { wrapper: createWrapper() })

    await waitFor(() => {
      expect(screen.getByTestId('pagination')).toBeInTheDocument()
      expect(screen.getByText('Page 1 of 2')).toBeInTheDocument()
    })
  })

  it('should render the page title', async () => {
    mockUseTrades.mockReturnValue({ data: { trades: [], total: 0 }, isLoading: false, error: null })

    render(<Trades />, { wrapper: createWrapper() })

    await waitFor(() => {
      expect(screen.getByText('Trades')).toBeInTheDocument()
    })
  })
})
