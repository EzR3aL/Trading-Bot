import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import GettingStarted from '../GettingStarted'

// Mock API client for affiliate links fetch
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

// Mock GuidedTour components to avoid complexity
vi.mock('../../components/ui/GuidedTour', () => ({
  default: () => null,
  TourHelpButton: () => <button>Tour</button>,
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

describe('GettingStarted', () => {
  beforeEach(() => {
    vi.mocked(api.get).mockResolvedValue({ data: [] })
  })

  it('renders the page title and subtitle', () => {
    renderWithProviders(<GettingStarted />)
    expect(screen.getByText('guide.title')).toBeInTheDocument()
    expect(screen.getByText('guide.subtitle')).toBeInTheDocument()
  })

  it('renders quickstart section by default', () => {
    renderWithProviders(<GettingStarted />)
    expect(screen.getByText('guide.qsTitle')).toBeInTheDocument()
  })

  it('shows step content in the quickstart flow', () => {
    renderWithProviders(<GettingStarted />)
    expect(screen.getByText('guide.qsStep1')).toBeInTheDocument()
    expect(screen.getByText('guide.qsStep2')).toBeInTheDocument()
    expect(screen.getByText('guide.qsStep3')).toBeInTheDocument()
    expect(screen.getByText('guide.qsStep4')).toBeInTheDocument()
  })

  it('renders navigation section buttons', () => {
    renderWithProviders(<GettingStarted />)
    expect(screen.getAllByText('guide.navQuickstart').length).toBeGreaterThanOrEqual(1)
  })
})
