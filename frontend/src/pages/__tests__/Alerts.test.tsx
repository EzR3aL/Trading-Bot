import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import Alerts from '../Alerts'

// Mock react-i18next
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => {
      const translations: Record<string, string> = {
        'alerts.title': 'Alerts',
        'alerts.subtitle': 'Manage your price and strategy alerts',
        'alerts.newAlert': 'New Alert',
        'alerts.activeAlerts': 'Active Alerts',
        'alerts.all': 'All',
        'alerts.price': 'Price',
        'alerts.strategy': 'Strategy',
        'alerts.portfolio': 'Portfolio',
        'alerts.noAlerts': 'No alerts configured',
        'alerts.noHistory': 'No alert history',
        'alerts.historyTitle': 'Alert History',
        'alerts.threshold': 'Threshold',
        'alerts.triggerCount': 'Trigger Count',
        'alerts.lastTriggered': 'Last Triggered',
        'alerts.never': 'Never',
        'alerts.create': 'Create Alert',
        'alerts.type': 'Type',
        'alerts.category': 'Category',
        'alerts.selectCategory': 'Select Category',
        'alerts.symbol': 'Symbol',
        'alerts.selectSymbol': 'e.g. BTCUSDT',
        'alerts.direction': 'Direction',
        'alerts.above': 'Above',
        'alerts.below': 'Below',
        'alerts.cooldown': 'Cooldown (min)',
        'alerts.priceAbove': 'Price Above',
        'alerts.priceBelow': 'Price Below',
        'alerts.enabled': 'Enabled',
        'alerts.disabled': 'Disabled',
        'alerts.delete': 'Delete',
        'alerts.triggeredAt': 'Triggered At',
        'alerts.message': 'Message',
        'alerts.value': 'Value',
        'common.cancel': 'Cancel',
        'common.error': 'An error occurred',
      }
      return translations[key] || key
    },
  }),
}))

// Mock API client
const mockGet = vi.fn()
const mockPost = vi.fn()
const mockDelete = vi.fn()
const mockPatch = vi.fn()

vi.mock('../../api/client', () => ({
  default: {
    get: (...args: unknown[]) => mockGet(...args),
    post: (...args: unknown[]) => mockPost(...args),
    delete: (...args: unknown[]) => mockDelete(...args),
    patch: (...args: unknown[]) => mockPatch(...args),
    interceptors: {
      request: { use: vi.fn() },
      response: { use: vi.fn() },
    },
  },
}))

// Mock WebSocket
class MockWebSocket {
  onopen: (() => void) | null = null
  onmessage: ((e: MessageEvent) => void) | null = null
  onclose: (() => void) | null = null
  readyState = WebSocket.OPEN
  send = vi.fn()
  close = vi.fn()
  addEventListener = vi.fn()
}
vi.stubGlobal('WebSocket', MockWebSocket)

describe('Alerts Page', () => {
  beforeEach(() => {
    mockGet.mockReset()
    mockPost.mockReset()
    mockDelete.mockReset()
    mockPatch.mockReset()

    // Default: empty alerts and history
    mockGet.mockImplementation((url: string) => {
      if (url.includes('/alerts/history')) {
        return Promise.resolve({ data: [] })
      }
      if (url.includes('/alerts')) {
        return Promise.resolve({ data: [] })
      }
      return Promise.resolve({ data: {} })
    })
  })

  it('should render page title and subtitle', async () => {
    render(<Alerts />)

    await waitFor(() => {
      expect(screen.getByText('Alerts')).toBeInTheDocument()
    })
    expect(screen.getByText('Manage your price and strategy alerts')).toBeInTheDocument()
  })

  it('should show loading spinner initially', () => {
    // Make the API hang
    mockGet.mockReturnValue(new Promise(() => {}))
    render(<Alerts />)

    // The loading spinner should appear (it's a div with animate-spin)
    const spinner = document.querySelector('.animate-spin')
    expect(spinner).toBeTruthy()
  })

  it('should render empty state when no alerts', async () => {
    render(<Alerts />)

    await waitFor(() => {
      expect(screen.getByText('No alerts configured')).toBeInTheDocument()
    })
  })

  it('should render tab buttons', async () => {
    render(<Alerts />)

    await waitFor(() => {
      expect(screen.getByText('All')).toBeInTheDocument()
    })
    expect(screen.getByText('Price')).toBeInTheDocument()
    expect(screen.getByText('Strategy')).toBeInTheDocument()
    expect(screen.getByText('Portfolio')).toBeInTheDocument()
  })

  it('should render "New Alert" button', async () => {
    render(<Alerts />)

    await waitFor(() => {
      expect(screen.getByText('New Alert')).toBeInTheDocument()
    })
  })

  it('should render alert history section', async () => {
    render(<Alerts />)

    await waitFor(() => {
      expect(screen.getByText('Alert History')).toBeInTheDocument()
    })
    expect(screen.getByText('No alert history')).toBeInTheDocument()
  })

  it('should open create modal on button click', async () => {
    const user = userEvent.setup()
    render(<Alerts />)

    await waitFor(() => {
      expect(screen.getByText('New Alert')).toBeInTheDocument()
    })

    await user.click(screen.getByText('New Alert'))

    await waitFor(() => {
      expect(screen.getByText('Type')).toBeInTheDocument()
    })
  })

  it('should render alerts when data is returned', async () => {
    const alertData = [
      {
        id: 1,
        alert_type: 'price',
        category: 'price_above',
        symbol: 'BTCUSDT',
        threshold: 100000,
        direction: 'above',
        is_enabled: true,
        cooldown_minutes: 15,
        trigger_count: 0,
        last_triggered_at: null,
      },
    ]

    mockGet.mockImplementation((url: string) => {
      if (url.includes('/alerts/history')) {
        return Promise.resolve({ data: [] })
      }
      if (url.includes('/alerts')) {
        return Promise.resolve({ data: alertData })
      }
      return Promise.resolve({ data: {} })
    })

    render(<Alerts />)

    await waitFor(() => {
      expect(screen.getByText('BTCUSDT')).toBeInTheDocument()
    })
    expect(screen.getByText('Price Above')).toBeInTheDocument()
  })

  it('should show active alerts count', async () => {
    const alertData = [
      {
        id: 1, alert_type: 'price', category: 'price_above', symbol: 'BTCUSDT',
        threshold: 100000, direction: 'above', is_enabled: true,
        cooldown_minutes: 15, trigger_count: 0, last_triggered_at: null,
      },
      {
        id: 2, alert_type: 'portfolio', category: 'daily_loss', symbol: null,
        threshold: 5, direction: null, is_enabled: false,
        cooldown_minutes: 60, trigger_count: 1, last_triggered_at: null,
      },
    ]

    mockGet.mockImplementation((url: string) => {
      if (url.includes('/alerts/history')) return Promise.resolve({ data: [] })
      if (url.includes('/alerts')) return Promise.resolve({ data: alertData })
      return Promise.resolve({ data: {} })
    })

    render(<Alerts />)

    await waitFor(() => {
      // 1 active alert out of 2
      expect(screen.getByText('1')).toBeInTheDocument()
    })
  })
})
