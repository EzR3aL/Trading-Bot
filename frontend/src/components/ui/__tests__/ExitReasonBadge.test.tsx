import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import ExitReasonBadge from '../ExitReasonBadge'

// Mock react-i18next — covers legacy aliases + all 10 new codes from #194.
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => {
      const translations: Record<string, string> = {
        // Legacy
        'trades.exitReasons.TAKE_PROFIT': 'Take Profit',
        'trades.exitReasons.STOP_LOSS': 'Stop Loss',
        'trades.exitReasons.TRAILING_STOP': 'Trailing Stop',
        'trades.exitReasons.STRATEGY_EXIT': 'Strategy Exit',
        'trades.exitReasons.EXTERNAL_CLOSE': 'Externally closed',
        'trades.exitReasons.MANUAL_CLOSE': 'Manually closed (legacy)',
        'trades.exitReasons.unknown': 'Unknown',
        // New precise codes
        'trades.exitReasons.TRAILING_STOP_NATIVE': 'Trailing Stop (Exchange)',
        'trades.exitReasons.TRAILING_STOP_SOFTWARE': 'Trailing Stop (Bot)',
        'trades.exitReasons.TAKE_PROFIT_NATIVE': 'Take Profit (Exchange)',
        'trades.exitReasons.STOP_LOSS_NATIVE': 'Stop Loss (Exchange)',
        'trades.exitReasons.MANUAL_CLOSE_UI': 'Manually closed (Dashboard)',
        'trades.exitReasons.MANUAL_CLOSE_EXCHANGE': 'Manually closed (Exchange)',
        'trades.exitReasons.LIQUIDATION': 'Liquidation',
        'trades.exitReasons.FUNDING_EXPIRY': 'Funding expiry',
        'trades.exitReasons.EXTERNAL_CLOSE_UNKNOWN': 'Externally closed (unknown)',
      }
      return translations[key] || key
    },
  }),
}))

describe('ExitReasonBadge', () => {
  it('should render null when reason is null', () => {
    const { container } = render(<ExitReasonBadge reason={null} />)

    expect(container.firstChild).toBeNull()
  })

  it('should render Take Profit badge', () => {
    render(<ExitReasonBadge reason="TAKE_PROFIT" />)

    expect(screen.getByText('Take Profit')).toBeInTheDocument()
  })

  it('should render Stop Loss badge', () => {
    render(<ExitReasonBadge reason="STOP_LOSS" />)

    expect(screen.getByText('Stop Loss')).toBeInTheDocument()
  })

  it('should render Trailing Stop badge', () => {
    render(<ExitReasonBadge reason="TRAILING_STOP" />)

    expect(screen.getByText('Trailing Stop')).toBeInTheDocument()
  })

  it('should render Strategy Exit badge', () => {
    render(<ExitReasonBadge reason="STRATEGY_EXIT" />)

    expect(screen.getByText('Strategy Exit')).toBeInTheDocument()
  })

  it('should render External Close badge', () => {
    render(<ExitReasonBadge reason="EXTERNAL_CLOSE" />)

    expect(screen.getByText('Externally closed')).toBeInTheDocument()
  })

  it('should render Manual Close badge', () => {
    render(<ExitReasonBadge reason="MANUAL_CLOSE" />)

    expect(screen.getByText('Manually closed (legacy)')).toBeInTheDocument()
  })

  it('should render Unknown for unrecognized reason', () => {
    render(<ExitReasonBadge reason="SOMETHING_ELSE" />)

    expect(screen.getByText('Unknown')).toBeInTheDocument()
  })

  it('should match reason by prefix (e.g. STRATEGY_EXIT with extra info)', () => {
    render(<ExitReasonBadge reason="STRATEGY_EXIT [BotName] some reason" />)

    expect(screen.getByText('Strategy Exit')).toBeInTheDocument()
  })

  it('should apply emerald styles for TAKE_PROFIT', () => {
    const { container } = render(<ExitReasonBadge reason="TAKE_PROFIT" />)

    const badge = container.firstChild as HTMLElement
    expect(badge.className).toContain('bg-emerald-500/10')
    expect(badge.className).toContain('text-emerald-400')
  })

  it('should apply red styles for STOP_LOSS', () => {
    const { container } = render(<ExitReasonBadge reason="STOP_LOSS" />)

    const badge = container.firstChild as HTMLElement
    expect(badge.className).toContain('bg-red-500/10')
    expect(badge.className).toContain('text-red-400')
  })

  it('should apply blue styles for TRAILING_STOP', () => {
    const { container } = render(<ExitReasonBadge reason="TRAILING_STOP" />)

    const badge = container.firstChild as HTMLElement
    expect(badge.className).toContain('bg-blue-500/10')
    expect(badge.className).toContain('text-blue-400')
  })

  it('should render compact variant', () => {
    const { container } = render(<ExitReasonBadge reason="TAKE_PROFIT" compact />)

    const badge = container.firstChild as HTMLElement
    // Compact should not have the px-2.5 / rounded-full badge styling
    expect(badge.className).not.toContain('rounded-full')
    expect(screen.getByText('Take Profit')).toBeInTheDocument()
  })

  // ── New precise codes (issue #194) ─────────────────────────────────

  it('should render TRAILING_STOP_NATIVE with correct label and emerald accent', () => {
    const { container } = render(<ExitReasonBadge reason="TRAILING_STOP_NATIVE" />)

    expect(screen.getByText('Trailing Stop (Exchange)')).toBeInTheDocument()
    const badge = container.firstChild as HTMLElement
    expect(badge.className).toContain('bg-emerald-500/10')
    expect(badge.className).toContain('text-emerald-300')
  })

  it('should render TRAILING_STOP_SOFTWARE with correct label and blue accent', () => {
    const { container } = render(<ExitReasonBadge reason="TRAILING_STOP_SOFTWARE" />)

    expect(screen.getByText('Trailing Stop (Bot)')).toBeInTheDocument()
    const badge = container.firstChild as HTMLElement
    expect(badge.className).toContain('bg-blue-500/10')
    expect(badge.className).toContain('text-blue-300')
  })

  it('should render TAKE_PROFIT_NATIVE with correct label', () => {
    const { container } = render(<ExitReasonBadge reason="TAKE_PROFIT_NATIVE" />)

    expect(screen.getByText('Take Profit (Exchange)')).toBeInTheDocument()
    const badge = container.firstChild as HTMLElement
    expect(badge.className).toContain('bg-emerald-500/10')
  })

  it('should render STOP_LOSS_NATIVE with correct label and red accent', () => {
    const { container } = render(<ExitReasonBadge reason="STOP_LOSS_NATIVE" />)

    expect(screen.getByText('Stop Loss (Exchange)')).toBeInTheDocument()
    const badge = container.firstChild as HTMLElement
    expect(badge.className).toContain('bg-red-500/10')
    expect(badge.className).toContain('text-red-400')
  })

  it('should render MANUAL_CLOSE_UI with correct label', () => {
    render(<ExitReasonBadge reason="MANUAL_CLOSE_UI" />)

    expect(screen.getByText('Manually closed (Dashboard)')).toBeInTheDocument()
  })

  it('should render MANUAL_CLOSE_EXCHANGE with correct label', () => {
    render(<ExitReasonBadge reason="MANUAL_CLOSE_EXCHANGE" />)

    expect(screen.getByText('Manually closed (Exchange)')).toBeInTheDocument()
  })

  it('should render LIQUIDATION with bold red accent', () => {
    const { container } = render(<ExitReasonBadge reason="LIQUIDATION" />)

    expect(screen.getByText('Liquidation')).toBeInTheDocument()
    const badge = container.firstChild as HTMLElement
    expect(badge.className).toContain('text-red-500')
  })

  it('should render FUNDING_EXPIRY with slate accent', () => {
    const { container } = render(<ExitReasonBadge reason="FUNDING_EXPIRY" />)

    expect(screen.getByText('Funding expiry')).toBeInTheDocument()
    const badge = container.firstChild as HTMLElement
    expect(badge.className).toContain('text-slate-300')
  })

  it('should render EXTERNAL_CLOSE_UNKNOWN with correct label', () => {
    render(<ExitReasonBadge reason="EXTERNAL_CLOSE_UNKNOWN" />)

    expect(screen.getByText('Externally closed (unknown)')).toBeInTheDocument()
  })

  // ── Prefix disambiguation: longest match wins ──────────────────────

  it('should prefer TRAILING_STOP_NATIVE over TRAILING_STOP when both prefixes apply', () => {
    render(<ExitReasonBadge reason="TRAILING_STOP_NATIVE" />)

    // Must NOT fall back to the legacy "Trailing Stop" label.
    expect(screen.getByText('Trailing Stop (Exchange)')).toBeInTheDocument()
    expect(screen.queryByText('Trailing Stop')).not.toBeInTheDocument()
  })

  it('should prefer TAKE_PROFIT_NATIVE over TAKE_PROFIT when both prefixes apply', () => {
    render(<ExitReasonBadge reason="TAKE_PROFIT_NATIVE" />)

    expect(screen.getByText('Take Profit (Exchange)')).toBeInTheDocument()
    expect(screen.queryByText('Take Profit')).not.toBeInTheDocument()
  })

  it('should prefer STOP_LOSS_NATIVE over STOP_LOSS when both prefixes apply', () => {
    render(<ExitReasonBadge reason="STOP_LOSS_NATIVE" />)

    expect(screen.getByText('Stop Loss (Exchange)')).toBeInTheDocument()
    expect(screen.queryByText('Stop Loss')).not.toBeInTheDocument()
  })

  it('should prefer MANUAL_CLOSE_EXCHANGE over MANUAL_CLOSE when both prefixes apply', () => {
    render(<ExitReasonBadge reason="MANUAL_CLOSE_EXCHANGE" />)

    expect(screen.getByText('Manually closed (Exchange)')).toBeInTheDocument()
    expect(screen.queryByText('Manually closed (legacy)')).not.toBeInTheDocument()
  })

  it('should prefer EXTERNAL_CLOSE_UNKNOWN over EXTERNAL_CLOSE when both prefixes apply', () => {
    render(<ExitReasonBadge reason="EXTERNAL_CLOSE_UNKNOWN" />)

    expect(screen.getByText('Externally closed (unknown)')).toBeInTheDocument()
    expect(screen.queryByText('Externally closed')).not.toBeInTheDocument()
  })
})
