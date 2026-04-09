import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import Portfolio from '../Portfolio'
import { QueryWrapper } from '../../test/queryWrapper'

// Stable t function reference to prevent useEffect re-firing
const mockT = (key: string) => {
  const translations: Record<string, string> = {
    'portfolio.title': 'Portfolio',
    'portfolio.subtitle': 'Multi-Exchange Overview',
    'portfolio.totalBalance': 'Total Balance',
    'portfolio.totalPnl': 'Total PnL',
    'portfolio.totalTrades': 'Total Trades',
    'portfolio.winRate': 'Win Rate',
    'portfolio.fees': 'Fees',
    'portfolio.positions': 'Open Positions',
    'portfolio.noPositions': 'No open positions',
    'portfolio.exchange': 'Exchange',
    'portfolio.symbol': 'Symbol',
    'portfolio.side': 'Side',
    'portfolio.size': 'Size',
    'portfolio.entryPrice': 'Entry Price',
    'portfolio.currentPrice': 'Current Price',
    'portfolio.pnl': 'PnL',
    'portfolio.leverage': 'Leverage',
    'portfolio.allocation': 'Allocation',
    'portfolio.noData': 'No data',
    'portfolio.exchangeCards': 'Exchange Breakdown',
    'portfolio.dailyChart': 'Daily PnL',
    'portfolio.days7': '7D',
    'portfolio.days14': '14D',
    'portfolio.days30': '30D',
    'portfolio.days90': '90D',
    'common.error': 'An error occurred',
  }
  return translations[key] || key
}

// Mock react-i18next
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: mockT,
  }),
}))

// Mock API client
const mockGet = vi.fn()

vi.mock('../../api/client', () => ({
  default: {
    get: (...args: unknown[]) => mockGet(...args),
    interceptors: {
      request: { use: vi.fn() },
      response: { use: vi.fn() },
    },
  },
}))

// Mock ExchangeIcon component
vi.mock('../../components/ui/ExchangeLogo', () => ({
  ExchangeIcon: ({ exchange }: { exchange: string }) => <span data-testid={`icon-${exchange}`}>{exchange}</span>,
}))

// Mock recharts to avoid canvas rendering issues in JSDOM
vi.mock('recharts', () => ({
  AreaChart: ({ children }: any) => <div data-testid="area-chart">{children}</div>,
  Area: () => null,
  XAxis: () => null,
  YAxis: () => null,
  CartesianGrid: () => null,
  Tooltip: () => null,
  ResponsiveContainer: ({ children }: any) => <div>{children}</div>,
  PieChart: ({ children }: any) => <div data-testid="pie-chart">{children}</div>,
  Pie: () => null,
  Cell: () => null,
  Legend: () => null,
  Sector: () => null,
}))

describe('Portfolio Page', () => {
  const mockSummary = {
    total_pnl: 150.5,
    total_trades: 25,
    overall_win_rate: 64.0,
    total_fees: 12.5,
    total_funding: 2.5,
    exchanges: [
      {
        exchange: 'bitget',
        total_pnl: 100.0,
        total_trades: 15,
        win_rate: 66.7,
        total_fees: 8.0,
        total_funding: 1.5,
      },
      {
        exchange: 'hyperliquid',
        total_pnl: 50.5,
        total_trades: 10,
        win_rate: 60.0,
        total_fees: 4.5,
        total_funding: 1.0,
      },
    ],
  }

  const mockPositions = [
    {
      exchange: 'bitget',
      symbol: 'BTCUSDT',
      side: 'long',
      size: 0.01,
      entry_price: 95000,
      current_price: 96000,
      unrealized_pnl: 10.0,
      leverage: 5,
    },
  ]

  const mockDaily = [
    { date: '2025-01-15', exchange: 'bitget', pnl: 50.0, trades: 3 },
    { date: '2025-01-15', exchange: 'hyperliquid', pnl: 25.0, trades: 2 },
  ]

  const mockAllocation = [
    { exchange: 'bitget', balance: 5000.0 },
    { exchange: 'hyperliquid', balance: 3000.0 },
  ]

  beforeEach(() => {
    mockGet.mockReset()

    // Default responses
    mockGet.mockImplementation((url: string) => {
      if (url.includes('/portfolio/summary')) return Promise.resolve({ data: mockSummary })
      if (url.includes('/portfolio/positions')) return Promise.resolve({ data: mockPositions })
      if (url.includes('/portfolio/daily')) return Promise.resolve({ data: mockDaily })
      if (url.includes('/portfolio/allocation')) return Promise.resolve({ data: mockAllocation })
      return Promise.resolve({ data: {} })
    })
  })

  it('should render page title', async () => {
    render(<Portfolio />, { wrapper: QueryWrapper })

    await waitFor(() => {
      expect(screen.getByText('Portfolio')).toBeInTheDocument()
    })
    expect(screen.getByText('Multi-Exchange Overview')).toBeInTheDocument()
  })

  it('should show loading spinner initially', () => {
    mockGet.mockReturnValue(new Promise(() => {}))
    render(<Portfolio />, { wrapper: QueryWrapper })

    const spinner = document.querySelector('.animate-spin')
    expect(spinner).toBeTruthy()
  })

  it('should render period buttons', async () => {
    render(<Portfolio />, { wrapper: QueryWrapper })

    await waitFor(() => {
      expect(screen.getByText('7D')).toBeInTheDocument()
    })
    expect(screen.getByText('14D')).toBeInTheDocument()
    expect(screen.getByText('30D')).toBeInTheDocument()
    expect(screen.getByText('90D')).toBeInTheDocument()
  })

  it('should render total balance', async () => {
    render(<Portfolio />, { wrapper: QueryWrapper })

    // Wait for the page to finish loading (spinner disappears)
    await waitFor(() => {
      expect(screen.getByText('Portfolio')).toBeInTheDocument()
    })

    // Wait for allocation data to load and total balance to render
    await waitFor(() => {
      // $8,000 = 5000 + 3000 from allocation
      // Locale can format as $8,000.00 or $8.000,00 — search the full body text
      const body = document.body.textContent || ''
      expect(body).toMatch(/\$8[,.]000[,.]00/)
    }, { timeout: 5000 })
  })

  it('should render exchange cards', async () => {
    render(<Portfolio />, { wrapper: QueryWrapper })

    await waitFor(() => {
      expect(screen.getByText('Exchange Breakdown')).toBeInTheDocument()
    })
    // Exchange names appear multiple times (icon mock + card label), so use getAllByText
    expect(screen.getAllByText('bitget').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('hyperliquid').length).toBeGreaterThanOrEqual(1)
  })

  it('should render summary stats', async () => {
    render(<Portfolio />, { wrapper: QueryWrapper })

    await waitFor(() => {
      expect(screen.getByText('25')).toBeInTheDocument() // total trades
    })
    expect(screen.getByText('64.0%')).toBeInTheDocument() // win rate
  })

  it('should render positions table', async () => {
    render(<Portfolio />, { wrapper: QueryWrapper })

    await waitFor(() => {
      expect(screen.getByText('Open Positions')).toBeInTheDocument()
    })
    expect(screen.getByText('BTCUSDT')).toBeInTheDocument()
    expect(screen.getByText('LONG')).toBeInTheDocument()
  })

  it('should render no positions message when empty', async () => {
    mockGet.mockImplementation((url: string) => {
      if (url.includes('/portfolio/summary')) return Promise.resolve({ data: mockSummary })
      if (url.includes('/portfolio/positions')) return Promise.resolve({ data: [] })
      if (url.includes('/portfolio/daily')) return Promise.resolve({ data: mockDaily })
      if (url.includes('/portfolio/allocation')) return Promise.resolve({ data: mockAllocation })
      return Promise.resolve({ data: {} })
    })

    render(<Portfolio />, { wrapper: QueryWrapper })

    await waitFor(() => {
      expect(screen.getByText('No open positions')).toBeInTheDocument()
    })
  })

  it('should render charts', async () => {
    render(<Portfolio />, { wrapper: QueryWrapper })

    await waitFor(() => {
      expect(screen.getByText('Daily PnL')).toBeInTheDocument()
    })
    expect(screen.getByText('Allocation')).toBeInTheDocument()
  })

  it('should show error message on API failure', async () => {
    mockGet.mockRejectedValue(new Error('Network error'))

    render(<Portfolio />, { wrapper: QueryWrapper })

    await waitFor(() => {
      expect(screen.getByText('An error occurred')).toBeInTheDocument()
    })
  })

  it('should change period on button click', async () => {
    const user = userEvent.setup()
    render(<Portfolio />, { wrapper: QueryWrapper })

    await waitFor(() => {
      expect(screen.getByText('7D')).toBeInTheDocument()
    })

    await user.click(screen.getByText('7D'))

    // Should re-fetch with new period
    await waitFor(() => {
      const summaryCall = mockGet.mock.calls.find(
        (call: unknown[]) => typeof call[0] === 'string' && call[0].includes('/portfolio/summary')
      )
      expect(summaryCall).toBeTruthy()
    })
  })
})
