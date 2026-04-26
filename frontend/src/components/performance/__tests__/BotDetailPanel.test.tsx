import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { useRef } from 'react'
import BotDetailPanel from '../BotDetailPanel'
import type { BotCompareData, BotDetailStats } from '../types'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}))

vi.mock('../../ui/PnlCell', () => ({
  default: ({ pnl }: { pnl: number }) => <span data-testid="pnl">{pnl}</span>,
}))

vi.mock('../../ui/ExchangeLogo', () => ({
  ExchangeIcon: ({ exchange }: { exchange: string }) => <span data-testid={`exch-${exchange}`} />,
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

vi.mock('../StatCard', () => ({
  default: ({ label, value }: { label: string; value: string }) => (
    <div data-testid={`stat-${label}`}>{value}</div>
  ),
}))

vi.mock('../BotPnlTooltip', () => ({ default: () => null }))

vi.mock('../../../constants/strategies', () => ({
  strategyLabel: (s: string) => `strat:${s}`,
}))

vi.mock('../../../utils/dateUtils', () => ({
  formatChartCurrency: (v: number) => `$${v}`,
  formatDate: (s: string) => `date:${s}`,
  formatTime: (s: string) => `time:${s}`,
}))

// Stub recharts so we don't need a real layout
vi.mock('recharts', async () => {
  const actual = await vi.importActual<typeof import('recharts')>('recharts')
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: React.ReactNode }) => <div data-testid="rc-resp">{children}</div>,
  }
})

const stats: BotDetailStats = {
  bot_id: 1,
  bot_name: 'PerfBot',
  summary: {
    total_trades: 10,
    wins: 6,
    losses: 4,
    win_rate: 60,
    total_pnl: 200,
    total_fees: 5,
    total_funding: 1,
    avg_pnl: 20,
    best_trade: 50,
    worst_trade: -30,
  },
  daily_series: [{ date: 'd1', pnl: 10, cumulative_pnl: 10, trades: 1, wins: 1, fees: 1, funding: 0 }],
  recent_trades: [
    {
      id: 1,
      symbol: 'BTCUSDT',
      side: 'long',
      entry_price: 50000,
      exit_price: 51000,
      pnl: 50,
      pnl_percent: 1,
      confidence: 70,
      reason: '',
      status: 'closed',
      fees: 1,
      funding_paid: 0,
      demo_mode: false,
      entry_time: '2026-04-01T00:00:00Z',
      exit_time: '2026-04-01T01:00:00Z',
      exit_reason: null,
    },
  ],
}

const selectedBotData: BotCompareData = {
  bot_id: 1,
  name: 'PerfBot',
  strategy_type: 'edge_indicator',
  exchange_type: 'bitget',
  mode: 'live',
  total_trades: 10,
  total_pnl: 200,
  total_fees: 5,
  total_funding: 1,
  win_rate: 60,
  wins: 6,
  last_direction: 'LONG',
  last_confidence: 80,
  series: [],
}

function Wrapper(props: { sharingTrade: BotDetailStats['recent_trades'][0] | null }) {
  const shareResolveRef = useRef<((el: HTMLDivElement | null) => void) | null>(null)
  return (
    <BotDetailPanel
      botDetail={stats}
      selectedBotData={selectedBotData}
      affiliateLink={null}
      botChartData={[]}
      isMobile={false}
      chartGridColor="#222"
      chartTickColor="#999"
      refColor="#444"
      sharingTrade={props.sharingTrade}
      shareResolveRef={shareResolveRef}
      onSelectTrade={vi.fn()}
      onMobileDirectShare={vi.fn()}
    />
  )
}

describe('BotDetailPanel', () => {
  it('renders the bot name in the header', () => {
    render(<Wrapper sharingTrade={null} />)
    expect(screen.getByText(/PerfBot/)).toBeInTheDocument()
  })

  it('renders summary stat tiles (win rate, best, worst)', () => {
    render(<Wrapper sharingTrade={null} />)
    expect(screen.getByTestId('stat-performance.winRate').textContent).toBe('60%')
    expect(screen.getByTestId('stat-performance.bestTrade').textContent).toBe('+$50.00')
    expect(screen.getByTestId('stat-performance.worstTrade').textContent).toBe('$-30.00')
  })

  it('renders the recent-trades table heading', () => {
    render(<Wrapper sharingTrade={null} />)
    expect(screen.getByText('performance.recentTrades')).toBeInTheDocument()
  })

  it('renders trade row symbol in desktop table', () => {
    render(<Wrapper sharingTrade={null} />)
    expect(screen.getAllByText('BTCUSDT').length).toBeGreaterThan(0)
  })
})
