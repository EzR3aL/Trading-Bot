import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import BotTradeHistoryModal from '../BotTradeHistoryModal'
import type { BotStatus } from '../types'

const mockGet = vi.fn()

vi.mock('../../../api/client', () => ({
  default: {
    get: (...args: unknown[]) => mockGet(...args),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
  },
  setTokenExpiry: vi.fn(),
  clearTokenExpiry: vi.fn(),
}))

vi.mock('../../ui/ExchangeLogo', () => ({
  ExchangeIcon: ({ exchange }: { exchange: string }) => <span data-testid={`exch-${exchange}`} />,
}))

vi.mock('../../ui/PnlCell', () => ({
  default: ({ pnl }: { pnl: number }) => <span data-testid="pnl">{pnl}</span>,
}))

vi.mock('../../ui/ExitReasonBadge', () => ({
  default: () => <span data-testid="exit-reason" />,
}))

vi.mock('../../ui/MobileTradeCard', () => ({
  default: () => <div data-testid="mobile-trade-card" />,
}))

vi.mock('../../ui/SizeValue', () => ({
  default: () => <span data-testid="size-value" />,
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
  formatTime: (d: string) => `time:${d}`,
}))

vi.mock('../../../constants/strategies', () => ({
  strategyLabel: (s: string) => `strategy:${s}`,
}))

vi.mock('../TradeDetailModal', () => ({
  default: () => <div data-testid="trade-detail" />,
}))

const t = (key: string) => key

const bot: BotStatus = {
  bot_config_id: 1,
  name: 'TestBot',
  strategy_type: 'edge_indicator',
  exchange_type: 'bitget',
  mode: 'demo',
  trading_pairs: ['BTCUSDT'],
  status: 'stopped',
  error_message: null,
  started_at: null,
  last_analysis: null,
  trades_today: 0,
  is_enabled: true,
  total_trades: 0,
  total_pnl: 0,
  total_fees: 0,
  total_funding: 0,
  open_trades: 0,
}

describe('BotTradeHistoryModal', () => {
  beforeEach(() => {
    mockGet.mockReset()
  })

  it('shows loading spinner while fetching', () => {
    mockGet.mockImplementation(() => new Promise(() => {}))
    const { container } = render(<BotTradeHistoryModal bot={bot} onClose={() => {}} t={t} />)
    expect(container.querySelector('.animate-spin')).toBeTruthy()
  })

  it('renders empty state when no trades returned', async () => {
    mockGet
      .mockResolvedValueOnce({
        data: {
          bot_id: 1,
          bot_name: 'TestBot',
          strategy_type: 'edge_indicator',
          exchange_type: 'bitget',
          summary: { total_trades: 0, wins: 0, losses: 0, win_rate: 0, total_pnl: 0, total_fees: 0, total_funding: 0, avg_pnl: 0, best_trade: 0, worst_trade: 0 },
          recent_trades: [],
        },
      })
      .mockResolvedValueOnce({ data: [] })

    render(<BotTradeHistoryModal bot={bot} onClose={() => {}} t={t} />)
    await waitFor(() => expect(screen.getByText('bots.noTrades')).toBeInTheDocument())
  })

  it('renders trade rows when stats include recent_trades', async () => {
    mockGet
      .mockResolvedValueOnce({
        data: {
          bot_id: 1,
          bot_name: 'TestBot',
          strategy_type: 'edge_indicator',
          exchange_type: 'bitget',
          summary: { total_trades: 1, wins: 1, losses: 0, win_rate: 100, total_pnl: 50, total_fees: 1, total_funding: 0, avg_pnl: 50, best_trade: 50, worst_trade: 0 },
          recent_trades: [
            {
              id: 1,
              symbol: 'BTCUSDT',
              side: 'long',
              size: 1,
              entry_price: 50000,
              exit_price: 51000,
              pnl: 50,
              pnl_percent: 1,
              confidence: 70,
              reason: '',
              status: 'closed',
              demo_mode: true,
              entry_time: '2026-04-01T00:00:00Z',
              exit_time: '2026-04-01T01:00:00Z',
              exit_reason: null,
              fees: 1,
              funding_paid: 0,
            },
          ],
        },
      })
      .mockResolvedValueOnce({ data: [] })

    render(<BotTradeHistoryModal bot={bot} onClose={() => {}} t={t} />)
    await waitFor(() => expect(screen.getByText('100%')).toBeInTheDocument())
    expect(screen.getAllByText('BTCUSDT').length).toBeGreaterThan(0)
  })
})
