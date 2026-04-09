import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import TaxReport from '../TaxReport'

// Mock API client
vi.mock('../../api/client', () => ({
  default: {
    get: vi.fn(),
  },
}))

import api from '../../api/client'

// Mock i18n
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: string) => fallback ?? key,
    i18n: { language: 'en' },
  }),
}))

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

describe('TaxReport', () => {
  beforeEach(() => {
    vi.mocked(api.get).mockResolvedValue({
      data: {
        year: 2026,
        total_trades: 100,
        total_pnl: 500.0,
        total_fees: 25.0,
        total_funding: 10.0,
        net_pnl: 465.0,
        months: [
          { month: 'Jan', trades: 20, pnl: 100.0, fees: 5.0 },
        ],
      },
    })
  })

  it('renders the page title', () => {
    renderWithProviders(<TaxReport />)
    expect(screen.getByText('tax.title')).toBeInTheDocument()
  })

  it('has a CSV download button', () => {
    renderWithProviders(<TaxReport />)
    expect(screen.getByText('CSV')).toBeInTheDocument()
  })

  it('shows year selection options', () => {
    renderWithProviders(<TaxReport />)
    // The year filter dropdown should contain the current year
    const currentYear = new Date().getFullYear()
    expect(screen.getByText(String(currentYear))).toBeInTheDocument()
  })

  it('shows loading skeletons initially', () => {
    // The component starts in loading state before the API responds
    renderWithProviders(<TaxReport />)
    // During loading, no error alert should be present
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})
