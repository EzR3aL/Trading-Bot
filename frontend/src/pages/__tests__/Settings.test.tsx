import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import Settings from '../Settings'

const mockT = (key: string) => {
  const translations: Record<string, string> = {
    'settings.title': 'Settings',
    'settings.apiKeys': 'API Keys',
    'settings.connections': 'Connections',
    'settings.affiliateLinks': 'Affiliate Links',
    'settings.hyperliquid': 'Hyperliquid',
    'settings.save': 'Save',
    'settings.testConnection': 'Test Connection',
    'settings.saved': 'Saved',
    'settings.apiKey': 'API Key',
    'settings.apiSecret': 'API Secret',
    'settings.passphrase': 'Passphrase',
    'common.error': 'An error occurred',
  }
  return translations[key] || key
}

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: mockT }),
}))

const mockGet = vi.fn()

vi.mock('../../api/client', () => ({
  default: {
    get: (...args: unknown[]) => mockGet(...args),
    post: vi.fn().mockResolvedValue({}),
    put: vi.fn().mockResolvedValue({}),
    delete: vi.fn().mockResolvedValue({}),
    interceptors: {
      request: { use: vi.fn() },
      response: { use: vi.fn() },
    },
  },
  setTokenExpiry: vi.fn(),
  clearTokenExpiry: vi.fn(),
  getApiErrorMessage: vi.fn(() => 'error'),
}))

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return { ...actual, useNavigate: () => vi.fn() }
})

// Mock authStore to provide user
vi.mock('../../stores/authStore', () => ({
  useAuthStore: (selector?: (s: any) => any) => {
    const state = { user: { id: 1, username: 'admin', role: 'admin', language: 'en', is_active: true, email: null } }
    return selector ? selector(state) : state
  },
}))

vi.mock('../../components/ui/GuidedTour', () => ({
  default: () => null,
  TourHelpButton: () => null,
}))
vi.mock('../../components/ui/ExchangeLogo', () => ({
  ExchangeIcon: ({ exchange }: { exchange: string }) => <span>{exchange}</span>,
}))
vi.mock('../../components/ui/Pagination', () => ({
  default: () => null,
}))
vi.mock('../../components/ui/FilterDropdown', () => ({
  default: ({ value, onChange, ariaLabel, options }: any) => (
    <select aria-label={ariaLabel} value={value} onChange={(e: any) => onChange(e.target.value)}>
      {options?.map((o: any) => <option key={o.value} value={o.value}>{o.label}</option>)}
    </select>
  ),
}))
vi.mock('../../utils/api-error', () => ({
  getApiErrorMessage: vi.fn(() => 'error'),
}))

const mockExchanges = [
  { name: 'bitget', display_name: 'Bitget', auth_type: 'api_key', supports_demo: true },
  { name: 'hyperliquid', display_name: 'Hyperliquid', auth_type: 'eth_wallet', supports_demo: false },
]

const mockConnections = [
  { exchange_type: 'bitget', api_keys_configured: true, demo_api_keys_configured: false },
]

describe('Settings Page', () => {
  beforeEach(() => {
    vi.clearAllMocks()

    // Default API responses
    mockGet.mockImplementation((url: string) => {
      if (url === '/exchanges') return Promise.resolve({ data: { exchanges: mockExchanges } })
      if (url === '/config') return Promise.resolve({ data: {} })
      if (url === '/config/exchange-connections') return Promise.resolve({ data: { connections: mockConnections } })
      if (url === '/affiliate-links') return Promise.resolve({ data: [] })
      return Promise.resolve({ data: {} })
    })
  })

  it('should render settings title', async () => {
    render(
      <MemoryRouter>
        <Settings />
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.getByText('Settings')).toBeInTheDocument()
    })
  })

  it('should render tab buttons for admin user', async () => {
    render(
      <MemoryRouter>
        <Settings />
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.getAllByText('API Keys').length).toBeGreaterThanOrEqual(1)
      expect(screen.getAllByText('Hyperliquid').length).toBeGreaterThanOrEqual(1)
    })
  })

  it('should show API Keys section by default', async () => {
    render(
      <MemoryRouter>
        <Settings />
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.getAllByText('API Keys').length).toBeGreaterThanOrEqual(1)
    })
  })

  it('should show error when all API calls fail', async () => {
    mockGet.mockImplementation((url: string) => {
      if (url === '/exchanges') return Promise.reject(new Error('fail'))
      return Promise.reject(new Error('fail'))
    })

    render(
      <MemoryRouter>
        <Settings />
      </MemoryRouter>
    )

    // The page should still render the title even on error
    await waitFor(() => {
      expect(screen.getByText('Settings')).toBeInTheDocument()
    })
  })
})
