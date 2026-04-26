import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import TradeDetailModal from '../TradeDetailModal'
import type { BotTrade } from '../types'

vi.mock('../../ui/ExchangeLogo', () => ({
  ExchangeIcon: ({ exchange }: { exchange: string }) => <span data-testid={`exch-${exchange}`} />,
}))

vi.mock('../../ui/PnlCell', () => ({
  default: ({ pnl }: { pnl: number }) => <span data-testid="pnl">{pnl}</span>,
}))

vi.mock('../../../stores/themeStore', () => ({
  useThemeStore: (selector: (s: unknown) => unknown) => selector({ theme: 'dark' }),
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

const t = (key: string, fallback?: string) => fallback || key

const baseTrade: BotTrade = {
  id: 1,
  symbol: 'BTCUSDT',
  side: 'long',
  size: 0.5,
  entry_price: 50000,
  exit_price: 52000,
  pnl: 1000,
  pnl_percent: 4.0,
  confidence: 80,
  reason: '',
  leverage: 5,
  status: 'closed',
  demo_mode: true,
  exchange: 'bitget',
  entry_time: '2026-04-01T00:00:00Z',
  exit_time: '2026-04-01T01:00:00Z',
  exit_reason: null,
  fees: 2,
  funding_paid: 0,
}

describe('TradeDetailModal', () => {
  it('renders trade symbol in header', () => {
    render(<TradeDetailModal trade={baseTrade} onClose={() => {}} t={t} />)
    expect(screen.getAllByText('BTCUSDT').length).toBeGreaterThan(0)
  })

  it('renders LONG badge for long side', () => {
    render(<TradeDetailModal trade={baseTrade} onClose={() => {}} t={t} />)
    expect(screen.getAllByText('+ LONG').length).toBeGreaterThan(0)
  })

  it('renders SHORT badge for short side', () => {
    render(<TradeDetailModal trade={{ ...baseTrade, side: 'short' }} onClose={() => {}} t={t} />)
    expect(screen.getAllByText('- SHORT').length).toBeGreaterThan(0)
  })

  it('renders the leverage chip when leverage is set', () => {
    render(<TradeDetailModal trade={baseTrade} onClose={() => {}} t={t} />)
    expect(screen.getByText('5x')).toBeInTheDocument()
  })

  it('renders entry and exit prices', () => {
    render(<TradeDetailModal trade={baseTrade} onClose={() => {}} t={t} />)
    expect(screen.getByText(/\$50[.,]000/)).toBeInTheDocument()
    expect(screen.getByText(/\$52[.,]000/)).toBeInTheDocument()
  })

  it('shows -- for exit price when null', () => {
    render(<TradeDetailModal trade={{ ...baseTrade, exit_price: null }} onClose={() => {}} t={t} />)
    expect(screen.getByText('--')).toBeInTheDocument()
  })

  it('renders affiliate link when provided', () => {
    render(
      <TradeDetailModal
        trade={baseTrade}
        onClose={() => {}}
        t={t}
        affiliateLink={{ exchange_type: 'bitget', affiliate_url: 'https://aff', label: 'My Aff' }}
      />,
    )
    expect(screen.getByText('My Aff')).toBeInTheDocument()
    expect(screen.getByText('https://aff')).toBeInTheDocument()
  })

  it('calls onClose when backdrop clicked', () => {
    const onClose = vi.fn()
    render(<TradeDetailModal trade={baseTrade} onClose={onClose} t={t} />)
    fireEvent.click(screen.getByLabelText('common.close'))
    expect(onClose).toHaveBeenCalled()
  })
})
