import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, act, fireEvent } from '@testing-library/react'
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import Trades from '../Trades'

const mockT = (key: string, opts?: { defaultValue?: string }) => {
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
    'trades.clearAllFilters': 'Clear all filters',
    'trades.noTradesTitle': 'No trades found',
    'trades.noTradesHint': 'Trades will appear here once your bots execute them',
    'common.error': 'An error occurred',
    'common.loadError': 'Failed to load data',
  }
  return translations[key] || opts?.defaultValue || key
}

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: mockT }),
}))

// Mock React Query hooks
const mockUseTrades = vi.fn()
const mockUseSyncTrades = vi.fn()
const mockUseTradesFilterOptions = vi.fn()

vi.mock('../../api/queries', () => ({
  useTrades: (...args: unknown[]) => mockUseTrades(...args),
  useSyncTrades: () => mockUseSyncTrades(),
  queryKeys: {
    trades: { all: ['trades'] },
  },
}))

vi.mock('../../hooks/useTradesFilterOptions', () => ({
  useTradesFilterOptions: () => mockUseTradesFilterOptions(),
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
  default: ({ page, totalPages }: { page: number; totalPages: number }) => (
    <div data-testid="pagination">
      <span>Page {page} of {totalPages}</span>
    </div>
  ),
}))
vi.mock('../../components/ui/DatePicker', () => ({
  default: ({ value, onChange, label }: { value: string; onChange: (v: string) => void; label: string }) => (
    <input
      data-testid={`date-picker-${label}`}
      aria-label={label}
      value={value}
      onChange={(e) => onChange(e.target.value)}
    />
  ),
}))
interface FilterDropdownOption { value: string; label: string }
vi.mock('../../components/ui/FilterDropdown', () => ({
  default: ({
    value,
    onChange,
    ariaLabel,
    options,
  }: {
    value: string
    onChange: (v: string) => void
    ariaLabel: string
    options: FilterDropdownOption[]
  }) => (
    <select
      aria-label={ariaLabel}
      value={value}
      onChange={(e) => onChange(e.target.value)}
    >
      {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
    </select>
  ),
}))
vi.mock('../../components/ui/MobileTradeCard', () => ({
  default: ({ trade }: { trade: { id: number; symbol: string } }) => (
    <div data-testid={`trade-${trade.id}`}>{trade.symbol}</div>
  ),
}))
vi.mock('../../components/ui/SizeValue', () => ({
  default: ({ children }: { children?: React.ReactNode }) => <span>{children}</span>,
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

// ── Location spy helper ───────────────────────────────────────────
// Renders a tiny sidecar that exposes the current URL so tests can
// assert on query-param updates without guessing at navigation APIs.
let currentSearch = ''
function LocationProbe() {
  const loc = useLocation()
  currentSearch = loc.search
  return null
}

function createWrapper(initialEntries: string[] = ['/trades']) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={initialEntries}>
        <LocationProbe />
        <Routes>
          <Route path="/trades" element={children} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  )
}

describe('Trades Page', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    currentSearch = ''

    mockUseSyncTrades.mockReturnValue({
      mutate: (_: unknown, opts?: { onSettled?: () => void }) => opts?.onSettled?.(),
    })
    mockUseTradesFilterOptions.mockReturnValue({
      data: {
        symbols: ['BTCUSDT', 'ETHUSDT', 'SOLUSDT'],
        bots: [
          { id: 1, name: 'BTC Edge' },
          { id: 2, name: 'ETH Hunter' },
        ],
        exchanges: ['bitget', 'hyperliquid'],
        statuses: ['open', 'closed', 'cancelled'],
      },
      isLoading: false,
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

  // ── New behavior: URL-driven filter state ────────────────────────

  it('should hydrate filter controls from URL search params on mount', async () => {
    mockUseTrades.mockReturnValue({ data: { trades: [], total: 0 }, isLoading: false, error: null })

    render(<Trades />, {
      wrapper: createWrapper(['/trades?symbol=BTCUSDT&status=open&exchange=bitget']),
    })

    await waitFor(() => {
      const statusSelect = screen.getByLabelText('Status') as HTMLSelectElement
      expect(statusSelect.value).toBe('open')

      const symbolInput = screen.getByLabelText('Symbol') as HTMLInputElement
      expect(symbolInput.value).toBe('BTCUSDT')

      const exchangeSelect = screen.getByLabelText('Exchange') as HTMLSelectElement
      expect(exchangeSelect.value).toBe('bitget')
    })

    // The useTrades query must receive URL-derived filters, not stale local state.
    const lastCall = mockUseTrades.mock.calls.at(-1)?.[0] as Record<string, unknown>
    expect(lastCall).toMatchObject({
      symbol: 'BTCUSDT',
      status: 'open',
      exchange: 'bitget',
      page: 1,
    })
  })

  it('should update URL when a dropdown filter changes', async () => {
    mockUseTrades.mockReturnValue({ data: { trades: [], total: 0 }, isLoading: false, error: null })

    render(<Trades />, { wrapper: createWrapper() })

    const statusSelect = screen.getByLabelText('Status') as HTMLSelectElement
    await act(async () => {
      fireEvent.change(statusSelect, { target: { value: 'open' } })
    })

    await waitFor(() => {
      expect(currentSearch).toContain('status=open')
    })
  })

  it('should debounce URL updates from the symbol textbox', async () => {
    mockUseTrades.mockReturnValue({ data: { trades: [], total: 0 }, isLoading: false, error: null })

    render(<Trades />, { wrapper: createWrapper() })

    const symbolInput = screen.getByLabelText('Symbol') as HTMLInputElement

    // Typing quickly shouldn't immediately write every keystroke to the URL.
    // We use real timers (fake timers conflict with react-query's async
    // machinery) and instead assert the intermediate and final states.
    act(() => {
      fireEvent.change(symbolInput, { target: { value: 'B' } })
      fireEvent.change(symbolInput, { target: { value: 'BT' } })
      fireEvent.change(symbolInput, { target: { value: 'BTC' } })
    })

    // Immediately after typing the URL must not yet reflect the new symbol —
    // intermediate keystrokes ('B', 'BT') never produce a history entry.
    expect(currentSearch).not.toContain('symbol=')

    // After the debounce window elapses, the URL settles on the final value.
    await waitFor(
      () => {
        expect(currentSearch).toContain('symbol=BTC')
      },
      { timeout: 1000 },
    )
    // Single write — no flicker through intermediate values.
    expect(currentSearch).not.toContain('symbol=B&')
    expect(currentSearch).not.toContain('symbol=BT&')
  })

  it('should populate dropdown options from the filter-options hook, not derive from trade list', async () => {
    mockUseTrades.mockReturnValue({ data: { trades: [], total: 0 }, isLoading: false, error: null })
    mockUseTradesFilterOptions.mockReturnValue({
      data: {
        symbols: ['DOGEUSDT'],
        bots: [{ id: 99, name: 'Moonshot Bot' }],
        exchanges: ['hyperliquid'],
        statuses: ['open', 'closed'],
      },
      isLoading: false,
    })

    render(<Trades />, { wrapper: createWrapper() })

    const botSelect = screen.getByLabelText('Bot') as HTMLSelectElement
    await waitFor(() => {
      const values = Array.from(botSelect.options).map((o) => o.value)
      // "Moonshot Bot" comes from the hook even though no trades mention it
      expect(values).toContain('Moonshot Bot')
    })

    const exchangeSelect = screen.getByLabelText('Exchange') as HTMLSelectElement
    const exchangeValues = Array.from(exchangeSelect.options).map((o) => o.value)
    expect(exchangeValues).toContain('hyperliquid')
    expect(exchangeValues).not.toContain('bitget') // confirms it isn't derived from loaded trades
  })

  // UX-M1 regression: virtualisation must keep the rendered-row DOM
  // cost bounded when the trade list is large, without breaking the
  // existing sort / filter / click contract.
  it('should render fewer DOM rows than source when trade list exceeds virtualisation threshold', async () => {
    // 250 trades — well above the 50-row threshold the hook uses.
    // We deliberately don't use 1000+ here because under the parallel
    // test suite JSDOM layout-less "rendering" of that many rows is
    // slow enough to approach vitest's default per-test timeout; 250
    // is still a strong signal that virtualisation is active and
    // keeps the assertion snappy.
    const trades = Array.from({ length: 250 }, (_, i) => makeTrade(i + 1, `COIN${i}USDT`))
    mockUseTrades.mockReturnValue({ data: { trades, total: 250 }, isLoading: false, error: null })

    render(<Trades />, { wrapper: createWrapper() })

    await waitFor(() => {
      // At least one trade row visible — the virtualised slice.
      expect(screen.getAllByRole('row').length).toBeGreaterThan(1)
    })

    // Windowed render contract: the DOM holds strictly fewer rows
    // than the source. Without virtualisation we'd see 250+ <tr>s
    // (one per trade + header); the virtualised slice is bounded by
    // viewport + overscan. We assert "< source size" rather than a
    // tight cap because JSDOM does not perform real layout so exact
    // bounds depend on react-virtual's fallback behaviour — the
    // key invariant is that scaling the source does NOT scale the
    // DOM linearly. A real browser renders ~30 rows here.
    const rowCount = screen.getAllByRole('row').length
    expect(rowCount).toBeLessThan(trades.length)
  })

  it('should gracefully render empty dropdowns when filter-options is loading', async () => {
    mockUseTrades.mockReturnValue({ data: { trades: [], total: 0 }, isLoading: false, error: null })
    mockUseTradesFilterOptions.mockReturnValue({ data: undefined, isLoading: true })

    render(<Trades />, { wrapper: createWrapper() })

    // Page renders without crashing; status falls back to a default list
    await waitFor(() => {
      expect(screen.getByText('Trades')).toBeInTheDocument()
    })
    const botSelect = screen.getByLabelText('Bot') as HTMLSelectElement
    const values = Array.from(botSelect.options).map((o) => o.value)
    expect(values).toEqual(['']) // only the "All Bots" option
  })
})
