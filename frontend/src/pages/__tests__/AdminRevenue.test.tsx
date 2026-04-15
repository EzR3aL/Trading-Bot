import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import AdminRevenue from '../AdminRevenue'

const mockGet = vi.fn()
const mockPost = vi.fn()

vi.mock('../../api/client', () => ({
  default: {
    get: (...args: unknown[]) => mockGet(...args),
    post: (...args: unknown[]) => mockPost(...args),
    put: vi.fn(),
    delete: vi.fn(),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
  },
  setTokenExpiry: vi.fn(),
  clearTokenExpiry: vi.fn(),
}))

vi.mock('../../utils/api-error', () => ({
  getApiErrorMessage: (_err: unknown, fallback: string) => fallback,
}))

const mockAddToast = vi.fn()
vi.mock('../../stores/toastStore', () => ({
  useToastStore: (selector: (s: { addToast: typeof mockAddToast }) => unknown) =>
    selector({ addToast: mockAddToast }),
}))

vi.mock('../../components/ui/ExchangeLogo', () => ({
  ExchangeIcon: ({ exchange }: { exchange: string }) => (
    <span data-testid={`exchange-icon-${exchange}`}>{exchange}</span>
  ),
}))

vi.mock('recharts', () => ({
  BarChart: ({ children }: { children: React.ReactNode }) => <div data-testid="bar-chart">{children}</div>,
  Bar: () => null,
  XAxis: () => null,
  YAxis: () => null,
  CartesianGrid: () => null,
  Tooltip: () => null,
  ResponsiveContainer: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  Legend: () => null,
}))

const SAMPLE_RESPONSE = {
  summary: { today: 150.0, last_7d: 230.5, last_30d: 255.5, total: 255.5 },
  by_exchange: [
    { exchange: 'bitget', type: 'affiliate', total: 150.0, count: 1 },
    { exchange: 'weex', type: 'affiliate', total: 80.5, count: 1 },
  ],
  daily: [{ date: '2026-04-13', total: 150.0, by_exchange: { bitget: 150.0 } }],
  signups: { total: 6, by_exchange: { bitget: 3, weex: 3 } },
  sync_status: {
    bitget: { status: 'ok', last_synced_at: new Date().toISOString(), error: null },
    weex: { status: 'ok', last_synced_at: new Date().toISOString(), error: null },
    bingx: { status: 'not_configured', last_synced_at: null, error: null },
    bitunix: { status: 'unsupported', last_synced_at: null, error: 'No public API' },
    hyperliquid: { status: 'ok', last_synced_at: new Date().toISOString(), error: null },
  },
}

describe('AdminRevenue', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockGet.mockResolvedValue({ data: SAMPLE_RESPONSE })
    mockPost.mockResolvedValue({ data: { detail: 'synced', summary: {} } })
  })

  it('loads and displays revenue summary', async () => {
    render(<AdminRevenue />)
    await waitFor(() => expect(screen.getAllByText('150,00 $').length).toBeGreaterThan(0))
    expect(screen.getByText('Einnahmen')).toBeInTheDocument()
  })

  it('renders all 5 exchange tiles', async () => {
    render(<AdminRevenue />)
    await waitFor(() => {
      expect(screen.getByTestId('exchange-icon-bitget')).toBeInTheDocument()
      expect(screen.getByTestId('exchange-icon-weex')).toBeInTheDocument()
      expect(screen.getByTestId('exchange-icon-hyperliquid')).toBeInTheDocument()
      expect(screen.getByTestId('exchange-icon-bingx')).toBeInTheDocument()
      expect(screen.getByTestId('exchange-icon-bitunix')).toBeInTheDocument()
    })
  })

  it('shows Bitunix unavailable badge and warning', async () => {
    render(<AdminRevenue />)
    await waitFor(() => {
      const warnings = screen.getAllByText(/API nicht verfügbar|öffentliche Affiliate-API/)
      expect(warnings.length).toBeGreaterThanOrEqual(1)
    })
  })

  it('does not render manual entry button', async () => {
    render(<AdminRevenue />)
    await waitFor(() => expect(screen.getByText('Einnahmen')).toBeInTheDocument())
    expect(screen.queryByText('Neuer Eintrag')).not.toBeInTheDocument()
  })

  it('renders sync button and triggers sync on click', async () => {
    const user = userEvent.setup()
    render(<AdminRevenue />)
    const syncButton = await screen.findByText('Jetzt synchronisieren')
    await user.click(syncButton)
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/admin/revenue/sync'))
  })

  it('shows signup count in KPI strip', async () => {
    render(<AdminRevenue />)
    await waitFor(() => {
      expect(screen.getByText('Affiliate Signups')).toBeInTheDocument()
      expect(screen.getByText('6')).toBeInTheDocument()
    })
  })
})
