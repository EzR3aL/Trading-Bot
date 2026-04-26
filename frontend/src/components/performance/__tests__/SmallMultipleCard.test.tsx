import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import SmallMultipleCard from '../SmallMultipleCard'
import type { BotCompareData } from '../types'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}))

vi.mock('../../../constants/strategies', () => ({
  strategyLabel: (s: string) => `strat:${s}`,
}))

vi.mock('../../../utils/dateUtils', () => ({
  formatChartCurrency: (v: number) => `$${v}`,
  formatChartDate: (d: string) => d,
}))

// recharts ResponsiveContainer needs a real width to render — stub it
vi.mock('recharts', async () => {
  const actual = await vi.importActual<typeof import('recharts')>('recharts')
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: React.ReactNode }) => <div data-testid="rc-resp">{children}</div>,
  }
})

const baseBot: BotCompareData = {
  bot_id: 1,
  name: 'BotX',
  strategy_type: 'edge_indicator',
  exchange_type: 'bitget',
  mode: 'demo',
  total_trades: 4,
  total_pnl: 25,
  total_fees: 1,
  total_funding: 0,
  win_rate: 50,
  wins: 2,
  last_direction: 'SHORT',
  last_confidence: 50,
  series: [{ date: 'd1', cumulative_pnl: 5 }, { date: 'd2', cumulative_pnl: 25 }],
}

const baseProps = {
  bot: baseBot,
  color: '#abcdef',
  yDomain: [0, 100] as [number, number],
  chartGridColor: '#222',
  chartTickColor: '#999',
  isSelected: false,
  onClick: vi.fn(),
}

describe('SmallMultipleCard', () => {
  it('renders bot name and mode', () => {
    render(<SmallMultipleCard {...baseProps} />)
    expect(screen.getByText('BotX')).toBeInTheDocument()
    expect(screen.getByText('DEMO')).toBeInTheDocument()
  })

  it('renders formatted PnL', () => {
    render(<SmallMultipleCard {...baseProps} />)
    expect(screen.getByText('+$25.00')).toBeInTheDocument()
  })

  it('renders win rate chip', () => {
    render(<SmallMultipleCard {...baseProps} />)
    expect(screen.getByText('50%')).toBeInTheDocument()
  })

  it('renders wins/total chip', () => {
    render(<SmallMultipleCard {...baseProps} />)
    expect(screen.getByText('2/4')).toBeInTheDocument()
  })

  it('renders SHORT direction marker when last_direction=SHORT', () => {
    render(<SmallMultipleCard {...baseProps} />)
    expect(screen.getByText('SHORT')).toBeInTheDocument()
  })

  it('omits last-trade marker when last_direction is null', () => {
    render(<SmallMultipleCard {...baseProps} bot={{ ...baseBot, last_direction: null }} />)
    expect(screen.queryByText('SHORT')).not.toBeInTheDocument()
    expect(screen.queryByText('LONG')).not.toBeInTheDocument()
  })

  it('calls onClick when the tile is clicked', () => {
    const onClick = vi.fn()
    render(<SmallMultipleCard {...baseProps} onClick={onClick} />)
    fireEvent.click(screen.getByText('BotX').closest('button')!)
    expect(onClick).toHaveBeenCalled()
  })

  it('applies selected ring class when isSelected=true', () => {
    render(<SmallMultipleCard {...baseProps} isSelected={true} />)
    const btn = screen.getByText('BotX').closest('button')!
    expect(btn.className).toContain('ring-1')
  })
})
