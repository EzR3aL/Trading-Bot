import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import AdminRevenue from '../AdminRevenue'

// --- Mocks ---

const mockGet = vi.fn()
const mockPost = vi.fn()
const mockPut = vi.fn()
const mockDelete = vi.fn()

vi.mock('../../api/client', () => ({
  default: {
    get: (...args: unknown[]) => mockGet(...args),
    post: (...args: unknown[]) => mockPost(...args),
    put: (...args: unknown[]) => mockPut(...args),
    delete: (...args: unknown[]) => mockDelete(...args),
    interceptors: {
      request: { use: vi.fn() },
      response: { use: vi.fn() },
    },
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

// Mock recharts to avoid canvas issues in tests
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

// --- Sample data ---

const SAMPLE_RESPONSE = {
  summary: { today: 150.0, last_7d: 230.5, last_30d: 255.5, total: 255.5 },
  by_exchange: [
    { exchange: 'bitget', type: 'affiliate', total: 150.0, count: 1 },
    { exchange: 'weex', type: 'affiliate', total: 80.5, count: 1 },
    { exchange: 'hyperliquid', type: 'builder_fee', total: 25.0, count: 3 },
  ],
  daily: [
    { date: '2026-04-13', total: 150.0, by_exchange: { bitget: 150.0 } },
    { date: '2026-04-08', total: 80.5, by_exchange: { weex: 80.5 } },
  ],
  entries: [
    {
      id: 1,
      date: '2026-04-13',
      exchange: 'bitget',
      type: 'affiliate',
      amount: 150.0,
      source: 'manual',
      notes: 'Q1 payout',
    },
    {
      id: 2,
      date: '2026-04-08',
      exchange: 'weex',
      type: 'affiliate',
      amount: 80.5,
      source: 'manual',
      notes: null,
    },
    {
      id: 3,
      date: '2026-04-03',
      exchange: 'hyperliquid',
      type: 'builder_fee',
      amount: 25.0,
      source: 'auto',
      notes: null,
    },
  ],
}

// --- Tests ---

describe('AdminRevenue', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockGet.mockResolvedValue({ data: SAMPLE_RESPONSE })
  })

  it('renders loading state initially', () => {
    mockGet.mockReturnValue(new Promise(() => {})) // never resolves
    render(<AdminRevenue />)
    expect(screen.getByText('Einnahmen')).toBeInTheDocument()
  })

  it('renders KPI strip with correct values', async () => {
    render(<AdminRevenue />)
    await waitFor(() => {
      expect(screen.getByText('Heute')).toBeInTheDocument()
    })
    expect(screen.getByText('Gesamt')).toBeInTheDocument()
    // '7 Tage' and '30 Tage' appear in both KPI strip and period selector
    expect(screen.getAllByText('7 Tage').length).toBeGreaterThanOrEqual(2)
    expect(screen.getAllByText('30 Tage').length).toBeGreaterThanOrEqual(2)
  })

  it('renders all 5 exchange cards', async () => {
    render(<AdminRevenue />)
    await waitFor(() => {
      // Exchange names appear in both cards and entry table, so use getAllByText
      expect(screen.getAllByText('Bitget').length).toBeGreaterThanOrEqual(1)
    })
    expect(screen.getAllByText('Weex').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('Hyperliquid').length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText('BingX')).toBeInTheDocument()
    expect(screen.getByText('Bitunix')).toBeInTheDocument()
  })

  it('renders entry table with manual entries', async () => {
    render(<AdminRevenue />)
    await waitFor(() => {
      expect(screen.getByText('Letzte Einträge')).toBeInTheDocument()
    })
  })

  it('renders chart section', async () => {
    render(<AdminRevenue />)
    await waitFor(() => {
      expect(screen.getByText('Zeitverlauf')).toBeInTheDocument()
    })
    expect(screen.getByTestId('bar-chart')).toBeInTheDocument()
  })

  it('shows period selector buttons', async () => {
    render(<AdminRevenue />)
    await waitFor(() => {
      expect(screen.getByText('90 Tage')).toBeInTheDocument()
    })
    expect(screen.getByText('1 Jahr')).toBeInTheDocument()
    // '7 Tage' and '30 Tage' appear both in KPI strip and period selector
    expect(screen.getAllByText('7 Tage').length).toBeGreaterThanOrEqual(2)
    expect(screen.getAllByText('30 Tage').length).toBeGreaterThanOrEqual(2)
  })

  it('changes period when clicking period button', async () => {
    render(<AdminRevenue />)
    await waitFor(() => {
      expect(mockGet).toHaveBeenCalledTimes(1)
    })
    // Click '90 Tage' which is unique (only in period selector)
    fireEvent.click(screen.getByText('90 Tage'))
    await waitFor(() => {
      expect(mockGet).toHaveBeenCalledTimes(2)
    })
  })

  it('shows error toast on API failure', async () => {
    mockGet.mockRejectedValue(new Error('Network error'))
    render(<AdminRevenue />)
    await waitFor(() => {
      expect(mockAddToast).toHaveBeenCalledWith('error', 'Fehler beim Laden der Einnahmen')
    })
  })

  it('renders "Neuer Eintrag" button', async () => {
    render(<AdminRevenue />)
    await waitFor(() => {
      expect(screen.getByText('Neuer Eintrag')).toBeInTheDocument()
    })
  })

  it('opens create modal on button click', async () => {
    render(<AdminRevenue />)
    await waitFor(() => {
      expect(screen.getByText('Neuer Eintrag')).toBeInTheDocument()
    })
    fireEvent.click(screen.getByText('Neuer Eintrag'))
    expect(screen.getByText('Anlegen')).toBeInTheDocument()
  })

  it('submits create form and refreshes data', async () => {
    mockPost.mockResolvedValue({ data: { id: 10, exchange: 'bingx', amount: 42.5, source: 'manual' } })
    render(<AdminRevenue />)
    await waitFor(() => {
      expect(screen.getByText('Neuer Eintrag')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('Neuer Eintrag'))

    const amountInput = screen.getByPlaceholderText('0.00')
    fireEvent.change(amountInput, { target: { value: '42.50' } })

    fireEvent.click(screen.getByText('Anlegen'))

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledTimes(1)
    })
  })

  it('shows edit/delete buttons only for manual entries', async () => {
    render(<AdminRevenue />)
    await waitFor(() => {
      expect(screen.getByText('Letzte Einträge')).toBeInTheDocument()
    })
    // Manual entries (2) get edit+delete buttons, auto entry (1) does not
    const editButtons = screen.getAllByTitle('Bearbeiten')
    const deleteButtons = screen.getAllByTitle('Löschen')
    expect(editButtons.length).toBe(2)
    expect(deleteButtons.length).toBe(2)
  })

  it('opens delete confirmation modal', async () => {
    render(<AdminRevenue />)
    await waitFor(() => {
      expect(screen.getByText('Letzte Einträge')).toBeInTheDocument()
    })
    const deleteButtons = screen.getAllByTitle('Löschen')
    fireEvent.click(deleteButtons[0])
    expect(screen.getByText('Eintrag löschen')).toBeInTheDocument()
    expect(screen.getByText('Löschen')).toBeInTheDocument()
  })

  it('calls delete API and refreshes on confirm', async () => {
    mockDelete.mockResolvedValue({ data: { detail: 'deleted' } })
    render(<AdminRevenue />)
    await waitFor(() => {
      expect(screen.getByText('Letzte Einträge')).toBeInTheDocument()
    })

    const deleteButtons = screen.getAllByTitle('Löschen')
    fireEvent.click(deleteButtons[0])

    const confirmBtn = screen.getByText('Löschen')
    fireEvent.click(confirmBtn)

    await waitFor(() => {
      expect(mockDelete).toHaveBeenCalledWith('/admin/revenue/1')
    })
  })

  it('renders empty state when no entries', async () => {
    mockGet.mockResolvedValue({
      data: {
        summary: { today: 0, last_7d: 0, last_30d: 0, total: 0 },
        by_exchange: [],
        daily: [],
        entries: [],
      },
    })
    render(<AdminRevenue />)
    await waitFor(() => {
      expect(screen.getByText('Noch keine manuellen Einträge vorhanden')).toBeInTheDocument()
    })
  })
})
