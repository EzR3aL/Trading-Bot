import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import BotsGrid from '../BotsGrid'
import type { BotStatus } from '../types'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}))

vi.mock('../BotCard', () => ({
  default: ({ bot }: { bot: BotStatus }) => <div data-testid={`bot-${bot.bot_config_id}`}>{bot.name}</div>,
}))

vi.mock('../../ui/Skeleton', () => ({
  SkeletonBotCard: () => <div data-testid="skeleton-card" />,
}))

const makeBot = (id: number, name: string): BotStatus => ({
  bot_config_id: id,
  name,
  strategy_type: 'edge_indicator',
  exchange_type: 'bitget',
  mode: 'demo',
  trading_pairs: ['BTC/USDT'],
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
})

const baseProps = {
  loading: false,
  bots: [] as BotStatus[],
  isMobile: false,
  isAdmin: false,
  expandedBotId: null,
  actionLoading: null,
  closePositionOpen: null,
  moreMenuOpen: null,
  onNewBot: vi.fn(),
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

describe('BotsGrid', () => {
  it('renders skeleton placeholders when loading', () => {
    render(<BotsGrid {...baseProps} loading={true} />)
    expect(screen.getAllByTestId('skeleton-card').length).toBe(3)
  })

  it('renders empty state when bots is empty and not loading', () => {
    render(<BotsGrid {...baseProps} />)
    expect(screen.getByText('bots.noBots')).toBeInTheDocument()
    expect(screen.getByText('bots.noBotsAction')).toBeInTheDocument()
  })

  it('calls onNewBot when empty-state CTA clicked', () => {
    const onNewBot = vi.fn()
    render(<BotsGrid {...baseProps} onNewBot={onNewBot} />)
    fireEvent.click(screen.getByText('bots.noBotsAction'))
    expect(onNewBot).toHaveBeenCalled()
  })

  it('renders one BotCard per bot', () => {
    render(<BotsGrid {...baseProps} bots={[makeBot(1, 'A'), makeBot(2, 'B')]} />)
    expect(screen.getByTestId('bot-1')).toBeInTheDocument()
    expect(screen.getByTestId('bot-2')).toBeInTheDocument()
  })
})
