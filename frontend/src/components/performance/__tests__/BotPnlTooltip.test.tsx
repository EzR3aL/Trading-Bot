import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import BotPnlTooltip from '../BotPnlTooltip'

const t = (key: string) => key

describe('BotPnlTooltip', () => {
  it('renders nothing when not active', () => {
    const { container } = render(<BotPnlTooltip active={false} payload={[]} t={t} />)
    expect(container.firstChild).toBeNull()
  })

  it('renders nothing when payload is empty', () => {
    const { container } = render(<BotPnlTooltip active={true} payload={[]} t={t} />)
    expect(container.firstChild).toBeNull()
  })

  it('renders dailyPnl entry from payload', () => {
    render(
      <BotPnlTooltip
        active={true}
        payload={[{ name: 'PnL', value: 50.25, dataKey: 'dailyPnl' }]}
        label="2026-04-01"
        t={t}
      />,
    )
    expect(screen.getByText('PnL')).toBeInTheDocument()
    expect(screen.getByText('$50.25')).toBeInTheDocument()
    expect(screen.getByText('2026-04-01')).toBeInTheDocument()
  })

  it('renders fees and funding rows when those values > 0', () => {
    render(
      <BotPnlTooltip
        active={true}
        payload={[
          { name: 'PnL', value: 100, dataKey: 'dailyPnl' },
          { name: 'Fees', value: 5, dataKey: 'fees' },
          { name: 'Funding', value: 3, dataKey: 'funding' },
        ]}
        t={t}
      />,
    )
    expect(screen.getByText('-$5.00')).toBeInTheDocument()
    expect(screen.getByText('-$3.00')).toBeInTheDocument()
  })

  it('shows net total when fees or funding present', () => {
    render(
      <BotPnlTooltip
        active={true}
        payload={[
          { name: 'PnL', value: 100, dataKey: 'dailyPnl' },
          { name: 'Fees', value: 5, dataKey: 'fees' },
          { name: 'Funding', value: 3, dataKey: 'funding' },
        ]}
        t={t}
      />,
    )
    expect(screen.getByText('common.net')).toBeInTheDocument()
    expect(screen.getByText('$92.00')).toBeInTheDocument()
  })

  it('renders cumulative entry when present', () => {
    render(
      <BotPnlTooltip
        active={true}
        payload={[
          { name: 'PnL', value: 50, dataKey: 'dailyPnl' },
          { name: 'Cumulative', value: 200.5, dataKey: 'cumulativePnl' },
        ]}
        t={t}
      />,
    )
    expect(screen.getByText('Cumulative')).toBeInTheDocument()
    expect(screen.getByText('$200.50')).toBeInTheDocument()
  })
})
