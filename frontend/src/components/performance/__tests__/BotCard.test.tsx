import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import BotCard from '../BotCard'
import type { BotCompareData } from '../types'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: unknown) => {
      if (opts && typeof opts === 'object') {
        return `${key}:${JSON.stringify(opts)}`
      }
      return key
    },
  }),
}))

vi.mock('../../../constants/strategies', () => ({
  strategyLabel: (s: string) => `strat:${s}`,
}))

vi.mock('../Sparkline', () => ({
  default: () => <div data-testid="sparkline" />,
}))

const baseBot: BotCompareData = {
  bot_id: 1,
  name: 'PerfBot',
  strategy_type: 'edge_indicator',
  exchange_type: 'bitget',
  mode: 'live',
  total_trades: 10,
  total_pnl: 150,
  total_fees: 5,
  total_funding: 1,
  win_rate: 70,
  wins: 7,
  last_direction: 'LONG',
  last_confidence: 80,
  series: [{ date: 'd1', cumulative_pnl: 1 }, { date: 'd2', cumulative_pnl: 5 }],
}

const baseProps = {
  bot: baseBot,
  color: '#00ff00',
  isSelected: false,
  isHovered: false,
  onClick: vi.fn(),
  onMouseEnter: vi.fn(),
  onMouseLeave: vi.fn(),
  index: 0,
}

describe('performance/BotCard', () => {
  it('renders bot name + strategy + mode', () => {
    render(<BotCard {...baseProps} />)
    expect(screen.getByText('PerfBot')).toBeInTheDocument()
    expect(screen.getByText('strat:edge_indicator')).toBeInTheDocument()
    expect(screen.getByText('LIVE')).toBeInTheDocument()
  })

  it('renders formatted PnL with + prefix when positive', () => {
    render(<BotCard {...baseProps} />)
    expect(screen.getByText('+$150.00')).toBeInTheDocument()
  })

  it('renders formatted PnL without + prefix when negative', () => {
    render(<BotCard {...baseProps} bot={{ ...baseBot, total_pnl: -50.5 }} />)
    expect(screen.getByText('$-50.50')).toBeInTheDocument()
  })

  it('renders win rate', () => {
    render(<BotCard {...baseProps} />)
    expect(screen.getByText('70%')).toBeInTheDocument()
  })

  it('renders wins/total chip', () => {
    render(<BotCard {...baseProps} />)
    expect(screen.getByText('7/10')).toBeInTheDocument()
  })

  it('shows last_direction badge', () => {
    render(<BotCard {...baseProps} />)
    expect(screen.getByText('LONG')).toBeInTheDocument()
  })

  it('renders the Sparkline subcomponent', () => {
    render(<BotCard {...baseProps} />)
    expect(screen.getByTestId('sparkline')).toBeInTheDocument()
  })

  it('calls onClick when card clicked', () => {
    const onClick = vi.fn()
    render(<BotCard {...baseProps} onClick={onClick} />)
    fireEvent.click(screen.getByText('PerfBot').closest('button')!)
    expect(onClick).toHaveBeenCalled()
  })

  it('calls onMouseEnter and onMouseLeave on hover events', () => {
    const onMouseEnter = vi.fn()
    const onMouseLeave = vi.fn()
    render(<BotCard {...baseProps} onMouseEnter={onMouseEnter} onMouseLeave={onMouseLeave} />)
    const btn = screen.getByText('PerfBot').closest('button')!
    fireEvent.mouseEnter(btn)
    fireEvent.mouseLeave(btn)
    expect(onMouseEnter).toHaveBeenCalled()
    expect(onMouseLeave).toHaveBeenCalled()
  })
})
