import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import Dashboard from '../Dashboard'

const mockT = (key: string) => {
  const translations: Record<string, string> = {
    'dashboard.title': 'Dashboard',
    'dashboard.totalPnl': 'Total PnL',
    'dashboard.winRate': 'Win Rate',
    'dashboard.bestTrade': 'Best Trade',
    'dashboard.worstTrade': 'Worst Trade',
    'dashboard.fees': 'Fees',
    'dashboard.funding': 'Funding',
    'dashboard.pnlOverTime': 'PnL Over Time',
    'dashboard.winLoss': 'Win / Loss',
    'common.timeframes.days7': '7D',
    'dashboard.days14': '14D',
    'common.timeframes.days30': '30D',
    'common.timeframes.days90': '90D',
    'common.error': 'An error occurred',
  }
  return translations[key] || key
}

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: mockT }),
}))

// Mock the React Query hooks from queries module
const mockUseDashboardStats = vi.fn()
const mockUseDashboardDaily = vi.fn()
const mockUsePortfolioPositions = vi.fn()
const mockUseSyncTrades = vi.fn()
const mockUseUpdateTpSl = vi.fn()

vi.mock('../../api/queries', () => ({
  useDashboardStats: (...args: unknown[]) => mockUseDashboardStats(...args),
  useDashboardDaily: (...args: unknown[]) => mockUseDashboardDaily(...args),
  usePortfolioPositions: (...args: unknown[]) => mockUsePortfolioPositions(...args),
  useSyncTrades: () => mockUseSyncTrades(),
  useUpdateTpSl: () => mockUseUpdateTpSl(),
  queryKeys: {
    dashboard: {
      stats: () => ['dashboard', 'stats'],
      daily: () => ['dashboard', 'daily'],
    },
    portfolio: { positions: ['portfolio', 'positions'] },
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

// Mock chart and UI components
vi.mock('../../components/dashboard/PnlChart', () => ({
  default: () => <div data-testid="pnl-chart">PnlChart</div>,
}))
vi.mock('../../components/dashboard/WinLossChart', () => ({
  default: () => <div data-testid="winloss-chart">WinLossChart</div>,
}))
vi.mock('../../components/dashboard/RevenueChart', () => ({
  default: () => <div data-testid="revenue-chart">RevenueChart</div>,
}))
vi.mock('../../components/ui/Skeleton', () => ({
  DashboardSkeleton: () => <div data-testid="dashboard-skeleton">Loading...</div>,
}))
vi.mock('../../components/ui/ExchangeLogo', () => ({
  ExchangeIcon: ({ exchange }: { exchange: string }) => <span>{exchange}</span>,
}))
vi.mock('../../components/ui/SizeValue', () => ({
  default: ({ children }: any) => <span>{children}</span>,
}))
vi.mock('../../components/ui/GuidedTour', () => ({
  default: () => null,
  TourHelpButton: () => null,
}))
vi.mock('../../components/ui/MobilePositionCard', () => ({
  default: () => null,
}))
vi.mock('../../components/ui/EditPositionPanel', () => ({
  default: () => null,
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

const mockStats = {
  total_trades: 100,
  winning_trades: 60,
  losing_trades: 40,
  win_rate: 60.0,
  total_pnl: 500.0,
  net_pnl: 480.0,
  total_fees: 15.0,
  total_funding: 5.0,
  avg_pnl: 5.0,
  best_trade: 50.0,
  worst_trade: -20.0,
}

const mockDailyData = {
  days: [
    { date: '2026-04-01', pnl: 10, trades: 3, cumulative_pnl: 10 },
    { date: '2026-04-02', pnl: -5, trades: 2, cumulative_pnl: 5 },
  ],
}

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

describe('Dashboard Page', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    sessionStorage.clear()

    // Default: sync mutation that calls onSettled immediately
    mockUseSyncTrades.mockReturnValue({
      mutate: (_: unknown, opts?: { onSettled?: () => void }) => opts?.onSettled?.(),
    })
    mockUseUpdateTpSl.mockReturnValue({ mutate: vi.fn() })
  })

  it('should show loading skeleton when data is loading', () => {
    mockUseDashboardStats.mockReturnValue({ data: null, isLoading: true, error: null })
    mockUseDashboardDaily.mockReturnValue({ data: null, isLoading: true, error: null })
    mockUsePortfolioPositions.mockReturnValue({ data: [], isLoading: true })

    render(<Dashboard />, { wrapper: createWrapper() })

    expect(screen.getByTestId('dashboard-skeleton')).toBeInTheDocument()
  })

  it('should render without crashing and display data when loaded', async () => {
    mockUseDashboardStats.mockReturnValue({ data: mockStats, isLoading: false, error: null })
    mockUseDashboardDaily.mockReturnValue({ data: mockDailyData, isLoading: false, error: null })
    mockUsePortfolioPositions.mockReturnValue({ data: [], isLoading: false })

    render(<Dashboard />, { wrapper: createWrapper() })

    await waitFor(() => {
      expect(screen.getByText('Dashboard')).toBeInTheDocument()
      expect(screen.getByText('Total PnL')).toBeInTheDocument()
      expect(screen.getByText('Win Rate')).toBeInTheDocument()
      expect(screen.getByText('Best Trade')).toBeInTheDocument()
      expect(screen.getByText('Worst Trade')).toBeInTheDocument()
    })
  })

  it('should display charts when loaded', async () => {
    mockUseDashboardStats.mockReturnValue({ data: mockStats, isLoading: false, error: null })
    mockUseDashboardDaily.mockReturnValue({ data: mockDailyData, isLoading: false, error: null })
    mockUsePortfolioPositions.mockReturnValue({ data: [], isLoading: false })

    render(<Dashboard />, { wrapper: createWrapper() })

    await waitFor(() => {
      expect(screen.getByTestId('pnl-chart')).toBeInTheDocument()
      expect(screen.getByTestId('winloss-chart')).toBeInTheDocument()
    })
  })

  it('should show error when stats query fails', async () => {
    mockUseDashboardStats.mockReturnValue({ data: null, isLoading: false, error: new Error('fail') })
    mockUseDashboardDaily.mockReturnValue({ data: null, isLoading: false, error: null })
    mockUsePortfolioPositions.mockReturnValue({ data: [], isLoading: false })

    render(<Dashboard />, { wrapper: createWrapper() })

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('An error occurred')
    })
  })
})
