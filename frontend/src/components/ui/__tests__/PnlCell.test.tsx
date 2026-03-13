import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import PnlCell from '../PnlCell'

// Mock react-i18next
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => {
      const translations: Record<string, string> = {
        'trades.fees': 'Fees',
        'dashboard.funding': 'Funding',
        'common.total': 'Total',
      }
      return translations[key] || key
    },
  }),
}))

describe('PnlCell', () => {
  it('should display formatted positive PnL with triangle indicator', () => {
    render(<PnlCell pnl={150.75} fees={5} fundingPaid={2} />)

    expect(screen.getByText('▲ +$150.75')).toBeInTheDocument()
  })

  it('should display formatted negative PnL with triangle indicator', () => {
    render(<PnlCell pnl={-42.30} fees={3} fundingPaid={1} />)

    expect(screen.getByText('▼ $42.30')).toBeInTheDocument()
  })

  it('should display "--" for null PnL', () => {
    render(<PnlCell pnl={null} fees={0} fundingPaid={0} />)

    expect(screen.getByText('--')).toBeInTheDocument()
  })

  it('should display zero PnL with plus prefix and triangle', () => {
    render(<PnlCell pnl={0} fees={0} fundingPaid={0} />)

    expect(screen.getByText('▲ +$0.00')).toBeInTheDocument()
  })

  it('should render children instead of default formatting', () => {
    render(
      <PnlCell pnl={100} fees={5} fundingPaid={2}>
        <span>Custom content</span>
      </PnlCell>
    )

    expect(screen.getByText('Custom content')).toBeInTheDocument()
    expect(screen.queryByText('▲ +$100.00')).not.toBeInTheDocument()
  })

  it('should apply custom className when provided', () => {
    render(<PnlCell pnl={50} fees={1} fundingPaid={0} className="custom-class" />)

    const span = screen.getByText('▲ +$50.00')
    expect(span.className).toContain('custom-class')
  })

  it('should apply profit color class for positive PnL', () => {
    render(<PnlCell pnl={100} fees={0} fundingPaid={0} />)

    const span = screen.getByText('▲ +$100.00')
    expect(span.className).toContain('text-profit')
  })

  it('should apply loss color class for negative PnL', () => {
    render(<PnlCell pnl={-50} fees={0} fundingPaid={0} />)

    const span = screen.getByText('▼ $50.00')
    expect(span.className).toContain('text-loss')
  })

  it('should apply loss color class for null PnL', () => {
    render(<PnlCell pnl={null} fees={0} fundingPaid={0} />)

    const span = screen.getByText('--')
    expect(span.className).toContain('text-loss')
  })
})
