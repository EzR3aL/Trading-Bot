import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import BotCard from '../BotCard'
import type { BotStatus } from '../types'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: string) => fallback || key,
  }),
}))

vi.mock('../../ui/ExchangeLogo', () => ({
  ExchangeIcon: ({ exchange }: { exchange: string }) => <span data-testid={`exch-${exchange}`} />,
}))

vi.mock('../../ui/PnlCell', () => ({
  default: ({ pnl }: { pnl: number }) => <span data-testid="pnl">{pnl}</span>,
}))

vi.mock('../../../constants/strategies', () => ({
  strategyLabel: (s: string) => `strategy:${s}`,
}))

vi.mock('../../../utils/dateUtils', () => ({
  formatTime: (s: string) => `time:${s}`,
}))

vi.mock('../../../utils/timezone', () => ({
  utcHourToLocal: (h: number) => h,
}))

const baseBot: BotStatus = {
  bot_config_id: 11,
  name: 'AlphaBot',
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
  total_trades: 5,
  total_pnl: 100,
  total_fees: 1,
  total_funding: 0.5,
  open_trades: 0,
}

const baseProps = {
  bot: baseBot,
  isFirst: false,
  isMobile: false,
  isAdmin: false,
  isExpanded: false,
  actionLoading: null,
  closePositionOpen: null,
  moreMenuOpen: null,
  onToggleExpand: vi.fn(),
  onStart: vi.fn(),
  onStopClick: vi.fn(),
  onClosePosition: vi.fn(),
  onSetClosePositionOpen: vi.fn(),
  onShowHistory: vi.fn(),
  onSetMoreMenuOpen: vi.fn(),
  onEdit: vi.fn(),
  onDuplicate: vi.fn(),
  onDelete: vi.fn(),
}

describe('BotCard', () => {
  it('renders the bot name and trading pairs', () => {
    render(<BotCard {...baseProps} />)
    expect(screen.getByText('AlphaBot')).toBeInTheDocument()
    expect(screen.getByText('BTCUSDT')).toBeInTheDocument()
  })

  it('renders mode badge in upper case', () => {
    render(<BotCard {...baseProps} />)
    expect(screen.getByText('DEMO')).toBeInTheDocument()
  })

  it('renders Start button when bot is stopped', () => {
    render(<BotCard {...baseProps} />)
    expect(screen.getByLabelText('bots.start AlphaBot')).toBeInTheDocument()
  })

  it('renders Stop button when bot is running', () => {
    render(<BotCard {...baseProps} bot={{ ...baseBot, status: 'running' }} />)
    expect(screen.getByLabelText('bots.stop AlphaBot')).toBeInTheDocument()
  })

  it('calls onStart with bot id when Start button clicked', () => {
    const onStart = vi.fn()
    render(<BotCard {...baseProps} onStart={onStart} />)
    fireEvent.click(screen.getByLabelText('bots.start AlphaBot'))
    expect(onStart).toHaveBeenCalledWith(11)
  })

  it('calls onStopClick with bot id when Stop button clicked on running bot', () => {
    const onStopClick = vi.fn()
    render(<BotCard {...baseProps} bot={{ ...baseBot, status: 'running' }} onStopClick={onStopClick} />)
    fireEvent.click(screen.getByLabelText('bots.stop AlphaBot'))
    expect(onStopClick).toHaveBeenCalledWith(11)
  })

  it('calls onShowHistory with the bot when history button clicked', () => {
    const onShowHistory = vi.fn()
    render(<BotCard {...baseProps} onShowHistory={onShowHistory} />)
    fireEvent.click(screen.getByTitle('bots.tradeHistory'))
    expect(onShowHistory).toHaveBeenCalledWith(baseBot)
  })

  it('shows error message when bot.error_message is set', () => {
    render(<BotCard {...baseProps} bot={{ ...baseBot, error_message: 'Network down' }} />)
    expect(screen.getByText('Network down')).toBeInTheDocument()
  })

  it('shows Close Position single-pair button when open_trades > 0', () => {
    render(<BotCard {...baseProps} bot={{ ...baseBot, open_trades: 1 }} />)
    expect(screen.getByText(/bots\.closePosition BTCUSDT/)).toBeInTheDocument()
  })

  it('shows hyperliquid setup warning for non-admin when builder_fee_approved=false and bot not running', () => {
    render(
      <BotCard
        {...baseProps}
        isAdmin={false}
        bot={{ ...baseBot, exchange_type: 'hyperliquid', builder_fee_approved: false }}
      />,
    )
    expect(screen.getByText(/Einrichtung in Einstellungen erforderlich/)).toBeInTheDocument()
  })

  it('hides hyperliquid setup warning when isAdmin=true', () => {
    render(
      <BotCard
        {...baseProps}
        isAdmin={true}
        bot={{ ...baseBot, exchange_type: 'hyperliquid', builder_fee_approved: false }}
      />,
    )
    expect(screen.queryByText(/Einrichtung in Einstellungen erforderlich/)).not.toBeInTheDocument()
  })
})
