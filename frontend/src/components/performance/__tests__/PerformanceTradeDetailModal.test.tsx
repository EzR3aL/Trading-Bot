import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import PerformanceTradeDetailModal from '../PerformanceTradeDetailModal'
import type { BotDetailRecentTrade } from '../types'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}))

vi.mock('../../ui/ExchangeLogo', () => ({
  ExchangeIcon: ({ exchange }: { exchange: string }) => <span data-testid={`exch-${exchange}`} />,
}))

vi.mock('../../ui/PnlCell', () => ({
  default: ({ pnl }: { pnl: number }) => <span data-testid="pnl">{pnl}</span>,
}))

vi.mock('../../../stores/themeStore', () => ({
  useThemeStore: (sel: (s: unknown) => unknown) => sel({ theme: 'dark' }),
}))

vi.mock('../../../stores/toastStore', () => ({
  useToastStore: { getState: () => ({ addToast: vi.fn() }) },
}))

vi.mock('../../../hooks/useIsMobile', () => ({ default: () => false }))
vi.mock('../../../hooks/useSwipeToClose', () => ({
  default: () => ({ ref: { current: null }, style: {} }),
}))

vi.mock('../../../utils/dateUtils', () => ({
  formatDate: (d: string) => `date:${d}`,
}))

const trade: BotDetailRecentTrade = {
  id: 1,
  symbol: 'ETHUSDT',
  side: 'long',
  entry_price: 2000,
  exit_price: 2100,
  pnl: 100,
  pnl_percent: 5,
  confidence: 80,
  reason: '',
  status: 'closed',
  fees: 1,
  funding_paid: 0,
  leverage: 3,
  demo_mode: false,
  entry_time: '2026-04-01T00:00:00Z',
  exit_time: '2026-04-01T01:00:00Z',
  exit_reason: null,
}

describe('PerformanceTradeDetailModal', () => {
  it('renders trade symbol in header', () => {
    render(<PerformanceTradeDetailModal trade={trade} exchange="bitget" affiliateLink={null} onClose={() => {}} />)
    expect(screen.getAllByText('ETHUSDT').length).toBeGreaterThan(0)
  })

  it('renders LONG badge for long side', () => {
    render(<PerformanceTradeDetailModal trade={trade} exchange="bitget" affiliateLink={null} onClose={() => {}} />)
    expect(screen.getAllByText('+ LONG').length).toBeGreaterThan(0)
  })

  it('renders SHORT badge for short side', () => {
    render(<PerformanceTradeDetailModal trade={{ ...trade, side: 'short' }} exchange="bitget" affiliateLink={null} onClose={() => {}} />)
    expect(screen.getAllByText('- SHORT').length).toBeGreaterThan(0)
  })

  it('renders entry/exit prices', () => {
    render(<PerformanceTradeDetailModal trade={trade} exchange="bitget" affiliateLink={null} onClose={() => {}} />)
    expect(screen.getByText(/\$2[.,]000/)).toBeInTheDocument()
    expect(screen.getByText(/\$2[.,]100/)).toBeInTheDocument()
  })

  it('shows -- when exit_price is null', () => {
    render(<PerformanceTradeDetailModal trade={{ ...trade, exit_price: null }} exchange="bitget" affiliateLink={null} onClose={() => {}} />)
    expect(screen.getByText('--')).toBeInTheDocument()
  })

  it('renders affiliate link when provided', () => {
    render(
      <PerformanceTradeDetailModal
        trade={trade}
        exchange="bitget"
        affiliateLink={{ exchange_type: 'bitget', affiliate_url: 'https://aff', label: 'Aff Label' }}
        onClose={() => {}}
      />,
    )
    expect(screen.getByText('Aff Label')).toBeInTheDocument()
    expect(screen.getByText('https://aff')).toBeInTheDocument()
  })

  it('calls onClose when backdrop clicked', () => {
    const onClose = vi.fn()
    render(<PerformanceTradeDetailModal trade={trade} exchange="bitget" affiliateLink={null} onClose={onClose} />)
    fireEvent.click(screen.getByLabelText('common.close'))
    expect(onClose).toHaveBeenCalled()
  })
})
